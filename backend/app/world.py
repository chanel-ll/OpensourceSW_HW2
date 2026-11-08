"""Research World: classification (field -> subfield -> paper), layout and edges. No LLM involved.

- Subfields = KMeans over MiniLM embeddings; fields = KMeans over subfield centroids. Names from keywords.
- Re-clustering maps new clusters onto existing ones by member overlap, so user renames / moves / merges survive.
- Between re-clusterings a new paper joins the nearest subfield; if nothing is close enough it waits as a
  "새 세부 분야 후보" until the user turns the candidates into a subfield.
"""
import math
import re
from collections import Counter

import numpy as np
from sklearn.cluster import KMeans

from . import notes
from .collect import enrich, norm_title
from .models import Field, Paper, PaperSource, Project, ProjectReference, Source, Subfield
from .settings import CFG

W = CFG["world"]


def vec(p):
    return np.frombuffer(p.embedding, dtype=np.float32)


def world_papers(db):
    """⭐ papers + papers of sources with 'World에 포함' + references of my projects."""
    src_ids = [s.id for s in db.query(Source).filter_by(include_in_world=True)]
    ids = {p.id for p in db.query(Paper.id).filter(Paper.starred.is_(True))}
    if src_ids:
        ids |= {r.paper_id for r in db.query(PaperSource).filter(PaperSource.source_id.in_(src_ids))}
    ids |= {r.paper_id for r in db.query(ProjectReference)}
    papers = db.query(Paper).filter(Paper.id.in_(ids)).all() if ids else []
    return [p for p in papers if not p.hidden or p.starred]


def _unit(v):
    n = np.linalg.norm(v)
    return v / n if n else v


def _kmeans(X, k):
    k = max(1, min(k, len(X)))
    if k == 1:
        return np.zeros(len(X), dtype=int)
    return KMeans(n_clusters=k, n_init=10, random_state=0).fit_predict(X)


def _match(new_groups: dict[int, set], old_groups: dict[int, set]) -> dict[int, int]:
    """Greedy one-to-one mapping new cluster -> old id by member overlap (keeps ids, names, user edits)."""
    pairs = sorted(((len(n & o), ni, oi) for ni, n in new_groups.items() for oi, o in old_groups.items() if n & o),
                   reverse=True)
    out, used = {}, set()
    for _, ni, oi in pairs:
        if ni not in out and oi not in used:
            out[ni] = oi
            used.add(oi)
    return out


def _name(member_kw: list[list[str]], all_kw_counts: Counter, n_groups: int):
    """c-TF-IDF-ish: frequent here, rare elsewhere. e.g. 'gaussian splatting · novel view'."""
    c = Counter(k for kws in member_kw for k in set(kws))
    score = {k: v * math.log(1 + n_groups / max(1, all_kw_counts[k])) for k, v in c.items()}
    top = [k for k, _ in sorted(score.items(), key=lambda kv: -kv[1])[:2]]
    return " · ".join(top) or "미분류"


def _kw(p):
    return (p.keywords or []) + ((p.summary or {}).get("keywords") or [])


def _centroids(db, papers):
    groups: dict[int, list] = {}
    for p in papers:
        if p.subfield_id:
            groups.setdefault(p.subfield_id, []).append(vec(p))
    return {sid: _unit(np.mean(vs, axis=0)) for sid, vs in groups.items()}


def recluster(db):
    papers = world_papers(db)
    enrich(papers)
    db.flush()
    if not papers:
        return
    X = np.stack([vec(p) for p in papers])
    labels = _kmeans(X, round(math.sqrt(len(papers) / 2)))
    new_groups = {int(l): {p.id for p, pl in zip(papers, labels) if pl == l} for l in set(labels.tolist())}
    old_groups: dict[int, set] = {}
    for p in papers:
        if p.subfield_id:
            old_groups.setdefault(p.subfield_id, set()).add(p.id)
    mapping = _match(new_groups, old_groups)
    for label in new_groups:
        if label not in mapping:
            sf = Subfield()
            db.add(sf)
            db.flush()
            mapping[label] = sf.id
    for p, l in zip(papers, labels):
        if not p.subfield_pinned:
            p.subfield_id = mapping[int(l)]
    db.flush()
    _cleanup(db)
    _regroup_fields(db, papers)
    _rename(db, papers)


