"""Rules 2-4: retry once on non-JSON, fall back safely, never re-call for a stored LLM summary.
No real network: every test injects a fake `post`."""
import json

import httpx

from app.llm import Client
from app.summary_rules import needs_llm

TITLE = "Depth completion from sparse ToF"
ABSTRACT = "We densify sparse depth from time-of-flight sensors. A second sentence follows."
GOOD = {"one_line": "희소 ToF 깊이를 조밀하게 복원한다.", "contributions": ["경량 네트워크"], "keywords": ["depth completion"]}


def reply(content, status=200):
    return httpx.Response(status, json={"choices": [{"message": {"content": content}}]})


class FakePost:
    """Returns the queued replies in order (an Exception instance is raised instead) and records each call."""
    def __init__(self, *replies):
        self.replies, self.calls = list(replies), []

    def __call__(self, url, **kw):
        self.calls.append(kw["json"])
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def client(post, key="test-key"):
    return Client(base_url="http://llm.invalid", api_key=key, model="fake-model", post=post, sleep=lambda s: None)


# ---- rule 2: non-JSON -> exactly one retry ----
def test_valid_json_needs_one_call():
    post = FakePost(reply(json.dumps(GOOD)))
    s = client(post).summarize(TITLE, ABSTRACT, ["depth"])
    assert len(post.calls) == 1 and s["used_fallback"] is False and s["one_line"] == GOOD["one_line"]


def test_non_json_is_retried_once_then_succeeds():
    post = FakePost(reply("Sure! Here is the summary."), reply(json.dumps(GOOD)))
    s = client(post).summarize(TITLE, ABSTRACT, ["depth"])
    assert len(post.calls) == 2 and s["used_fallback"] is False


def test_non_json_twice_stops_after_exactly_two_calls():
    post = FakePost(reply("no json"), reply("still no json"), reply(json.dumps(GOOD)))
    c = client(post)
    s = c.summarize(TITLE, ABSTRACT, ["depth"])
    assert len(post.calls) == 2 and s["used_fallback"] is True
    assert c.stats["failures"] == 2 and c.stats["fallbacks"] == 1


# ---- rule 3: every failure ends in a fallback summary, never an exception ----
def test_no_key_falls_back_without_calling():
    post = FakePost()
    c = client(post, key="")
    s = c.summarize(TITLE, ABSTRACT, ["depth completion", "ToF"])
    assert post.calls == []
    assert s == {"one_line": "We densify sparse depth from time-of-flight sensors.", "contributions": [],
                 "keywords": ["depth completion", "ToF"], "used_fallback": True, "reason": s["reason"]}
    assert c.stats["fallbacks"] == 1


def test_timeout_falls_back_without_a_second_wait():
    # review C6: a timeout already cost up to 60 s under the summary lock; retrying doubled it
    post = FakePost(httpx.ReadTimeout("slow"), reply(json.dumps(GOOD)))
    s = client(post).summarize(TITLE, ABSTRACT, [])
    assert len(post.calls) == 1 and s["used_fallback"] is True


def test_credit_exhausted_falls_back_and_disables_further_calls():
    post = FakePost(httpx.Response(402, text="insufficient credit"))
    c = client(post)
    assert c.summarize(TITLE, ABSTRACT, [])["used_fallback"] is True
    assert c.summarize(TITLE, ABSTRACT, [])["used_fallback"] is True
    assert len(post.calls) == 1 and c.available() is False


def test_bad_summary_is_discarded_and_counted():
    post = FakePost(reply(json.dumps({"contributions": []})), reply(json.dumps({"one_line": ""})))
    c = client(post)
    s = c.summarize(TITLE, ABSTRACT, [])
    assert s["used_fallback"] is True and c.stats["discarded"] == 2


def test_fallback_without_abstract_uses_title():
    s = client(FakePost(), key="").summarize(TITLE, "", [])
    assert s["one_line"] == TITLE


# ---- rule 4: a stored LLM summary is final, a fallback can be upgraded ----
def test_needs_llm():
    assert needs_llm(None) is True
    assert needs_llm({**GOOD, "used_fallback": True}) is True
    assert needs_llm({**GOOD, "used_fallback": False}) is False
    assert needs_llm(GOOD) is False          # summaries stored before HW6 had no flag: they came from the LLM


# ---- learned from the real ChatKHU run (gpt-5.4-nano, 2026-11-27) ----
# The real reply was pretty-printed over many lines; gateway models also often wrap JSON in ```json fences.
def test_real_style_multiline_and_fenced_json_is_accepted():
    pretty = json.dumps(GOOD, ensure_ascii=False, indent=2)
    for content in (pretty, f"```json\n{pretty}\n```"):
        post = FakePost(reply(content))
        s = client(post).summarize(TITLE, ABSTRACT, [])
        assert len(post.calls) == 1 and s["used_fallback"] is False and s["one_line"] == GOOD["one_line"]


# ---- review fixes (correctness reviewer) ----
def test_malformed_200_body_is_retried_not_a_500():
    # C1: gateway answered 200 with an error object / HTML instead of choices[]
    for bad in (httpx.Response(200, json={"error": {"message": "overloaded"}}), httpx.Response(200, text="<html>busy</html>")):
        post = FakePost(bad, reply(json.dumps(GOOD)))
        s = client(post).summarize(TITLE, ABSTRACT, [])
        assert len(post.calls) == 2 and s["used_fallback"] is False


def test_empty_tab_name_reply_does_not_raise():
    # C2: "" / null content crashed source collection
    for content in ("", "   ", None):
        assert client(FakePost(reply(content))).tab_name("p", "i", [], []) == ""


def test_rate_limit_mentioning_quota_is_backed_off_not_treated_as_no_credit():
    # C3: "token quota exceeded" on a 429 disabled the LLM until restart
    post = FakePost(httpx.Response(429, text="Rate limit: per-minute token quota exceeded"), reply(json.dumps(GOOD)))
    c = client(post)
    s = c.summarize(TITLE, ABSTRACT, [])
    assert s["used_fallback"] is False and c.available() is True and len(post.calls) == 2


def test_400_saying_insufficient_is_not_credit_exhaustion():
    post = FakePost(httpx.Response(400, text="max_tokens is insufficient"))
    c = client(post)
    assert c.summarize(TITLE, ABSTRACT, [])["used_fallback"] is True and c.available() is True
