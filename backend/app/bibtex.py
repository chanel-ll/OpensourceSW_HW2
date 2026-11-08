"""BibTeX for a project's references."""
import re
import unicodedata

CONF = re.compile(r"conference|proceedings|symposium|workshop|\b(CVPR|ICCV|ECCV|NeurIPS|ICML|ICLR|AAAI|IJCAI|SIGGRAPH|"
                  r"ACL|EMNLP|NAACL|ICRA|IROS|CoRL|RSS|3DV|WACV|BMVC|MICCAI|KDD|WWW|CHI|UIST|ISMAR)\b", re.I)


def _ascii(s):
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()


def _esc(s):
    return (s or "").replace("\\", "").replace("{", "").replace("}", "")


def key(p, used: set):
    last = re.sub(r"[^a-z]", "", _ascii((p.authors or [{"name": "anon"}])[0]["name"].split()[-1].lower())) or "anon"
    word = next((w for w in re.findall(r"[a-z]+", _ascii(p.title.lower())) if len(w) > 3), "paper")
    k, i = f"{last}{p.year or ''}{word}", 1
    while k in used:
        i += 1
        k = f"{last}{p.year or ''}{word}{chr(96 + i)}"
    used.add(k)
    return k


def entry(p, used: set):
    fields = {"title": "{" + _esc(p.title) + "}",  # double braces keep capitalization
              "author": " and ".join(_esc(a["name"]) for a in p.authors or [])}
    if p.is_preprint or not p.venue:
        kind = "misc"
        if p.arxiv_id:
            fields.update(eprint=p.arxiv_id, archivePrefix="arXiv", primaryClass=(p.categories or [""])[0])
    elif CONF.search(p.venue):
        kind, fields["booktitle"] = "inproceedings", _esc(p.venue)
    else:
        kind, fields["journal"] = "article", _esc(p.venue)
    fields.update(year=str(p.year or ""), doi=p.doi or "", url=(p.links or {}).get("arxiv") or (p.links or {}).get("doi") or "")
    body = ",\n".join(f"  {k} = {{{v}}}" for k, v in fields.items() if v)
    return f"@{kind}{{{key(p, used)},\n{body}\n}}"


def export(papers):
    used: set = set()
    return "\n\n".join(entry(p, used) for p in papers) + "\n"


if __name__ == "__main__":
    from types import SimpleNamespace as P

    a = P(title="Splat-Based {3D} Scene", authors=[{"name": "Hyeonjoong Jang"}, {"name": "Min H. Kim"}], year=2025,
          venue="ICCV", is_preprint=False, arxiv_id=None, categories=[], doi="10.1/x", links={})
    b = P(title="Splat Something Else", authors=[{"name": "Hyeonjoong Jang"}], year=2025, venue="", is_preprint=True,
          arxiv_id="2501.00001", categories=["cs.CV"], doi=None, links={"arxiv": "https://arxiv.org/abs/2501.00001"})
    c = P(title="Journal Paper", authors=[{"name": "José Müller"}], year=2024, venue="ACM TOG", is_preprint=False,
          arxiv_id=None, categories=[], doi=None, links={})
    out = export([a, b, c])
    print(out)
    assert "@inproceedings{jang2025splat," in out and "booktitle = {ICCV}" in out
    assert "@misc{jang2025splatb," in out and "eprint = {2501.00001}" in out
    assert "@article{muller2024journal," in out and "title = {{Splat-Based 3D Scene}}" in out
