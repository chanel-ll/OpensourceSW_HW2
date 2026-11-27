"""Pure rules for paper summaries (no DB, no network)."""


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
    kws = data.get("keywords", [])
    if not isinstance(kws, list):
        raise BadSummary("bad_summary: keywords must be a list")
    return {"one_line": one.strip(), "contributions": [str(c) for c in contrib], "keywords": [str(k) for k in kws][:5]}


def fallback(title, abstract, keywords=()):
    """Rule-based summary when the LLM cannot answer: first sentence of the abstract (or the title)."""
    text = " ".join((abstract or "").split())
    first = text.split(". ")[0].rstrip(".") + "." if text else title
    return {"one_line": first, "contributions": [], "keywords": list(keywords)[:5], "used_fallback": True}


def needs_llm(stored):
    """Only a missing or fallback summary may call the LLM; a stored LLM summary is final."""
    return not stored or bool(stored.get("used_fallback"))
