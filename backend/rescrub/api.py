"""HTTP API for the website plus tracking-data reads (reference: docs/API.md).

Served at https://<your domain>/api (Caddy strips /api; uvicorn runs with --root-path /api):

    uvicorn rescrub.main:app --host 0.0.0.0 --port 8000 --root-path /api --proxy-headers

Every /sessions/... request needs a signed-in user and only reaches that user's own
recordings. Every state-changing request must come from an allowed Origin.
"""

import json
import logging
import re
import tempfile
import time
import uuid
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import auth, db, emails, report
from .pipeline.surfaces import parse_zones
from .pipeline.video_io import VideoError, looks_like_mp4, probe
from .settings import Settings, get_settings
from .storage import LocalStorage, get_storage

log = logging.getLogger("rescrub.api")


class ReviewUpdate(BaseModel):
    reviewStatus: Literal["needs_review", "confirmed", "dismissed"]


class LoginRequest(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=1024)  # auth.MAX_PASSWORD gives the user-facing message


def _uuid(value: str) -> str:
    try:
        return str(uuid.UUID(value))
    except ValueError:
        raise HTTPException(404, "Session not found.") from None


MAX_NAME = 120        # same limits as the website (web/lib/api.ts)
SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
MAX_CONTEXT = 2000


class RateLimiter:
    def __init__(self, limit: int, window_sec: float, message: str):
        self.limit, self.window, self.message = limit, window_sec, message
        self.hits: dict[str, deque] = defaultdict(deque)

    def check(self, client: str) -> None:
        now = time.monotonic()
        if len(self.hits) > 50_000:  # bound memory if many clients (or spoofed addresses) appear
            self.hits = defaultdict(deque, {k: v for k, v in self.hits.items() if v and now - v[-1] <= self.window})
        q = self.hits[client]
        while q and now - q[0] > self.window:
            q.popleft()
        if len(q) >= self.limit:
            raise HTTPException(429, self.message)
        q.append(now)


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def create_app(settings: Settings | None = None, pool=None, storage=None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.pool = pool or db.connect(settings.database_url)
        app.state.storage = storage or get_storage(settings)
        yield
        if pool is None:
            app.state.pool.close()

    # Interactive docs reveal every endpoint; off unless ENABLE_API_DOCS=true (development).
    docs = settings.enable_api_docs
    app = FastAPI(title="reScrub API", lifespan=lifespan, docs_url="/docs" if docs else None,
                  redoc_url="/redoc" if docs else None, openapi_url="/openapi.json" if docs else None)
    # The website calls the API on its own origin (/api), so CORS is only needed if the API is
    # ever served from another host; credentials are then limited to the listed origins.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Content-Type"],
    )
    cookie_name = settings.session_cookie_name
    login_ip_limiter = RateLimiter(settings.logins_per_15min_per_ip, 900,
                                   "Too many sign-in attempts. Please wait a few minutes.")
    register_limiter = RateLimiter(settings.registrations_per_hour_per_ip, 3600,
                                   "Too many new accounts from this network. Please try again later.")
    login_email_limiter = RateLimiter(settings.logins_per_15min_per_email, 900,
                                      "Too many sign-in attempts. Please wait a few minutes.")
    upload_limiter = RateLimiter(settings.uploads_per_hour_per_client, 3600,
                                 "Too many uploads. Please wait before trying again.")
    # The website polls every 3 s; this allows several open tabs but stops hammering.
    api_limiter = RateLimiter(settings.requests_per_minute_per_client, 60, "Too many requests. Please slow down.")
    # Each report is a paid Gemini call; limited per account.
    report_limiter = RateLimiter(settings.reports_per_hour_per_user, 3600,
                                 "Too many reports this hour. Please wait before writing another.")

    # The website reads `error` from every failed response.
    @app.exception_handler(StarletteHTTPException)
    async def http_error(_req, exc: StarletteHTTPException):
        return JSONResponse({"error": str(exc.detail)}, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_req, exc: RequestValidationError):
        first = exc.errors()[0] if exc.errors() else {}
        field = ".".join(str(p) for p in first.get("loc", [])[1:])
        return JSONResponse({"error": f"Invalid request: {field} {first.get('msg', '')}".strip()}, status_code=422)

    def current_user(request: Request) -> dict:
        user = auth.user_for_token(app.state.pool, request.cookies.get(cookie_name, ""))
        if user is None:
            raise HTTPException(401, "Please sign in.")
        return user

    def same_site(request: Request) -> None:
        auth.check_origin(request, settings.cors_origin_list)

    def session_or_404(session_id: str, user: dict) -> dict:
        """The recording, only if it belongs to this user (404 otherwise, so IDs can't be probed)."""
        s = db.get_session(app.state.pool, _uuid(session_id))
        if s is None or s["owner_id"] is None or str(s["owner_id"]) != str(user["id"]):
            raise HTTPException(404, "Session not found.")
        return s

    @app.middleware("http")
    async def check_upload_first(request: Request, call_next):
        """FastAPI reads (and spools to disk) a whole form body before running any dependency, so an
        upload's origin, sign-in, size and limits are checked here, before the body is read."""
        if request.method == "POST" and request.url.path.rstrip("/").endswith("/sessions"):
            try:
                same_site(request)
                user = await run_in_threadpool(current_user, request)
                length = request.headers.get("content-length", "")
                if not length.isdigit():
                    raise HTTPException(411, "The upload must state its size (Content-Length).")
                if int(length) > settings.max_upload_mb * 1024 * 1024 + 1024 * 1024:
                    raise HTTPException(413, f"The video is larger than {settings.max_upload_mb} MB.")
                upload_limiter.check(client_ip(request))
                daily = settings.uploads_per_day_per_user
                if daily and await run_in_threadpool(db.uploads_since, app.state.pool, user["id"], 24) >= daily:
                    raise HTTPException(429, f"You can upload {daily} recordings a day. Please try again tomorrow.")
            except HTTPException as e:
                return JSONResponse({"error": str(e.detail)}, status_code=e.status_code)
        return await call_next(request)

    @app.get("/health")
    def health():
        with app.state.pool.connection() as c:
            c.execute("SELECT 1")
        return {"ok": True}

    # --- sign-in ----------------------------------------------------------------

    @app.post("/auth/login", dependencies=[Depends(same_site)])
    def login(body: LoginRequest, request: Request, response: Response):
        login_ip_limiter.check(client_ip(request))
        login_email_limiter.check(auth.normalize_email(body.email)[:254])
        user = auth.authenticate(app.state.pool, body.email, body.password)
        if user is None:
            # Never say whether the email or the password was wrong.
            raise HTTPException(401, "Email or password is incorrect.")
        set_session_cookie(response, user["id"])
        log.info("login ok user=%s", user["id"])
        return {"email": user["email"], "role": user["role"]}

    def set_session_cookie(response: Response, user_id) -> None:
        token, expires = auth.start_session(app.state.pool, user_id, settings.session_ttl)
        response.set_cookie(
            cookie_name, token, expires=expires, path="/", secure=settings.cookie_secure,
            httponly=True, samesite="lax",
        )

    @app.get("/auth/options")
    def auth_options():
        return {"registration": settings.allow_registration, "emailDomains": settings.registration_domain_list}

    @app.post("/auth/register", status_code=201, dependencies=[Depends(same_site)])
    def register(body: LoginRequest, request: Request, response: Response):
        if not settings.allow_registration:
            raise HTTPException(403, "New accounts can't be created on this site. Ask its administrator for one.")
        register_limiter.check(client_ip(request))
        email = auth.normalize_email(body.email)
        domains = settings.registration_domain_list
        if domains and email.rpartition("@")[2] not in domains:
            raise HTTPException(403, "Sign-up here needs an email address at " + ", ".join(domains) + ".")
        if problem := emails.email_problem(email, check_dns=settings.check_email_dns):
            raise HTTPException(400, problem)
        try:
            uid = auth.create_user(app.state.pool, email, body.password)
        except auth.EmailTaken:
            # Unavoidable for open sign-up without email verification; rate limited above.
            raise HTTPException(409, "An account with this email already exists. Sign in instead.") from None
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        set_session_cookie(response, uid)
        log.info("register ok user=%s", uid)
        return {"email": email, "role": "member"}

    @app.post("/auth/logout", dependencies=[Depends(same_site)])
    def logout(request: Request, response: Response):
        auth.end_session(app.state.pool, request.cookies.get(cookie_name, ""))
        response.delete_cookie(cookie_name, path="/", secure=settings.cookie_secure, httponly=True, samesite="lax")
        return {}

    @app.get("/auth/me")
    def me(user: dict = Depends(current_user)):
        return {"email": user["email"], "role": user["role"]}

    # --- website contract ---------------------------------------------------

    @app.post("/sessions", dependencies=[Depends(same_site)])
    async def create_session(
        request: Request,
        user: dict = Depends(current_user),
        video: UploadFile = File(...),
        name: str = Form(""),
        procedureContext: str = Form(""),
        designatedObjects: str = Form(""),  # no longer sent by the website; kept for older clients
        acknowledged: str = Form("false"),
        zones: str = Form(""),
    ):
        # Origin, sign-in, Content-Length and upload limits were checked by check_upload_first.
        limit = settings.max_upload_mb * 1024 * 1024
        if acknowledged.lower() != "true":
            raise HTTPException(400, "Please confirm the recording acknowledgment before uploading.")
        if len(name.strip()) > MAX_NAME or len(procedureContext.strip()) > MAX_CONTEXT:
            raise HTTPException(400, f"The name must be at most {MAX_NAME} characters and the context {MAX_CONTEXT}.")
        zones_data = None
        if zones.strip():
            try:
                zones_data = json.loads(zones)
                parse_zones(zones_data, 64, 64)  # shape check only
            except (ValueError, TypeError) as e:
                raise HTTPException(400, f"Invalid zones: {e}") from None

        sid = str(uuid.uuid4())
        key = f"uploads/{uuid.uuid4()}.mp4"
        with tempfile.TemporaryDirectory(prefix="rescrub-up-") as tmp:
            path = Path(tmp) / "upload.mp4"
            size = 0
            with open(path, "wb") as f:
                while chunk := await video.read(1024 * 1024):
                    size += len(chunk)
                    if size > limit:
                        raise HTTPException(413, f"The video is larger than {settings.max_upload_mb} MB.")
                    f.write(chunk)
            with open(path, "rb") as f:
                if not looks_like_mp4(f.read(16)):
                    raise HTTPException(415, "Only MP4 recordings are supported.")
            try:
                await run_in_threadpool(probe, path, settings.max_video_sec)
            except VideoError as e:
                raise HTTPException(415, str(e)) from None
            await run_in_threadpool(app.state.storage.put_file, path, key)

        db.create_session(
            app.state.pool, sid, name=name.strip() or "Untitled session", procedure_context=procedureContext.strip(),
            designated_objects=designatedObjects[:MAX_CONTEXT], zones=zones_data, video_key=key, owner_id=user["id"],
        )
        return {"sessionId": sid}

    @app.get("/sessions")
    def list_recordings(request: Request, user: dict = Depends(current_user)):
        """The signed-in user's 20 most recent recordings, newest first."""
        api_limiter.check(client_ip(request))
        return {"sessions": [
            {"sessionId": str(s["id"]), "name": s["name"], "state": s["state"],
             "progress": round(float(s["progress"]), 3), "createdAt": s["created_at"].isoformat()}
            for s in db.list_sessions(app.state.pool, user["id"], 20)
        ]}

    @app.get("/sessions/{session_id}")
    def job_status(session_id: str, request: Request, user: dict = Depends(current_user)):
        api_limiter.check(client_ip(request))
        s = session_or_404(session_id, user)
        sid = str(s["id"])
        status = {"sessionId": sid, "name": s["name"], "state": s["state"], "progress": round(float(s["progress"]), 3)}
        if s["state"] == "queued":
            status["queuePosition"] = db.queue_position(app.state.pool, s)
        if s["state"] == "failed":
            status["error"] = s["error"] or "Processing failed."
        if s["state"] == "completed":
            status["result"] = {
                "sessionId": sid,
                "source": "backend",
                "createdAt": s["created_at"].isoformat(),
                "findings": db.list_findings(app.state.pool, sid),
            }
            if s["annotated_key"]:
                # Streamed by this API (never a storage link). A path, not a full URL, so the Host
                # header can't influence it; the website only accepts exactly this path.
                prefix = request.scope.get("root_path", "").rstrip("/")
                status["result"]["annotatedVideoUrl"] = f"{prefix}/sessions/{sid}/annotated.mp4"
        return status

    @app.post("/sessions/{session_id}/cancel", dependencies=[Depends(same_site)])
    def cancel(session_id: str, request: Request, user: dict = Depends(current_user)):
        api_limiter.check(client_ip(request))
        s = session_or_404(session_id, user)
        db.request_cancel(app.state.pool, str(s["id"]))
        return {}

    @app.patch("/sessions/{session_id}/findings/{event_id}", dependencies=[Depends(same_site)])
    def review(session_id: str, event_id: str, body: ReviewUpdate, request: Request,
               user: dict = Depends(current_user)):
        api_limiter.check(client_ip(request))
        if not SAFE_ID.match(event_id):  # same rule as the website (web/lib/validate.ts)
            raise HTTPException(404, "Finding not found.")
        s = session_or_404(session_id, user)
        if not db.set_review_status(app.state.pool, str(s["id"]), event_id, body.reviewStatus):
            raise HTTPException(404, "Finding not found.")
        return {}

    # --- final review report (Gemini) ------------------------------------------

    def report_body(sid: str, saved: dict, findings: list[dict]) -> dict:
        # "stale": reviewer decisions changed since the report was written.
        return {**saved, "sessionId": sid, "stale": saved.get("decisionsHash") != report.decisions_hash(findings)}

    @app.get("/sessions/{session_id}/report")
    def get_report(session_id: str, request: Request, user: dict = Depends(current_user)):
        api_limiter.check(client_ip(request))
        s = session_or_404(session_id, user)
        sid = str(s["id"])
        saved = db.get_report(app.state.pool, sid)
        if saved is None:
            raise HTTPException(404, "No report has been written for this recording yet.")
        return report_body(sid, saved, db.list_findings(app.state.pool, sid))

    @app.post("/sessions/{session_id}/report", dependencies=[Depends(same_site)])
    def write_report(session_id: str, request: Request, user: dict = Depends(current_user)):
        """Ask Gemini for a final report from the findings and reviewer decisions (never the video)."""
        api_limiter.check(client_ip(request))
        s = session_or_404(session_id, user)
        if s["state"] != "completed":
            raise HTTPException(409, "The analysis has to finish before a report can be written.")
        if not settings.gemini_api_key:
            raise HTTPException(503, "Report writing isn't set up on this server.")
        report_limiter.check(str(user["id"]))
        sid = str(s["id"])
        findings = db.list_findings(app.state.pool, sid)
        try:
            written = report.generate(settings, s, findings)
        except report.ReportError as e:
            raise HTTPException(e.status, e.message) from None
        db.save_report(app.state.pool, sid, written)
        return report_body(sid, written, findings)

    @app.delete("/sessions/{session_id}", dependencies=[Depends(same_site)])
    def delete_recording(session_id: str, request: Request, user: dict = Depends(current_user)):
        """Delete the recording, labeled video, tracking data and findings for good."""
        api_limiter.check(client_ip(request))
        s = session_or_404(session_id, user)
        db.request_cancel(app.state.pool, str(s["id"]))  # stop a running job first
        for key in db.delete_session(app.state.pool, str(s["id"])):
            app.state.storage.delete(key)
        log.info("session deleted id=%s", s["id"])
        return {}

    # --- annotated video + tracking data -----------------------------------

    @app.get("/sessions/{session_id}/annotated.mp4", name="annotated_video")
    def annotated_video(session_id: str, request: Request, download: bool = False,
                        user: dict = Depends(current_user)):
        """Stream the labeled video, with HTTP Range so the player can seek; `?download=1` saves it as a file.

        Bytes always come through this API; storage links are never handed out.
        """
        s = session_or_404(session_id, user)
        if not s["annotated_key"]:
            raise HTTPException(404, "The labeled video is not ready.")
        st = app.state.storage
        headers = {"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff"}
        if download:
            # Only safe characters, so the session name can't break the header.
            stem = re.sub(r"[^A-Za-z0-9._-]+", "-", s["name"] or "").strip("-.")[:60] or "recording"
            headers["Content-Disposition"] = f'attachment; filename="rescrub-{stem}-labeled.mp4"'
        if isinstance(st, LocalStorage):
            return FileResponse(st.path(s["annotated_key"]), media_type="video/mp4", headers=headers)
        try:
            status, extra, body = st.stream(s["annotated_key"], request.headers.get("range"))
        except ValueError:
            raise HTTPException(416, "Requested range not satisfiable.") from None
        return StreamingResponse(body, status_code=status, media_type="video/mp4", headers={**headers, **extra})

    @app.get("/sessions/{session_id}/people")
    def people(session_id: str, request: Request, user: dict = Depends(current_user)):
        api_limiter.check(client_ip(request))
        s = session_or_404(session_id, user)
        return {"sessionId": str(s["id"]), "people": db.list_people(app.state.pool, str(s["id"]))}

    @app.get("/sessions/{session_id}/tracks")
    def tracks(
        session_id: str,
        request: Request,
        person: str | None = None,
        start: float | None = Query(None, alias="from"),
        end: float | None = Query(None, alias="to"),
        parts: str | None = Query(None, description="comma separated, e.g. r_wrist,r_index_tip"),
        limit: int = Query(20000, ge=1, le=50000),
        user: dict = Depends(current_user),
    ):
        api_limiter.check(client_ip(request))
        s = session_or_404(session_id, user)
        part_list = [p.strip() for p in parts.split(",") if p.strip()] if parts else None
        rows = db.list_keypoints(app.state.pool, str(s["id"]), person, start, end, part_list, limit)
        return {"sessionId": str(s["id"]), "fps": s["fps"], "keypoints": rows}

    @app.get("/sessions/{session_id}/surfaces")
    def surfaces(session_id: str, request: Request, user: dict = Depends(current_user)):
        api_limiter.check(client_ip(request))
        s = session_or_404(session_id, user)
        return {"sessionId": str(s["id"]), "width": s["width"], "height": s["height"],
                "surfaces": db.list_surfaces(app.state.pool, str(s["id"]))}

    @app.get("/sessions/{session_id}/proximity")
    def proximity(
        session_id: str,
        request: Request,
        candidate_only: bool = False,
        start: float | None = Query(None, alias="from"),
        end: float | None = Query(None, alias="to"),
        limit: int = Query(20000, ge=1, le=50000),
        user: dict = Depends(current_user),
    ):
        api_limiter.check(client_ip(request))
        s = session_or_404(session_id, user)
        rows = db.list_proximity(app.state.pool, str(s["id"]), candidate_only, start, end, limit)
        return {"sessionId": str(s["id"]), "events": rows}

    return app

