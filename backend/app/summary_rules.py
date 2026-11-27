"""Pure rules for paper summaries (no DB, no network)."""
import re

_ABBR = ("e.g.", "i.e.", "et al.", "fig.", "etc.", "vs.", "cf.", "eq.", "no.")


class BadSummary(ValueError):
    pass


def validate(data):
    """LLM output -> normalized summary, or BadSummary('bad_summary: <why>')."""
    if not isinstance(data, dict):
        raise BadSummary("bad_summary: not an object")
    one = data.get("one_line")
    if not isinstance(one, str) or not one.strip():
        raise BadSummary("bad_summary: one_line missing")
    contrib = data.get("contributions", [])
    if not isinstance(contrib, list) or len(contrib) > 3:
        raise BadSummary("bad_summary: contributions must be a list of at most 3")
    if not all(isinstance(c, str) and c.strip() for c in contrib):
        raise BadSummary("bad_summary: contributions must be non-empty strings")
    kws = data.get("keywords", [])
    if not isinstance(kws, list):
        raise BadSummary("bad_summary: keywords must be a list")
    return {"one_line": one.strip(), "contributions": [c.strip() for c in contrib], "keywords": [str(k) for k in kws][:5]}


def fallback(title, abstract, keywords=()):
    """Rule-based summary when the LLM cannot answer: first sentence of the abstract (or the title)."""
    text = " ".join((abstract or "").split())
    first = _first_sentence(text)[:300] if text else (title or "")
    return {"one_line": first, "contributions": [], "keywords": list(keywords)[:5], "used_fallback": True}


def needs_llm(stored):
    """Only a missing or fallback summary may call the LLM; a stored LLM summary is final."""
    return not stored or bool(stored.get("used_fallback")) or not str(stored.get("one_line") or "").strip()


def _first_sentence(text):
    """Up to the first . ! ? followed by a new sentence; abbreviations (e.g., et al.) and decimals do not end it."""
    for m in re.finditer(r"[.!?](?=\s+[A-Z0-9\"'(\[])", text):
        head = text[: m.end()]
        if not head.lower().endswith(_ABBR):
            return head
    return text if text.endswith((".", "!", "?")) else text + "."
