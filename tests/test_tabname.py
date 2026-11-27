"""Rule 5: an LLM tab name longer than 40 chars or not in 'A · B · C' form is replaced by the rule-based name."""
import pytest

from app.tabname import choose, heuristic

RULE = "KAIST · Computer Vision Lab · matching"


def test_good_llm_name_is_kept():
    assert choose("KAIST 비주얼컴퓨팅랩 · 3D Recon", RULE) == "KAIST 비주얼컴퓨팅랩 · 3D Recon"


def test_quotes_and_extra_lines_are_stripped():
    assert choose('"SNU · 3D Vision Lab · 3D Recon"\nThis name reflects...', RULE) == "SNU · 3D Vision Lab · 3D Recon"


@pytest.mark.parametrize("bad", [
    None,                                                      # LLM failed / unavailable
    "",
    "KAIST Computer Vision Lab",                               # no '·'
    "SNU ·  · 3D",                                             # empty part
    "Korea Advanced Institute of Science and Technology · CV Lab · Matching",   # > 40 chars
])
def test_bad_llm_name_falls_back(bad):
    assert choose(bad, RULE) == RULE


def test_heuristic_name():
    assert heuristic("KAIST Computer Vision Lab | Publications", "KAIST", "Seungryong Kim", ["matching"]) == RULE
    assert heuristic("", "", "Jaesik Park", []) == "Jaesik Park"