def _regroup_fields(db, papers):
    subs = db.query(Subfield).all()
    cents = _centroids(db, papers)
    subs = [s for s in subs if s.id in cents]
    if not subs:
        return
    labels = _kmeans(np.stack([cents[s.id] for s in subs]), round(math.sqrt(len(subs))))
    new_groups = {int(l): {s.id for s, sl in zip(subs, labels) if sl == l} for l in set(labels.tolist())}
    old_groups: dict[int, set] = {}
    for s in subs:
        if s.field_id:
            old_groups.setdefault(s.field_id, set()).add(s.id)
    mapping = _match(new_groups, old_groups)
    for label in new_groups:
        if label not in mapping:
            f = Field()
            db.add(f)
            db.flush()
            mapping[label] = f.id
    for s, l in zip(subs, labels):
        if not s.field_pinned or not s.field_id:
            s.field_id = mapping[int(l)]
    db.flush()
    _cleanup(db)


def _cleanup(db):
    used_sub = {sid for (sid,) in db.query(Paper.subfield_id).filter(Paper.subfield_id.isnot(None)).distinct()}
    for s in db.query(Subfield):
        if s.id not in used_sub:
            db.delete(s)
    db.flush()
    used_field = {fid for (fid,) in db.query(Subfield.field_id).filter(Subfield.field_id.isnot(None)).distinct()}
    for f in db.query(Field):
        if f.id not in used_field:
            db.delete(f)
    db.flush()


def _rename(db, papers):
    all_counts = Counter(k for p in papers for k in set(_kw(p)))
    subs = db.query(Subfield).all()
    by_sub: dict[int, list] = {}
    for p in papers:
        if p.subfield_id:
            by_sub.setdefault(p.subfield_id, []).append(_kw(p))
    for s in subs:
        if not s.name_locked:
            s.name = _name(by_sub.get(s.id, []), all_counts, len(subs))
    fields = db.query(Field).all()
    for f in fields:
        if not f.name_locked:
            members = [kw for s in subs if s.field_id == f.id for kw in by_sub.get(s.id, [])]
            f.name = _name(members, all_counts, len(fields))
    db.flush()


def assign_new(db, papers):
    """Nearest existing subfield for papers without one; too-far papers stay unassigned (candidates)."""
    cents = _centroids(db, papers)
    if not cents:
        return
    ids = list(cents)
    C = np.stack([cents[i] for i in ids])
    for p in papers:
        if p.subfield_id is None:
            sims = C @ vec(p)
            if sims.max() >= W["assign_threshold"]:
                p.subfield_id = ids[int(sims.argmax())]
    db.flush()


def classify(db):
    """Called on every World load: embed what is missing, cluster once, then only assign new papers."""
    papers = world_papers(db)
    enrich(papers)
    db.flush()
    if papers and not db.query(Subfield).count():
        recluster(db)
    else:
        assign_new(db, papers)
        _cleanup(db)
    db.commit()


def make_subfield_from_candidates(db):
    papers = world_papers(db)
    cands = [p for p in papers if p.subfield_id is None]
    if not cands:
        return None
    sf = Subfield()
    db.add(sf)
    db.flush()
    for p in cands:
        p.subfield_id = sf.id
    cent = _unit(np.mean([vec(p) for p in cands], axis=0))
    fields = {}
    for p in papers:
        if p.subfield_id and p.subfield_id != sf.id:
            fid = db.get(Subfield, p.subfield_id).field_id
            fields.setdefault(fid, []).append(vec(p))
    if fields:
        fid, _ = max(((fid, float(_unit(np.mean(vs, axis=0)) @ cent)) for fid, vs in fields.items()), key=lambda t: t[1])
        sf.field_id = fid
    else:
        f = Field()
        db.add(f)
        db.flush()
        sf.field_id = f.id
    db.flush()
    _rename(db, papers)
    db.commit()
    return sf.id


# ---------- layout ----------

def _sphere(n, radius, center):
    """Fibonacci sphere points: even spread, deterministic."""
    if n == 1:
        return [np.array(center, dtype=float)]
    pts = []
    for i in range(n):
        y = 1 - 2 * (i + 0.5) / n
        r = math.sqrt(1 - y * y)
        t = math.pi * (3 - math.sqrt(5)) * i
        pts.append(np.array(center, dtype=float) + radius * np.array([math.cos(t) * r, y, math.sin(t) * r]))
    return pts


