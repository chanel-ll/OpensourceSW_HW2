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
