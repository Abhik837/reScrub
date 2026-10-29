"""API contract (docs/API.md) against a real Postgres. Needs TEST_DATABASE_URL."""

import pytest
from fastapi.testclient import TestClient

from rescrub import auth, db
from rescrub.api import create_app
from rescrub.settings import Settings
from rescrub.storage import LocalStorage

FORM = {"name": "Mock lap chole", "procedureContext": "practice", "designatedObjects": "drape", "acknowledged": "true"}


SITE = "https://testserver"


def make_client(pool, tmp_path, **overrides):
    # No DNS in tests (example.com also publishes a "null MX"); tests/test_emails.py covers the lookup.
    overrides.setdefault("check_email_dns", False)
    settings = Settings(cors_origins=SITE, uploads_per_hour_per_client=100, **overrides)
    app = create_app(settings, pool=pool, storage=LocalStorage(tmp_path / "store"))
    # https base URL so the Secure cookie is sent back; Origin as a browser on our site would send it.
    return TestClient(app, base_url=SITE, headers={"Origin": SITE})


def sign_in(c, email="trainee@example.com", password="correct horse battery"):
    r = c.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r


@pytest.fixture
def client(pool, tmp_path):
    auth.create_user(pool, "trainee@example.com", "correct horse battery")
    with make_client(pool, tmp_path) as c:
        sign_in(c)
        yield c


def upload(client, path, **extra):
    with open(path, "rb") as f:
        return client.post("/sessions", data={**FORM, **extra}, files={"video": ("clip.mp4", f, "video/mp4")})


def test_upload_then_status_queued(client, tiny_mp4):
    r = upload(client, tiny_mp4)
    assert r.status_code == 200, r.text
    sid = r.json()["sessionId"]
    s = client.get(f"/sessions/{sid}").json()
    assert s["sessionId"] == sid and s["state"] == "queued" and "result" not in s


def test_rejects_non_mp4_and_missing_ack(client, tmp_path, tiny_mp4):
    fake = tmp_path / "fake.mp4"
    fake.write_bytes(b"not a video at all" * 10)
    r = upload(client, fake)
    assert r.status_code == 415 and "MP4" in r.json()["error"]
    r = upload(client, tiny_mp4, acknowledged="false")
    assert r.status_code == 400 and r.json()["error"]


def test_bad_zones_rejected(client, tiny_mp4):
    r = upload(client, tiny_mp4, zones='[{"label":"x","designation":"clean","polygon":[[0,0],[1,0],[1,1]]}]')
    assert r.status_code == 400 and "zones" in r.json()["error"]


