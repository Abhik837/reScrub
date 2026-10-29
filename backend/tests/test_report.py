"""Final review report (rescrub/report.py) and its API endpoints. Gemini is never called: the
HTTP call is replaced by a fake that returns a fixed answer."""

import json

import pytest
from test_api import make_client, sign_in, upload

from rescrub import auth, db, report
from rescrub.settings import Settings


def finding(event_id, t, status="needs_review", level="low"):
    return {
        "eventId": event_id, "timestampSec": t, "title": f"Title {event_id}", "objects": ["Side table"],
        "description": "Hand touches the side table.", "reasonForReview": "Nonsterile contact.",
        "evidence": [{"label": "Side table", "designation": "nonsterile", "timestampSec": t, "observation": "o"}],
        "uncertainty": {"level": level, "notes": "n"}, "reviewStatus": status,
    }


FINDINGS = [finding("evt-1", 12.0, "confirmed"), finding("evt-2", 30.0), finding("evt-3", 45.0, "dismissed", "high")]


def draft(**overrides):
    body = {
        "overview": "Three moments were flagged.",
        "keyMoments": [
            {"eventId": "evt-2", "summary": "Unreviewed contact.", "teachingPoint": "Re-glove."},
            {"eventId": "evt-1", "summary": "**Confirmed** contact.", "teachingPoint": "Keep hands up."},
            {"eventId": "evt-3", "summary": "Dismissed one.", "teachingPoint": "x"},       # dismissed: dropped
            {"eventId": "evt-999", "summary": "Invented.", "teachingPoint": "x"},          # unknown: dropped
            {"eventId": "evt-1", "summary": "Duplicate.", "teachingPoint": "x"},           # duplicate: dropped
        ],
        "coachingPoints": ["- Pause after contact.", "", "Watch the mask zone."],
        "limitations": "One camera.",
    }
    body.update(overrides)
    return json.dumps(body)


# --- validation (no database) -----------------------------------------------------------

def test_parse_draft_keeps_only_real_undismissed_findings():
    out = report.parse_draft(draft(), FINDINGS)
    assert [m["eventId"] for m in out["keyMoments"]] == ["evt-1", "evt-2"]  # confirmed first, then by time
    first = out["keyMoments"][0]
    # Facts come from the findings, words from the model (markup stripped).
    assert first["timestampSec"] == 12.0 and first["title"] == "Title evt-1" and first["reviewStatus"] == "confirmed"
    assert first["summary"] == "Confirmed contact."
    assert out["coachingPoints"] == ["Pause after contact.", "Watch the mask zone."]


def test_parse_draft_rejects_unusable_answers():
    for text in ("not json", "[]", draft(overview=""), draft(overview=123)):
        with pytest.raises(report.ReportError):
            report.parse_draft(text, FINDINGS)


def test_parse_draft_accepts_fenced_json():
    out = report.parse_draft("```json\n" + draft() + "\n```", FINDINGS)
    assert out["overview"] == "Three moments were flagged."


class FakeResponse:
    def __init__(self, body):
        self.body = json.dumps(body).encode()

    def read(self, *a):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def fake_gemini(monkeypatch, body=None, status=None):
    def urlopen(req, timeout):
        if status:
            raise report.urllib.error.HTTPError(req.full_url, status, "err", {}, None)
        return FakeResponse(body)
    monkeypatch.setattr(report.urllib.request, "urlopen", urlopen)


def test_call_gemini_reads_text_and_skips_thoughts(monkeypatch):
    fake_gemini(monkeypatch, {"candidates": [{"finishReason": "STOP", "content": {"parts": [
        {"text": "thinking...", "thought": True}, {"text": "{\"a\": 1}"}]}}]})
    assert report.call_gemini("k", "m", "sys", "user", 5) == "{\"a\": 1}"


def test_call_gemini_reports_cut_off_answers_and_overload(monkeypatch):
    fake_gemini(monkeypatch, {"candidates": [{"finishReason": "MAX_TOKENS", "content": {"parts": [{"text": "{"}]}}]})
    with pytest.raises(report.ReportError, match="too long"):
        report.call_gemini("k", "m", "sys", "user", 5)
    for code in (429, 503):
        fake_gemini(monkeypatch, status=code)
        with pytest.raises(report.ReportError, match="busy") as e:
            report.call_gemini("k", "m", "sys", "user", 5)
        assert e.value.status == 503
    fake_gemini(monkeypatch, status=400)
    with pytest.raises(report.ReportError, match="rejected"):
        report.call_gemini("k", "m", "sys", "user", 5)


def test_parse_draft_caps_lengths_and_strips_control_characters():
    out = report.parse_draft(draft(overview="a‮" + "x" * 5000), FINDINGS)
    assert "‮" not in out["overview"] and len(out["overview"]) <= report.TEXT["overview"]


def test_humanize_fixes_safe_ai_writing_tells():
    assert report.humanize("It touched the cart — then the tray.") == "It touched the cart, then the tray."
    assert report.humanize("Moreover, the hand moved. Notably, it stayed there.") == "The hand moved. It stayed there."
    assert report.humanize("It's worth noting that the view was blocked.") == "The view was blocked."
    assert report.humanize("Utilize a new glove in order to stay sterile!") == "Use a new glove to stay sterile."
    assert report.humanize("A crucial step and a robust habit.") == "A key step and a strong habit."
    # Hedges stay, and words that only contain a listed word ("overall" mid-sentence, "robustly") stay.
    kept = "The glove may have touched the drape; the overall view was robustly lit."
    assert report.humanize(kept) == kept


