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
])
def test_broken_summary_is_rejected_with_reason(bad):
    with pytest.raises(BadSummary) as e:
        validate(bad)
    assert str(e.value).startswith("bad_summary")