def test_unknown_session_404s(client):
    assert client.get("/sessions/not-a-uuid").status_code == 404
    r = client.get("/sessions/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 404 and r.json() == {"error": "Session not found."}


def test_cancel_queued_session(client, tiny_mp4):
    sid = upload(client, tiny_mp4).json()["sessionId"]
    assert client.post(f"/sessions/{sid}/cancel").json() == {}
    assert client.get(f"/sessions/{sid}").json()["state"] == "canceled"


def test_completed_result_and_review(client, pool, tiny_mp4, tmp_path):
    sid = upload(client, tiny_mp4).json()["sessionId"]
    claimed = db.claim_next_session(pool)
    assert str(claimed["id"]) == sid
    store = client.app.state.storage
    store.put_file(tiny_mp4, "annotated/x.mp4")
    db.complete_session(pool, sid, "annotated/x.mp4")
    db.upsert_finding(pool, sid, {
        "eventId": "evt-1", "timestampSec": 1.5, "title": "t", "objects": [], "description": "d",
        "reasonForReview": "r", "evidence": [], "uncertainty": {"level": "low", "notes": ""},
    })

    s = client.get(f"/sessions/{sid}").json()
    assert s["state"] == "completed"
    res = s["result"]
    assert res["source"] == "backend" and res["sessionId"] == sid
    assert res["findings"][0]["reviewStatus"] == "needs_review" and res["findings"][0]["sessionId"] == sid
    assert res["annotatedVideoUrl"].endswith(f"/sessions/{sid}/annotated.mp4")
    video = client.get(res["annotatedVideoUrl"])
    assert video.status_code == 200 and video.headers["content-type"] == "video/mp4"
    part = client.get(res["annotatedVideoUrl"], headers={"Range": "bytes=0-99"})
    assert part.status_code == 206 and len(part.content) == 100  # the player can seek
    assert "content-disposition" not in video.headers  # plays in the page
    saved = client.get(res["annotatedVideoUrl"] + "?download=1")
    assert saved.status_code == 200 and saved.content == video.content
    assert saved.headers["content-disposition"] == 'attachment; filename="rescrub-Mock-lap-chole-labeled.mp4"'

    assert client.patch(f"/sessions/{sid}/findings/evt-1", json={"reviewStatus": "confirmed"}).json() == {}
    assert client.get(f"/sessions/{sid}").json()["result"]["findings"][0]["reviewStatus"] == "confirmed"
    assert client.patch(f"/sessions/{sid}/findings/nope", json={"reviewStatus": "confirmed"}).status_code == 404
    assert client.patch(f"/sessions/{sid}/findings/evt-1", json={"reviewStatus": "maybe"}).status_code == 422


def test_cors_allows_website(client):
    headers = {"Origin": SITE, "Access-Control-Request-Method": "POST"}
    r = client.options("/sessions", headers=headers)
    assert r.headers.get("access-control-allow-origin") == SITE


def test_text_limits_match_website(client, tiny_mp4):
    r = upload(client, tiny_mp4, name="x" * 121)
    assert r.status_code == 400 and "120" in r.json()["error"]
    assert upload(client, tiny_mp4, procedureContext="", designatedObjects="").status_code == 200


def test_no_labeled_video_link_until_ready(client, pool, tiny_mp4):
    sid = upload(client, tiny_mp4).json()["sessionId"]
    db.claim_next_session(pool)
    db.complete_session(pool, sid, None)
    res = client.get(f"/sessions/{sid}").json()["result"]
    assert "annotatedVideoUrl" not in res and res["findings"] == []


def test_api_docs_hidden_by_default(client):
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404


def test_unsafe_finding_id_rejected(client, tiny_mp4):
    sid = upload(client, tiny_mp4).json()["sessionId"]
    r = client.patch(f"/sessions/{sid}/findings/evt%201'--", json={"reviewStatus": "confirmed"})
    assert r.status_code == 404


# --- sign-in and access control -------------------------------------------------

def test_login_cookie_is_locked_down(pool, tmp_path):
    auth.create_user(pool, "a@example.com", "a-long-password-1")
    with make_client(pool, tmp_path) as c:
        r = sign_in(c, "A@Example.com ", "a-long-password-1")  # email is case/space insensitive
        cookie = r.headers["set-cookie"]
        assert cookie.startswith("__Host-rescrub_session=")
        for flag in ("HttpOnly", "Secure", "SameSite=lax", "Path=/"):
            assert flag.lower() in cookie.lower()
        assert "domain" not in cookie.lower()
        assert c.get("/auth/me").json() == {"email": "a@example.com", "role": "member"}
        token = c.cookies.get("__Host-rescrub_session")
        stored = pool.connection().__enter__().execute("SELECT token_hash FROM auth_sessions").fetchall()
        assert all(bytes(row["token_hash"]) != token.encode() for row in stored)  # only a hash is stored


def test_wrong_password_and_unknown_email_look_the_same(pool, tmp_path):
    auth.create_user(pool, "b@example.com", "b-long-password-1")
    with make_client(pool, tmp_path) as c:
        bad_pw = c.post("/auth/login", json={"email": "b@example.com", "password": "nope-nope-nope"})
        no_user = c.post("/auth/login", json={"email": "nobody@example.com", "password": "nope-nope-nope"})
        assert bad_pw.status_code == no_user.status_code == 401
        assert bad_pw.json() == no_user.json() == {"error": "Email or password is incorrect."}
        assert "set-cookie" not in bad_pw.headers


def test_everything_requires_sign_in(pool, tmp_path, tiny_mp4):
    with make_client(pool, tmp_path) as c:
        sid = "00000000-0000-0000-0000-000000000000"
        assert c.get("/auth/me").status_code == 401
        assert upload(c, tiny_mp4).status_code == 401
        for path in (f"/sessions/{sid}", f"/sessions/{sid}/annotated.mp4", f"/sessions/{sid}/tracks"):
            r = c.get(path)
            assert r.status_code == 401 and r.json() == {"error": "Please sign in."}


def test_users_only_see_their_own_recordings(pool, tmp_path, tiny_mp4):
    auth.create_user(pool, "owner@example.com", "first-account-pw-1")
    auth.create_user(pool, "other@example.com", "second-account-pw-2")
    with make_client(pool, tmp_path) as owner, make_client(pool, tmp_path) as other:
        sign_in(owner, "owner@example.com", "first-account-pw-1")
        sign_in(other, "other@example.com", "second-account-pw-2")
        sid = upload(owner, tiny_mp4).json()["sessionId"]
        assert owner.get(f"/sessions/{sid}").status_code == 200
        for r in (other.get(f"/sessions/{sid}"), other.post(f"/sessions/{sid}/cancel"),
                  other.get(f"/sessions/{sid}/people"),
                  other.patch(f"/sessions/{sid}/findings/evt-1", json={"reviewStatus": "dismissed"}),
                  other.delete(f"/sessions/{sid}")):
            assert r.status_code == 404  # indistinguishable from a session that doesn't exist
        assert owner.get(f"/sessions/{sid}").json()["state"] == "queued"  # other's cancel did nothing


def test_requests_from_other_sites_are_refused(client, tiny_mp4):
    for origin in ("https://evil.example", None):
        headers = {"Origin": origin} if origin else {}
        if origin is None:
            client.headers.pop("Origin")
        with open(tiny_mp4, "rb") as f:
            r = client.post("/sessions", data=FORM, files={"video": ("c.mp4", f, "video/mp4")}, headers=headers)
        assert r.status_code == 403, origin
        client.headers["Origin"] = SITE
    assert client.post("/auth/logout", headers={"Origin": "https://evil.example"}).status_code == 403


def test_logout_ends_the_session(client):
    token = client.cookies.get("__Host-rescrub_session")
    assert client.post("/auth/logout").status_code == 200
    client.cookies.set("__Host-rescrub_session", token, domain="testserver")  # replay the old cookie
    assert client.get("/auth/me").status_code == 401


def test_disabled_and_reset_accounts_are_signed_out(pool, tmp_path):
    auth.create_user(pool, "c@example.com", "c-long-password-1")
    with make_client(pool, tmp_path) as c:
        sign_in(c, "c@example.com", "c-long-password-1")
        auth.set_password(pool, "c@example.com", "c-new-password-22")
        assert c.get("/auth/me").status_code == 401
        sign_in(c, "c@example.com", "c-new-password-22")
        auth.set_disabled(pool, "c@example.com", True)
        assert c.get("/auth/me").status_code == 401
        r = c.post("/auth/login", json={"email": "c@example.com", "password": "c-new-password-22"})
        assert r.status_code == 401


def test_login_attempts_are_rate_limited(pool, tmp_path):
    with make_client(pool, tmp_path, logins_per_15min_per_email=3) as c:
        codes = [c.post("/auth/login", json={"email": "x@example.com", "password": "guess-guess-1"}).status_code
                 for _ in range(5)]
        assert codes == [401, 401, 401, 429, 429]


def test_short_passwords_rejected(pool):
    with pytest.raises(ValueError):
        auth.create_user(pool, "d@example.com", "short")


def test_owner_can_delete_a_recording_completely(client, pool, tiny_mp4):
    sid = upload(client, tiny_mp4).json()["sessionId"]
    db.claim_next_session(pool)
    store = client.app.state.storage
    store.put_file(tiny_mp4, "annotated/del.mp4")
    db.complete_session(pool, sid, "annotated/del.mp4")
    video_key = db.get_session(pool, sid)["video_key"]
    assert client.delete(f"/sessions/{sid}").json() == {}
    assert client.get(f"/sessions/{sid}").status_code == 404
    assert db.get_session(pool, sid) is None
    assert not store.path("annotated/del.mp4").exists() and not store.path(video_key).exists()
    assert client.delete(f"/sessions/{sid}", headers={"Origin": "https://evil.example"}).status_code == 403


def test_deleting_during_analysis_stops_the_job_and_removes_late_rows(client, pool, tiny_mp4):
    sid = upload(client, tiny_mp4).json()["sessionId"]
    db.claim_next_session(pool)  # the worker is analyzing it
    assert client.delete(f"/sessions/{sid}").json() == {}
    assert db.is_cancel_requested(pool, sid)  # the job stops at its next check
    with pool.connection() as c:  # a batch the worker flushed after the delete
        c.execute("""INSERT INTO detections (ts, session_id, video_sec, frame, person_label, track_id,
                                             x1, y1, x2, y2, conf)
                     VALUES (now(), %s, 1, 30, 'Person 1', 1, 0, 0, 1, 1, 0.9)""", (sid,))
    assert db.purge_if_deleted(pool, sid)
    with pool.connection() as c:
        assert c.execute("SELECT count(*) AS n FROM detections WHERE session_id = %s", (sid,)).fetchone()["n"] == 0


# --- self-service sign-up ---------------------------------------------------------

def test_register_creates_a_member_and_signs_in(pool, tmp_path):
    with make_client(pool, tmp_path) as c:
        assert c.get("/auth/options").json() == {"registration": True, "emailDomains": []}
        r = c.post("/auth/register", json={"email": " New@Example.com", "password": "a-fresh-password-1"})
        assert r.status_code == 201 and r.json() == {"email": "new@example.com", "role": "member"}
        assert r.headers["set-cookie"].startswith("__Host-rescrub_session=")
        assert c.get("/auth/me").json()["email"] == "new@example.com"
        again = c.post("/auth/register", json={"email": "new@example.com", "password": "another-password-2"})
        assert again.status_code == 409 and "set-cookie" not in again.headers
    with make_client(pool, tmp_path) as c:  # the first password still works; the second didn't overwrite it
        sign_in(c, "new@example.com", "a-fresh-password-1")


def test_register_rejects_weak_input(pool, tmp_path):
    with make_client(pool, tmp_path) as c:
        for email, password in (("not-an-email", "a-fresh-password-1"), ("w@example.com", "short"),
                                ("w@example.com", "aaaaaaaaaaaaaaaa"), ("jordan@example.com", "Jordan2024!!")):
            r = c.post("/auth/register", json={"email": email, "password": password})
            assert r.status_code == 400 and r.json()["error"], (email, password)
        r = c.post("/auth/register", json={"email": "ab@gmail.com", "password": "a-fresh-password-1"})
        assert r.status_code == 400 and "Gmail" in r.json()["error"]
        assert c.get("/auth/me").status_code == 401


def test_register_can_be_closed_or_limited(pool, tmp_path):
    body = {"email": "x@example.com", "password": "a-fresh-password-1"}
    with make_client(pool, tmp_path, allow_registration=False) as c:
        assert c.get("/auth/options").json()["registration"] is False
        assert c.post("/auth/register", json=body).status_code == 403
    with make_client(pool, tmp_path, registration_email_domains="School.edu") as c:
        assert c.post("/auth/register", json=body).status_code == 403
        assert c.post("/auth/register", json={**body, "email": "x@school.edu"}).status_code == 201
    with make_client(pool, tmp_path, registrations_per_hour_per_ip=2) as c:
        codes = [c.post("/auth/register", json={**body, "email": f"r{i}@example.com"}).status_code for i in range(3)]
        assert codes == [201, 201, 429]
    with make_client(pool, tmp_path) as c:
        assert c.post("/auth/register", json=body, headers={"Origin": "https://evil.example"}).status_code == 403


def test_uploads_are_checked_before_the_body_is_read(pool, tmp_path, tiny_mp4):
    with make_client(pool, tmp_path) as c:  # not signed in
        assert upload(c, tiny_mp4).status_code == 401
    auth.create_user(pool, "u@example.com", "an-uploader-password")
    with make_client(pool, tmp_path, uploads_per_day_per_user=2) as c:
        sign_in(c, "u@example.com", "an-uploader-password")
        with open(tiny_mp4, "rb") as f:  # no Content-Length (chunked)
            r = c.post("/sessions", content=iter([f.read()]),
                       headers={"Content-Type": "multipart/form-data; boundary=x"})
        assert r.status_code == 411
        assert [upload(c, tiny_mp4).status_code for _ in range(3)] == [200, 200, 429]


def test_probe_rejects_videos_that_would_occupy_the_worker(tmp_path, tiny_mp4):
    import subprocess

    from rescrub.pipeline.video_io import VideoError, probe

    assert probe(tiny_mp4).width == 320
    for name, src in (("wide", "testsrc=duration=1:size=4112x16:rate=5"),
                      ("fast", "testsrc=duration=1:size=64x64:rate=500")):
        path = tmp_path / f"{name}.mp4"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", src, "-c:v", "libx264",
                        "-pix_fmt", "yuv420p", str(path)], check=True)
        with pytest.raises(VideoError):
            probe(path)


