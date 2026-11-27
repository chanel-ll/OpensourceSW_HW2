"""Deployment contract: /health reports status, db, llm, version and counters; the key comes from FACTCHAT_API_KEY
and never appears in a response; the summarize API keeps working when the LLM fails."""
import httpx
from fastapi.testclient import TestClient

from app import llm, main, settings
from app.models import Paper, Session

api = TestClient(main.app)   # no `with`: startup jobs (migration, weekly update) do not run


def test_factchat_key_takes_precedence():
    assert settings.LLM_API_KEY == "test-secret-key"


def test_health_reports_version_db_llm_and_counters():
    r = api.get("/health")
    assert r.status_code == 200
    h = r.json()
    assert h["status"] == "ok" and h["db"] == "ok" and h["version"] == "sha-test"
    assert h["llm"]["enabled"] is True and set(h["llm"]["stats"]) == {"calls", "failures", "discarded", "fallbacks"}
    assert "test-secret-key" not in r.text


def test_summarize_api_falls_back_when_llm_is_down(monkeypatch):
    def down(url, **kw):
        raise httpx.ConnectError("gateway down")
    monkeypatch.setattr(llm.client, "post", down)
    with Session() as db:
        p = Paper(norm_title="health test paper", title="Health Test Paper", abstract="First sentence here. Second.",
                  authors=[], links={}, keywords=["health"])
        db.add(p)
        db.commit()
        pid = p.id
    r = api.post(f"/api/papers/{pid}/summarize")
    assert r.status_code == 200
    s = r.json()["summary"]
    assert s["used_fallback"] is True and s["one_line"] == "First sentence here." and s["model"] == "fallback"