def test_parse_draft_applies_wording_cleanup_to_model_text():
    out = report.parse_draft(draft(overview="Overall, Person 2 utilized the tray — twice!",
                                   limitations="Additionally, one camera."), FINDINGS)
    assert out["overview"] == "Person 2 used the tray, twice."
    assert out["limitations"] == "One camera."


def test_input_sent_to_gemini_has_no_video_or_identifying_fields():
    session = {"id": "s", "name": "Dr Smith station 3", "procedure_context": "Mock lap chole", "duration_sec": 95,
               "video_key": "uploads/x.mp4", "owner_id": "u"}
    payload = report.build_input(session, FINDINGS)
    text = json.dumps(payload)
    assert "Dr Smith" not in text and "uploads/" not in text and "owner" not in text
    assert payload["recordingLength"] == "01:35" and payload["counts"]["confirmed"] == 1
    assert payload["findings"][0]["time"] == "00:12"


def test_decisions_hash_changes_with_reviews():
    changed = [dict(FINDINGS[0], reviewStatus="dismissed"), *FINDINGS[1:]]
    assert report.decisions_hash(FINDINGS) != report.decisions_hash(changed)
    assert report.decisions_hash(FINDINGS) == report.decisions_hash(list(reversed(FINDINGS)))


def test_generate_needs_key_and_safe_model_name(monkeypatch):
    with pytest.raises(report.ReportError) as e:
        report.generate(Settings(gemini_api_key=""), {}, FINDINGS)
    assert e.value.status == 503
    with pytest.raises(report.ReportError):
        report.generate(Settings(gemini_api_key="k", gemini_model="../../evil"), {}, FINDINGS)


def test_generate_builds_report_from_fake_gemini(monkeypatch):
    seen = {}

    def fake_call(api_key, model, system, user_text, timeout):
        seen.update(api_key=api_key, model=model, user_text=user_text)
        return draft()

    monkeypatch.setattr(report, "call_gemini", fake_call)
    out = report.generate(Settings(gemini_api_key="test-key", gemini_model="gemini-test"), {"id": "s"}, FINDINGS)
    assert seen["api_key"] == "test-key" and seen["model"] == "gemini-test"
    assert out["stats"] == {"findings": 3, "confirmed": 1, "needsReview": 1, "dismissed": 1, "highUncertainty": 1}
    assert out["decisionsHash"] == report.decisions_hash(FINDINGS) and out["model"] == "gemini-test"


# --- API (needs TEST_DATABASE_URL) ------------------------------------------------------

def completed_session(client, pool, tiny_mp4):
    sid = upload(client, tiny_mp4).json()["sessionId"]
    db.claim_next_session(pool)
    db.complete_session(pool, sid, None)
    for f in FINDINGS:
        db.upsert_finding(pool, sid, {k: v for k, v in f.items() if k != "reviewStatus"})
    db.set_review_status(pool, sid, "evt-1", "confirmed")
    db.set_review_status(pool, sid, "evt-3", "dismissed")
    return sid


@pytest.fixture
def report_client(pool, tmp_path, monkeypatch):
    monkeypatch.setattr(report, "call_gemini", lambda *a, **k: draft())
    auth.create_user(pool, "trainee@example.com", "correct horse battery")
    with make_client(pool, tmp_path, gemini_api_key="test-key") as c:
        sign_in(c)
        yield c


def test_report_endpoints(report_client, pool, tiny_mp4):
    c = report_client
    sid = completed_session(c, pool, tiny_mp4)
    assert c.get(f"/sessions/{sid}/report").status_code == 404

    r = c.post(f"/sessions/{sid}/report")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["sessionId"] == sid and body["stale"] is False
    assert [m["eventId"] for m in body["keyMoments"]] == ["evt-1", "evt-2"]

    assert c.get(f"/sessions/{sid}/report").json()["stale"] is False
    c.patch(f"/sessions/{sid}/findings/evt-2", json={"reviewStatus": "confirmed"})
    assert c.get(f"/sessions/{sid}/report").json()["stale"] is True


def test_report_requires_finished_analysis_and_ownership(report_client, pool, tiny_mp4, tmp_path):
    c = report_client
    queued = upload(c, tiny_mp4).json()["sessionId"]
    assert c.post(f"/sessions/{queued}/report").status_code == 409

    sid = completed_session(c, pool, tiny_mp4)
    auth.create_user(pool, "other@example.com", "another long password")
    with make_client(pool, tmp_path / "other", gemini_api_key="test-key") as other:
        sign_in(other, "other@example.com", "another long password")
        assert other.post(f"/sessions/{sid}/report").status_code == 404
        assert other.get(f"/sessions/{sid}/report").status_code == 404


def test_report_off_without_key(pool, tmp_path, tiny_mp4):
    auth.create_user(pool, "trainee@example.com", "correct horse battery")
    with make_client(pool, tmp_path) as c:
        sign_in(c)
        sid = completed_session(c, pool, tiny_mp4)
        r = c.post(f"/sessions/{sid}/report")
        assert r.status_code == 503 and "set up" in r.json()["error"]