def test_recordings_list_and_queue_position(pool, tmp_path, tiny_mp4):
    auth.create_user(pool, "first@example.com", "first-account-pw-1")
    auth.create_user(pool, "other@example.com", "second-account-pw-2")
    with make_client(pool, tmp_path) as me, make_client(pool, tmp_path) as other:
        sign_in(me, "first@example.com", "first-account-pw-1")
        sign_in(other, "other@example.com", "second-account-pw-2")
        theirs = upload(other, tiny_mp4, name="Theirs").json()["sessionId"]
        first = upload(me, tiny_mp4, name="First").json()["sessionId"]
        second = upload(me, tiny_mp4, name="Second").json()["sessionId"]
        listed = me.get("/sessions").json()["sessions"]
        assert [s["sessionId"] for s in listed] == [second, first]  # newest first, only mine
        assert listed[0]["name"] == "Second" and listed[0]["state"] == "queued" and listed[0]["createdAt"]
        status = me.get(f"/sessions/{second}").json()
        assert status["name"] == "Second" and status["queuePosition"] == 2  # theirs and my first are ahead
        assert other.get(f"/sessions/{theirs}").json()["queuePosition"] == 0
        db.claim_next_session(pool)  # the worker takes "Theirs"
        assert me.get(f"/sessions/{first}").json()["queuePosition"] == 1
        assert "queuePosition" not in other.get(f"/sessions/{theirs}").json()  # analyzing now
    with make_client(pool, tmp_path) as anon:
        assert anon.get("/sessions").status_code == 401