def _circle(n, radius, center):
    if n == 1:
        return [np.array(center, dtype=float)]
    return [np.array(center, dtype=float) + radius * np.array([math.cos(2 * math.pi * i / n), math.sin(2 * math.pi * i / n), 0])
            for i in range(n)]


def _jitter(pid, radius, dims):
    rng = np.random.default_rng(pid)
    d = rng.normal(size=dims)
    d /= np.linalg.norm(d) or 1
    out = np.zeros(3)
    out[:dims] = d * radius * rng.uniform(0.35, 1.0)
    return out


def _r(v):
    return [round(float(x), 1) for x in v]


def layout(db, papers):
    fields = sorted(db.query(Field).all(), key=lambda f: f.id)
    subs = sorted(db.query(Subfield).all(), key=lambda s: s.id)
    members: dict[int, list] = {}
    for p in papers:
        members.setdefault(p.subfield_id, []).append(p)
    pos3, pos2, out_fields = {}, {}, []
    F = len(fields)
    fc3 = _sphere(F, 220 + 60 * F, (0, 0, 0)) if F else []
    fc2 = _circle(F, 200 + 70 * F, (0, 0, 0)) if F else []
    for f, c3, c2 in zip(fields, fc3, fc2):
        fsubs = [s for s in subs if s.field_id == f.id]
        sc3 = _sphere(len(fsubs), 70 + 18 * len(fsubs), c3)
        sc2 = _circle(len(fsubs), 70 + 22 * len(fsubs), c2)
        out_subs = []
        for s, s3, s2 in zip(fsubs, sc3, sc2):
            ms = members.get(s.id, [])
            rad = 22 + 6 * math.sqrt(len(ms))
            for p in ms:
                pos3[p.id] = s3 + _jitter(p.id, rad, 3)
                pos2[p.id] = s2 + _jitter(p.id, rad, 2)
            out_subs.append({"id": s.id, "name": s.name, "name_locked": s.name_locked, "count": len(ms),
                             "center3": _r(s3), "radius3": round(rad + 8, 1), "center2": _r(s2), "radius2": round(rad + 8, 1)})
        r3 = max([np.linalg.norm(np.array(s["center3"]) - c3) + s["radius3"] for s in out_subs] or [40]) + 15
        r2 = max([np.linalg.norm(np.array(s["center2"]) - c2) + s["radius2"] for s in out_subs] or [40]) + 15
        out_fields.append({"id": f.id, "name": f.name, "name_locked": f.name_locked, "center3": _r(c3),
                           "radius3": round(float(r3), 1), "center2": _r(c2), "radius2": round(float(r2), 1),
                           "subfields": out_subs})
    far = 220 + 60 * F + 260
    for p in members.get(None, []):  # unassigned candidates float below the universe
        pos3[p.id] = np.array([0, -far, 0]) + _jitter(p.id, 60, 3)
        pos2[p.id] = np.array([0, far, 0]) + _jitter(p.id, 60, 2)
    return out_fields, pos3, pos2


# ---------- edges ----------

