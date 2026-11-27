"""Pure weekly-change rules for one already-stored paper (no DB, no network)."""

FILL_ONLY = ("abstract", "year", "pub_date", "doi", "arxiv_id", "s2_id", "openalex_id")


def compare(old, new):
    """old: stored fields, new: this round's merged record -> (patch, [(kind, detail)]).
    Never blanks or reverts a field because a provider returned nothing this round."""
    patch, changes, diff = {}, [], []
    if new["norm_title"] != old["norm_title"]:
        diff.append("제목")
        patch.update(title=new["title"], norm_title=new["norm_title"])
    if new["authors"] and [a["name"] for a in new["authors"]] != [a["name"] for a in old["authors"] or []]:
        diff.append("저자")
        patch["authors"] = new["authors"]
    links = {**(old["links"] or {}), **(new["links"] or {})}
    if links != (old["links"] or {}):
        diff.append("링크(" + ", ".join(sorted(set(links) - set(old["links"] or {})) or ["변경"]) + ")")
        patch["links"] = links
    if new["venue"]:
        if old["is_preprint"]:
            changes.append(("ACCEPTED", new["venue"]))
            patch.update(is_preprint=False, venue=new["venue"])
        elif new["venue"] != old["venue"]:
            patch["venue"] = new["venue"]
    for f in FILL_ONLY:
        if new[f] and not old[f]:
            patch[f] = new[f]
    if diff:
        changes.append(("UPDATED", ", ".join(diff)))
    return patch, changes
