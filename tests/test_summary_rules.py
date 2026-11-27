"""Rule 1: an LLM summary that breaks the contract is discarded with reason bad_summary."""
import pytest

from app.summary_rules import BadSummary, validate

GOOD = {"one_line": "희소 깊이를 조밀하게 만든다.", "contributions": ["a", "b"], "keywords": ["depth", "ToF"]}


def test_valid_summary_is_kept_and_trimmed():
    s = validate({**GOOD, "one_line": "  요약  ", "keywords": ["k1", "k2", "k3", "k4", "k5", "k6"]})
    assert s == {"one_line": "요약", "contributions": ["a", "b"], "keywords": ["k1", "k2", "k3", "k4", "k5"]}


@pytest.mark.parametrize("bad", [
    {"contributions": [], "keywords": []},                       # one_line missing
    {**GOOD, "one_line": ""},                                   # empty
    {**GOOD, "one_line": 42},                                   # not a string
    {**GOOD, "contributions": ["1", "2", "3", "4"]},            # more than 3 contributions
    {**GOOD, "contributions": "just a string"},                 # wrong type
    ["not", "a", "dict"],
    {**GOOD, "contributions": [None]},                         # review C4: non-string item
    {**GOOD, "contributions": ["ok", ""]},                     # review C4: empty item
])
def test_broken_summary_is_rejected_with_reason(bad):
    with pytest.raises(BadSummary) as e:
        validate(bad)
    assert str(e.value).startswith("bad_summary")


# ---- review fixes (correctness reviewer C5, C7) ----
from app.summary_rules import fallback, needs_llm  # noqa: E402


@pytest.mark.parametrize("abstract, first", [
    ("We use priors, e.g. depth and normals. Then more.", "We use priors, e.g. depth and normals."),
    ("Prior work (Smith et al. 2020) fails. We fix it.", "Prior work (Smith et al. 2020) fails."),
    ("Is depth enough? We show it is not.", "Is depth enough?"),
    ("Accuracy improves by 3.5 points. Code is public.", "Accuracy improves by 3.5 points."),
    ("One sentence without a final period", "One sentence without a final period."),
])
def test_fallback_first_sentence(abstract, first):
    assert fallback("T", abstract)["one_line"] == first


def test_fallback_with_no_text_at_all_is_still_a_string():
    assert fallback(None, "  ")["one_line"] == ""


def test_empty_legacy_summary_can_be_redone():
    assert needs_llm({"one_line": "", "contributions": [], "keywords": []}) is True