def edges(db, papers, projects):
    by_oa = {p.openalex_id: p.id for p in papers if p.openalex_id}
    ids = {p.id for p in papers}
    out = []
    for p in papers:  # citation A -> B
        for ref in p.references or []:
            if ref in by_oa and by_oa[ref] != p.id:
                out.append({"source": p.id, "target": by_oa[ref], "type": "citation"})
    if len(papers) > 1:  # semantic: top-k neighbours
        X = np.stack([vec(p) for p in papers])
        S = X @ X.T
        np.fill_diagonal(S, -1)
        seen = set()
        for i, p in enumerate(papers):
            for j in np.argsort(-S[i])[: W["similar_top_k"]]:
                pair = tuple(sorted((p.id, papers[j].id)))
                if S[i, j] >= W["similar_min"] and pair not in seen:
                    seen.add(pair)
                    out.append({"source": pair[0], "target": pair[1], "type": "similar", "weight": round(float(S[i, j]), 3)})
    # same source / co-author: shared authors (+1 if same source), top 3 per paper to avoid cliques
    # ponytail: O(n²) pair scan, fine to ~2k papers; invert author->papers index if World grows past that
    akeys = {p.id: {a.get("openalex_id") or re.sub(r"[^a-z]", "", a["name"].lower()) for a in p.authors or []} for p in papers}
    srcs: dict[int, set] = {}
    for ps in db.query(PaperSource).filter(PaperSource.paper_id.in_(ids)):
        srcs.setdefault(ps.paper_id, set()).add(ps.source_id)
    seen = set()
    for p in papers:
        scored = []
        for q in papers:
            if q.id != p.id:
                w = len(akeys[p.id] & akeys[q.id]) + bool(srcs.get(p.id, set()) & srcs.get(q.id, set()))
                if w:
                    scored.append((w, q.id))
        for w, qid in sorted(scored, reverse=True)[:3]:
            pair = tuple(sorted((p.id, qid)))
            if pair not in seen:
                seen.add(pair)
                out.append({"source": pair[0], "target": pair[1], "type": "coauthor", "weight": w})
    # manual [[links]] from notes; project notes link the project node
    by_title = {p.norm_title: p.id for p in papers}
    note_owner = {p.note_file: p.id for p in db.query(Paper).filter(Paper.note_file.isnot(None))}
    proj_by_folder = {pr.folder: pr.id for pr in projects}
    seen = set()
    for kind, owner, _, text in notes.all_notes():
        src = note_owner.get(owner) if kind == "paper" else proj_by_folder.get(owner)
        if src is None or (kind == "paper" and src not in ids):
            continue
        for t in notes.links(text):
            tgt = by_title.get(t)
            key = (kind, src, tgt)
            if tgt and tgt != src and key not in seen:
                seen.add(key)
                out.append({"source": src if kind == "paper" else f"project-{src}", "target": tgt, "type": "manual"})
    for r in db.query(ProjectReference):
        if r.paper_id in ids:
            out.append({"source": f"project-{r.project_id}", "target": r.paper_id, "type": "project", "role": r.role})
    return out


def graph(db):
    classify(db)
    papers = world_papers(db)
    projects = db.query(Project).all()
    fields, pos3, pos2 = layout(db, papers)
    sub_field = {s.id: s.field_id for s in db.query(Subfield)}
    srcs: dict[int, list] = {}
    for ps in db.query(PaperSource).filter(PaperSource.paper_id.in_([p.id for p in papers])):
        srcs.setdefault(ps.paper_id, []).append(ps.source_id)
    nodes = [{
        "id": p.id, "kind": "paper", "title": p.title, "authors": [a["name"] for a in (p.authors or [])[:2]],
        "n_authors": len(p.authors or []), "venue": "" if p.is_preprint else p.venue, "is_preprint": p.is_preprint,
        "year": p.year, "keywords": (p.keywords or [])[:5], "one_line": (p.summary or {}).get("one_line", ""),
        "starred": p.starred, "source_ids": srcs.get(p.id, []), "subfield_id": p.subfield_id,
        "field_id": sub_field.get(p.subfield_id), "pos3": _r(pos3[p.id]), "pos2": _r(pos2[p.id]),
    } for p in papers]
    refs: dict[int, list] = {}
    for r in db.query(ProjectReference):
        refs.setdefault(r.project_id, []).append(r.paper_id)
    for i, pr in enumerate(projects):
        ps3 = [pos3[pid] for pid in refs.get(pr.id, []) if pid in pos3]
        ps2 = [pos2[pid] for pid in refs.get(pr.id, []) if pid in pos2]
        c3 = np.mean(ps3, axis=0) + np.array([0, 45, 0]) if ps3 else np.array([-500.0, 300 - 60 * i, 0])
        c2 = np.mean(ps2, axis=0) + np.array([0, -45, 0]) if ps2 else np.array([-500.0, -300 + 60 * i, 0])
        nodes.append({"id": f"project-{pr.id}", "kind": "project", "project_id": pr.id, "title": pr.name,
                      "status": pr.status, "n_refs": len(refs.get(pr.id, [])), "pos3": _r(c3), "pos2": _r(c2)})
    return {"fields": fields, "nodes": nodes, "edges": edges(db, papers, projects),
            "candidates": sum(1 for p in papers if p.subfield_id is None), "candidate_min": W["candidate_min"]}
