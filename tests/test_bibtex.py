"""Rule 8: citation keys are unique (and valid BibTeX) even when author, year and first word collide."""
import re
from types import SimpleNamespace

from app.bibtex import export, key


def paper(title, author="Jaesik Park", year=2025):
    return SimpleNamespace(title=title, authors=[{"name": author}], year=year, venue="", is_preprint=True,
                           arxiv_id=None, categories=[], doi=None, links={})


def test_same_author_year_word_gets_unique_keys():
    used = set()
    keys = [key(paper("Depth completion " + str(i)), used) for i in range(3)]
    assert keys == ["park2025depth", "park2025deptha", "park2025depthb"]


def test_many_collisions_stay_unique_and_valid():
    used = set()
    keys = [key(paper(f"Depth study {i}"), used) for i in range(60)]
    assert len(set(keys)) == 60
    assert all(re.fullmatch(r"[a-z0-9]+", k) for k in keys), [k for k in keys if not re.fullmatch(r"[a-z0-9]+", k)]


def test_suffixed_key_does_not_clash_with_a_natural_key():
    used = set()
    k1 = key(paper("Depth one"), used)                    # park2025depth
    k2 = key(paper("Deptha naturally"), used)             # park2025deptha (natural)
    k3 = key(paper("Depth two"), used)                    # must skip deptha
    assert len({k1, k2, k3}) == 3


def test_export_keys_unique():
    out = export([paper("Same words here"), paper("Same words there"), paper("Same words")])
    ks = re.findall(r"@\w+\{([^,]+),", out)
    assert len(ks) == len(set(ks)) == 3


def test_empty_author_name_and_missing_title_do_not_crash():
    # review C8: arXiv can yield an empty author name; /bibtex returned 500
    p = SimpleNamespace(title=None, authors=[{"name": ""}], year=2024, venue="", is_preprint=True,
                        arxiv_id=None, categories=[], doi=None, links={})
    assert key(p, set()) == "anon2024paper"
