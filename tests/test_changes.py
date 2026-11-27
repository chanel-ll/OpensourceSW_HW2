"""Rule 6: preprint -> venue is ACCEPTED; a provider that is briefly missing data never reverts stored data."""
from app.changes import compare

OLD = {"norm_title": "depth completion", "title": "Depth Completion", "authors": [{"name": "A"}, {"name": "B"}],
       "links": {"arxiv": "https://arxiv.org/abs/1"}, "is_preprint": True, "venue": "", "abstract": "abs",
       "year": 2025, "pub_date": "2025-01-01", "doi": None, "arxiv_id": "1", "s2_id": None, "openalex_id": "W1"}
EMPTY = {k: None for k in ("abstract", "year", "pub_date", "doi", "arxiv_id", "s2_id", "openalex_id")}


def rec(**kw):
    return {"norm_title": OLD["norm_title"], "title": OLD["title"], "authors": [], "links": {}, "venue": "", **EMPTY, **kw}


def test_preprint_published_at_venue_is_accepted():
    patch, changes = compare(OLD, rec(venue="CVPR 2026"))
    assert changes == [("ACCEPTED", "CVPR 2026")]
    assert patch["is_preprint"] is False and patch["venue"] == "CVPR 2026"


def test_missing_provider_data_does_not_revert_anything():
    published = {**OLD, "is_preprint": False, "venue": "CVPR 2026"}
    patch, changes = compare(published, rec())          # this round: no venue, no authors, no links, no ids
    assert patch == {} and changes == []


def test_new_link_and_author_change_are_updated():
    patch, changes = compare(OLD, rec(authors=[{"name": "A"}, {"name": "C"}], links={"code": "https://g/x"}))
    assert changes == [("UPDATED", "저자, 링크(code)")]
    assert patch["links"] == {"arxiv": "https://arxiv.org/abs/1", "code": "https://g/x"}


def test_empty_fields_are_filled_but_never_overwritten():
    patch, changes = compare(OLD, rec(doi="10.1/x", abstract="different abstract", year=2026))
    assert patch == {"doi": "10.1/x"} and changes == []


def test_retitled_paper_is_updated():
    patch, changes = compare(OLD, rec(norm_title="depth completion v2", title="Depth Completion v2"))
    assert changes == [("UPDATED", "제목")] and patch["title"] == "Depth Completion v2"
