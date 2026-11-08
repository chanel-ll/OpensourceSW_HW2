import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import String, cast, func, or_

from . import bibtex, collect, llm, notes, world
from .models import (Author, Field, LibraryGroup, LibraryItem, Paper, PaperChange, PaperSource, Project,
                     ProjectReference, Session, Source, Subfield, UpdateRun, now)
from .settings import APP_VERSION, CFG, ROOT

log = logging.getLogger("api")

# ---------- background jobs: one at a time (collection + weekly share API budgets) ----------
_pool = ThreadPoolExecutor(max_workers=1)
_job_lock = threading.Lock()
job = {"running": False, "kind": "", "message": "", "error": "", "queued": 0}


def submit(kind, fn, *args):
    def run():
        with _job_lock:
            job.update(running=True, kind=kind, message="시작", error="")
        try:
            fn(*args, progress=lambda m: job.update(message=m))
            job["message"] = "완료"
        except Exception as e:
            log.exception("job %s failed", kind)
            job["error"] = f"{type(e).__name__}: {e}"
        finally:
            job["running"] = False
            job["queued"] -= 1

    job["queued"] += 1
    _pool.submit(run)


def last_update_time(db):
    run = db.query(func.max(UpdateRun.finished_at)).filter(UpdateRun.status != "running").scalar()
    if run:
        return run
    return db.query(func.min(Source.last_updated)).scalar()  # first collection counts as the baseline


def update_due(db):
    last = last_update_time(db)
    return last is not None and now() - last >= timedelta(days=CFG["update_interval_days"])


@asynccontextmanager
async def lifespan(_):
    with Session() as db:
        # a run interrupted by closing the app is not "running" anymore
        db.query(UpdateRun).filter_by(status="running").update({"status": "error", "errors": ["앱 종료로 중단됨"]})
        db.query(Source).filter_by(status="collecting").update({"status": "error", "status_message": "앱 종료로 수집이 중단됨 — 다시 수집하세요"})
        db.commit()
        if collect.migration_needed(db):  # new model/preprocessing or papers without embeddings
            submit("embed", collect.migrate_models)
        if update_due(db):
            log.info("last update >= %s days ago: starting automatic weekly update", CFG["update_interval_days"])
            submit("weekly", collect.weekly_update, "auto")
    yield


app = FastAPI(title="Research Tracker", lifespan=lifespan)


# ---------- model info / analysis (also used by the deployment monitor) ----------

def model_info():
    from . import keywords

    k = CFG["keywords"]
    return {"name": k["model"], "revision": k.get("revision"), "preprocess": k.get("preprocess", "basic"),
            "model_id": keywords.model_id(), "app_version": APP_VERSION}


@app.get("/api/model")
def get_model():
    return model_info()


class AnalyzeIn(BaseModel):
    title: str
    abstract: str = ""


@app.post("/api/model/analyze")
def analyze(body: AnalyzeIn):
    """Keyword extraction + embedding on the served model. Public text only, no DB writes, no LLM."""
    from . import keywords

    if not body.title.strip():
        raise HTTPException(400, "title을 입력하세요.")
    t = time.perf_counter()
    doc = f"{body.title}. {body.abstract}"
    kws = keywords.extract([doc])[0]
    vec = keywords.embed([doc])[0]
    return {"keywords": kws, "embedding_dim": int(vec.shape[0]), "embedding_norm": round(float(np.linalg.norm(vec)), 4),
            "elapsed_ms": round((time.perf_counter() - t) * 1000, 1), "model": model_info()}


# ---------- serializers ----------

def paper_json(p: Paper, source_ids=None, change=None):
    return {
        "id": p.id, "title": p.title, "abstract": p.abstract, "year": p.year, "pub_date": p.pub_date,
        "venue": p.venue, "is_preprint": p.is_preprint, "authors": p.authors or [], "links": p.links or {},
        "keywords": p.keywords or [], "categories": p.categories or [], "summary": p.summary,
        "starred": p.starred, "hidden": p.hidden, "source_ids": source_ids or [], "change": change,
    }


def source_json(s: Source, db):
    count = db.query(PaperSource).filter_by(source_id=s.id).count()
    return {
        "id": s.id, "name": s.name, "name_source": s.name_source, "kind": s.kind, "org_type": s.org_type,
        "homepage_url": s.homepage_url, "page_title": s.page_title, "status": s.status,
        "status_message": s.status_message, "keywords": s.keywords or [], "paper_count": count,
        "last_updated": s.last_updated and s.last_updated.isoformat() + "Z", "include_in_world": s.include_in_world,
        "authors": [{"id": a.id, "name": a.name, "affiliation": a.affiliation, "openalex_id": a.openalex_id,
                     "s2_id": a.s2_id, "dblp_pid": a.dblp_pid} for a in s.authors],
    }


def _sources_of(db, paper_ids):
    out = {}
    for ps in db.query(PaperSource).filter(PaperSource.paper_id.in_(paper_ids)):
        out.setdefault(ps.paper_id, []).append(ps.source_id)
    return out


# ---------- status ----------

@app.get("/api/status")
def status():
    with Session() as db:
        last = last_update_time(db)
        unread = db.query(PaperChange).filter_by(read=False).count()
        return {"llm": llm.status(), "job": job, "last_update": last and last.isoformat() + "Z",
                "update_due": update_due(db), "unread_changes": unread,
                "starred_count": db.query(Paper).filter(Paper.starred.is_(True)).count(),
                "model": model_info(),
                "credit": None}  # ponytail: gateway balance API unknown; show when ChatKHU documents one


# ---------- sources: register -> candidates -> confirm -> collect ----------

class InspectIn(BaseModel):
    url: str


@app.post("/api/sources/inspect")
def inspect(body: InspectIn):
    if not body.url.startswith(("http://", "https://")):
        raise HTTPException(400, "http(s) 링크를 입력하세요.")
    return collect.inspect_page(body.url)


class SourceIn(BaseModel):
    homepage_url: str = ""
    name: str = ""
    page_title: str = ""
    org_type: str = "university"
    kind: str = "author_group"


@app.post("/api/sources")
def create_source(body: SourceIn):
    if body.kind != "author_group":
        raise HTTPException(400, "현재는 '저자 그룹' 소스만 지원합니다 (기관+분야, 페이지 파싱은 P3).")
    with Session() as db:
        s = Source(name=body.name or body.page_title or body.homepage_url or "새 소스", homepage_url=body.homepage_url,
                   page_title=body.page_title, org_type=body.org_type, kind=body.kind)
        db.add(s)
        db.commit()
        return source_json(s, db)


@app.get("/api/authors/candidates")
def author_candidates(name: str, hint: str = ""):
    if len(name.strip()) < 2:
        raise HTTPException(400, "저자 이름을 입력하세요.")
    return collect.author_candidates(name.strip(), hint)


class AuthorIn(BaseModel):
    name: str
    affiliation: str = ""
    openalex_id: str | None = None
    s2_id: str | None = None


class ConfirmIn(BaseModel):
    authors: list[AuthorIn]


@app.post("/api/sources/{sid}/authors")
def confirm_authors(sid: int, body: ConfirmIn):
    """Human-confirmed author identities (homonyms!). Each entry needs at least one API id."""
    if not body.authors or any(not (a.openalex_id or a.s2_id) for a in body.authors):
        raise HTTPException(400, "후보 목록에서 저자를 선택하세요 (OpenAlex 또는 Semantic Scholar ID 필요).")
    with Session() as db:
        s = db.get(Source, sid) or _404()
        for a in body.authors:
            dup = next((x for x in s.authors if (a.openalex_id and x.openalex_id == a.openalex_id)
                        or (a.s2_id and x.s2_id == a.s2_id)), None)
            if not dup:
                s.authors.append(Author(**a.model_dump()))
        db.commit()
        return source_json(s, db)


@app.delete("/api/sources/{sid}/authors/{aid}")
def remove_author(sid: int, aid: int):
    with Session() as db:
        a = db.get(Author, aid)
        if not a or a.source_id != sid:
            _404()
        db.delete(a)
        db.commit()
        return source_json(db.get(Source, sid), db)


@app.post("/api/sources/{sid}/collect", status_code=202)
def start_collect(sid: int):
    with Session() as db:
        s = db.get(Source, sid) or _404()
        if not s.authors:
            raise HTTPException(400, "먼저 저자를 확정하세요.")
        if s.status == "collecting":
            raise HTTPException(409, "이미 수집 중입니다.")
        s.status, s.status_message = "collecting", "대기 중..."
        db.commit()
    submit("collect", collect.collect_source, sid)
    return {"queued": True}


@app.get("/api/sources")
def list_sources():
    with Session() as db:
        return [source_json(s, db) for s in db.query(Source).order_by(Source.created_at)]


@app.get("/api/sources/{sid}")
def get_source(sid: int):
    with Session() as db:
        return source_json(db.get(Source, sid) or _404(), db)


class SourcePatch(BaseModel):
    name: str | None = None
    include_in_world: bool | None = None


@app.patch("/api/sources/{sid}")
def patch_source(sid: int, body: SourcePatch):
    with Session() as db:
        s = db.get(Source, sid) or _404()
        if body.name is not None and body.name.strip():
            s.name, s.name_source = body.name.strip(), "user"
        if body.include_in_world is not None:
            s.include_in_world = body.include_in_world
        db.commit()
        return source_json(s, db)


@app.delete("/api/sources/{sid}")
def delete_source(sid: int):
    with Session() as db:
        s = db.get(Source, sid) or _404()
        db.delete(s)
        db.flush()
        # papers no other source references and the user never touched
        orphans = db.query(Paper).filter(~Paper.id.in_(db.query(PaperSource.paper_id)),
                                         ~Paper.id.in_(db.query(ProjectReference.paper_id)),
                                         Paper.starred.is_(False), Paper.summary.is_(None), Paper.note_file.is_(None))
        for p in orphans:
            db.delete(p)
        db.commit()
    return {"deleted": sid}


# ---------- papers ----------

@app.get("/api/papers")
def list_papers(source_id: int | None = None, q: str = "", year: int | None = None, venue: str = "",
                keyword: str = "", include_hidden: bool = False, starred: bool = False):
    with Session() as db:
        qry = db.query(Paper)
        if source_id:
            qry = qry.join(PaperSource).filter(PaperSource.source_id == source_id)
        if not include_hidden:
            qry = qry.filter(Paper.hidden.is_(False))
        if starred:
            qry = qry.filter(Paper.starred.is_(True))
        if year:
            qry = qry.filter(Paper.year == year)
        if venue == "arXiv preprint":
            qry = qry.filter(Paper.is_preprint.is_(True))
        elif venue:
            qry = qry.filter(Paper.venue == venue)
        if q:
            like = f"%{q}%"
            # ponytail: JSON columns searched as text; FTS5 if the library grows past ~10k papers
            qry = qry.filter(or_(Paper.title.ilike(like), cast(Paper.keywords, String).ilike(like),
                                 cast(Paper.authors, String).ilike(like)))
        papers = qry.order_by(Paper.pub_date.desc().nullslast(), Paper.year.desc(), Paper.id.desc()).all()
        if keyword:
            papers = [p for p in papers if keyword in (p.keywords or []) + (p.categories or [])]
        srcs = _sources_of(db, [p.id for p in papers])
        return [paper_json(p, srcs.get(p.id)) for p in papers]


class PaperPatch(BaseModel):
    starred: bool | None = None
    hidden: bool | None = None


@app.patch("/api/papers/{pid}")
def patch_paper(pid: int, body: PaperPatch):
    with Session() as db:
        p = db.get(Paper, pid) or _404()
        if body.starred and not p.starred:
            p.starred_at = now()
        for k, v in body.model_dump(exclude_none=True).items():
            setattr(p, k, v)
        db.commit()
        return paper_json(p, _sources_of(db, [p.id]).get(p.id))


_summary_lock = threading.Lock()


@app.post("/api/papers/{pid}/summarize")
def summarize(pid: int):
    """Called only from the 요약 button. Stored result is returned forever after; never re-calls the LLM."""
    with _summary_lock, Session() as db:
        p = db.get(Paper, pid) or _404()
        if p.summary:
            return paper_json(p, _sources_of(db, [p.id]).get(p.id))
        if not llm.available():
            raise HTTPException(503, llm.status()["reason"])
        try:
            s = llm.summarize(p.title, p.abstract)  # public data only
        except llm.LLMError as e:
            raise HTTPException(503, str(e))
        p.summary = {**s, "model": llm.LLM_MODEL, "created_at": now().isoformat() + "Z"}
        db.commit()
        return paper_json(p, _sources_of(db, [p.id]).get(p.id))


# ---------- weekly ----------

@app.post("/api/weekly/update", status_code=202)
def weekly_update():
    if job["running"] or job["queued"]:
        raise HTTPException(409, f"다른 작업이 진행 중입니다: {job['kind']} — {job['message']}")
    submit("weekly", collect.weekly_update, "manual")
    return {"queued": True}


@app.get("/api/weekly")
def weekly():
    with Session() as db:
        runs = db.query(UpdateRun).order_by(UpdateRun.started_at.desc()).limit(26).all()
        out = []
        for r in runs:
            changes = db.query(PaperChange).filter_by(run_id=r.id).all()
            papers = {p.id: p for p in db.query(Paper).filter(Paper.id.in_([c.paper_id for c in changes]))}
            srcs = _sources_of(db, list(papers))
            by_paper = {}
            for c in changes:
                e = by_paper.setdefault(c.paper_id, {"kinds": [], "detail": [], "read": True, "ids": [], "source_id": c.source_id})
                e["kinds"].append(c.kind)
                e["ids"].append(c.id)
                e["read"] = e["read"] and c.read
                if c.detail:
                    e["detail"].append(f"{c.kind}: {c.detail}")
            items = [paper_json(papers[pid], srcs.get(pid), change=ch) for pid, ch in by_paper.items() if pid in papers]
            prev = db.query(UpdateRun).filter(UpdateRun.started_at < r.started_at, UpdateRun.status != "running") \
                .order_by(UpdateRun.started_at.desc()).first()
            out.append({
                "id": r.id, "started_at": r.started_at.isoformat() + "Z",
                "finished_at": r.finished_at and r.finished_at.isoformat() + "Z", "status": r.status,
                "trigger": r.trigger, "errors": r.errors or [],
                "period_start": (prev.started_at if prev else r.started_at - timedelta(days=CFG["update_interval_days"])).isoformat() + "Z",
                "counts": {"new": sum("NEW" in i["change"]["kinds"] for i in items),
                           "accepted": sum("ACCEPTED" in i["change"]["kinds"] for i in items),
                           "updated": sum("UPDATED" in i["change"]["kinds"] for i in items),
                           "sources": len({c.source_id for c in changes})},
                "items": items,
            })
        return out


class ReadIn(BaseModel):
    change_ids: list[int]


@app.post("/api/changes/read")
def mark_read(body: ReadIn):
    with Session() as db:
        db.query(PaperChange).filter(PaperChange.id.in_(body.change_ids)).update({"read": True})
        db.commit()
    return {"ok": True}


def _404():
    raise HTTPException(404, "not found")


# ================= P1: paper notes =================

def brief(p: Paper):
    return {"id": p.id, "title": p.title, "year": p.year, "venue": "arXiv preprint" if p.is_preprint or not p.venue else p.venue}


def _note_owners(db):
    return ({p.note_file: p for p in db.query(Paper).filter(Paper.note_file.isnot(None))},
            {pr.folder: pr for pr in db.query(Project)})


def backlinks(db, p: Paper):
    """Notes (paper memos or project notes) that contain [[this paper]]."""
    paper_notes, proj = _note_owners(db)
    out = []
    for kind, owner, path, text in notes.all_notes():
        if p.norm_title not in notes.links(text):
            continue
        if kind == "paper" and owner in paper_notes and paper_notes[owner].id != p.id:
            out.append({"kind": "paper", "paper_id": paper_notes[owner].id, "title": paper_notes[owner].title})
        elif kind == "project" and owner in proj:
            out.append({"kind": "project", "project_id": proj[owner].id, "project": proj[owner].name, "note": path.stem})
    return out


@app.get("/api/papers/{pid}")
def paper_detail(pid: int):
    with Session() as db:
        p = db.get(Paper, pid) or _404()
        if p.embedding is None:
            collect.enrich([p])
            db.commit()
        all_papers = db.query(Paper).all()
        by_oa = {x.openalex_id: x for x in all_papers if x.openalex_id}
        cites = [brief(by_oa[r]) for r in p.references or [] if r in by_oa and by_oa[r].id != pid]
        cited_by = [brief(x) for x in all_papers if p.openalex_id and p.openalex_id in (x.references or [])]
        others = [x for x in all_papers if x.embedding is not None and x.id != pid]
        similar = []
        if others:
            sims = np.stack([world.vec(x) for x in others]) @ world.vec(p)
            similar = [{**brief(others[i]), "similarity": round(float(sims[i]), 2)}
                       for i in np.argsort(-sims)[:5] if sims[i] >= 0.45]
        sub = db.get(Subfield, p.subfield_id) if p.subfield_id else None
        field = db.get(Field, sub.field_id) if sub and sub.field_id else None
        src_ids = _sources_of(db, [pid]).get(pid, [])
        projects = [{"project_id": pr.id, "name": pr.name, "role": r.role, "memo": r.memo}
                    for r, pr in db.query(ProjectReference, Project).join(Project).filter(ProjectReference.paper_id == pid)]
        return {
            **paper_json(p, src_ids),
            "sources": [{"id": s.id, "name": s.name} for s in db.query(Source).filter(Source.id.in_(src_ids))],
            "classification": {"field": field and {"id": field.id, "name": field.name},
                               "subfield": sub and {"id": sub.id, "name": sub.name}},
            "related": {"cites": cites, "cited_by": cited_by, "similar": similar},
            "memo": notes.read(notes.PAPERS / p.note_file) if p.note_file else "",
            "note_path": str(notes.PAPERS / p.note_file) if p.note_file else "",
            "backlinks": backlinks(db, p),
            "projects": projects,
        }


class NoteIn(BaseModel):
    content: str


@app.put("/api/papers/{pid}/note")
def save_paper_note(pid: int, body: NoteIn):
    with Session() as db:
        p = db.get(Paper, pid) or _404()
        if not p.note_file:
            notes.PAPERS.mkdir(parents=True, exist_ok=True)
            p.note_file = notes.unique_path(notes.PAPERS, notes.safe_name(p.title)).name
            db.commit()
        notes.write(notes.PAPERS / p.note_file, body.content)
        return {"saved_at": now().isoformat() + "Z", "path": str(notes.PAPERS / p.note_file)}


@app.get("/api/titles")
def titles():
    """For [[ autocomplete. Inserting [[file-safe title]] keeps links valid in Obsidian too."""
    with Session() as db:
        return [{"id": p.id, "title": p.title, "link": notes.safe_name(p.title), "year": p.year}
                for p in db.query(Paper).order_by(Paper.year.desc().nullslast(), Paper.title)]


# ================= P1: My Research =================

STATUSES = ["아이디어", "진행 중", "투고 준비", "완료"]
ROLES = ["베이스라인", "관련 연구", "방법론 참고", "데이터셋"]


def _folder(pr: Project):
    return notes.PROJECTS / pr.folder


def _note_files(pr: Project):
    f = _folder(pr)
    return sorted(f.glob("*.md"), key=lambda x: -x.stat().st_mtime) if f.exists() else []


def _note_path(pr: Project, name: str):
    if notes.safe_name(name) != name:
        raise HTTPException(400, "노트 이름에 사용할 수 없는 문자가 있습니다.")
    return _folder(pr) / f"{name}.md"


def project_json(db, pr: Project, full=False):
    files = _note_files(pr)
    newest = max([pr.updated_at.timestamp()] + [f.stat().st_mtime for f in files])
    out = {"id": pr.id, "name": pr.name, "description": pr.description, "status": pr.status, "folder": str(_folder(pr)),
           "note_count": len(files), "ref_count": db.query(ProjectReference).filter_by(project_id=pr.id).count(),
           "updated_at": datetime.fromtimestamp(newest, timezone.utc).isoformat()}
    if full:
        rows = db.query(ProjectReference, Paper).join(Paper).filter(ProjectReference.project_id == pr.id) \
            .order_by(ProjectReference.added_at.desc()).all()
        srcs = _sources_of(db, [p.id for _, p in rows])
        out["references"] = [{**paper_json(p, srcs.get(p.id)), "role": r.role, "memo": r.memo} for r, p in rows]
        out["notes"] = [{"name": f.stem, "updated_at": datetime.fromtimestamp(f.stat().st_mtime, timezone.utc).isoformat()}
                        for f in files]
    return out


class ProjectIn(BaseModel):
    name: str
    description: str = ""
    status: str = "아이디어"


@app.get("/api/projects")
def list_projects():
    with Session() as db:
        return [project_json(db, pr) for pr in db.query(Project).order_by(Project.updated_at.desc())]


@app.post("/api/projects")
def create_project(body: ProjectIn):
    if not body.name.strip():
        raise HTTPException(400, "프로젝트 이름을 입력하세요.")
    if body.status not in STATUSES:
        raise HTTPException(400, f"상태는 {', '.join(STATUSES)} 중 하나입니다.")
    notes.PROJECTS.mkdir(parents=True, exist_ok=True)
    folder = notes.unique_path(notes.PROJECTS, notes.safe_name(body.name)).stem
    (notes.PROJECTS / folder).mkdir()
    with Session() as db:
        pr = Project(name=body.name.strip(), description=body.description, status=body.status, folder=folder)
        db.add(pr)
        db.commit()
        return project_json(db, pr, full=True)


@app.get("/api/projects/{prid}")
def get_project(prid: int):
    with Session() as db:
        return project_json(db, db.get(Project, prid) or _404(), full=True)


class ProjectPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    status: str | None = None


@app.patch("/api/projects/{prid}")
def patch_project(prid: int, body: ProjectPatch):
    with Session() as db:
        pr = db.get(Project, prid) or _404()
        if body.status is not None:
            if body.status not in STATUSES:
                raise HTTPException(400, f"상태는 {', '.join(STATUSES)} 중 하나입니다.")
            pr.status = body.status
        if body.description is not None:
            pr.description = body.description
        if body.name and body.name.strip() and body.name.strip() != pr.name:
            pr.name = body.name.strip()
            new = notes.unique_path(notes.PROJECTS, notes.safe_name(pr.name)).stem
            if _folder(pr).exists():
                _folder(pr).rename(notes.PROJECTS / new)
            pr.folder = new
        pr.updated_at = now()
        db.commit()
        return project_json(db, pr, full=True)


@app.delete("/api/projects/{prid}")
def delete_project(prid: int):
    with Session() as db:
        pr = db.get(Project, prid) or _404()
        notes.trash(_folder(pr))  # notes are moved to notes/.trash, never erased
        db.delete(pr)
        db.commit()
    return {"deleted": prid}


class NoteCreate(BaseModel):
    title: str


@app.post("/api/projects/{prid}/notes")
def create_note(prid: int, body: NoteCreate):
    with Session() as db:
        pr = db.get(Project, prid) or _404()
        _folder(pr).mkdir(parents=True, exist_ok=True)
        path = notes.unique_path(_folder(pr), notes.safe_name(body.title))
        notes.write(path, "")
        pr.updated_at = now()
        db.commit()
        return {"name": path.stem}


@app.get("/api/projects/{prid}/notes/{name}")
def read_note(prid: int, name: str):
    with Session() as db:
        path = _note_path(db.get(Project, prid) or _404(), name)
        if not path.exists():
            _404()
        return {"name": name, "content": notes.read(path), "path": str(path)}


@app.put("/api/projects/{prid}/notes/{name}")
def save_note(prid: int, name: str, body: NoteIn):
    with Session() as db:
        path = _note_path(db.get(Project, prid) or _404(), name)
        notes.write(path, body.content)
        return {"saved_at": now().isoformat() + "Z"}


class NoteRename(BaseModel):
    title: str


@app.patch("/api/projects/{prid}/notes/{name}")
def rename_note(prid: int, name: str, body: NoteRename):
    with Session() as db:
        pr = db.get(Project, prid) or _404()
        path = _note_path(pr, name)
        if not path.exists():
            _404()
        new = notes.unique_path(_folder(pr), notes.safe_name(body.title))
        path.rename(new)
        return {"name": new.stem}


@app.delete("/api/projects/{prid}/notes/{name}")
def delete_note(prid: int, name: str):
    with Session() as db:
        notes.trash(_note_path(db.get(Project, prid) or _404(), name))
    return {"deleted": name}


class RefIn(BaseModel):
    paper_id: int | None = None
    query: str = ""          # arXiv link/id, DOI or exact title
    openalex_id: str = ""    # chosen from candidates
    role: str = "관련 연구"


@app.post("/api/projects/{prid}/references")
def add_reference(prid: int, body: RefIn):
    if body.role not in ROLES:
        raise HTTPException(400, f"역할은 {', '.join(ROLES)} 중 하나입니다.")
    with Session() as db:
        pr = db.get(Project, prid) or _404()
        if body.paper_id:
            p = db.get(Paper, body.paper_id) or _404()
        else:
            if not (body.query.strip() or body.openalex_id):
                raise HTTPException(400, "arXiv 링크, DOI 또는 논문 제목을 입력하세요.")
            try:
                p, cands = collect.resolve_reference(db, body.query, body.openalex_id)
            except collect.ApiError as e:
                raise HTTPException(502, f"학술 API 조회 실패: {e}")
            if p is None:
                db.rollback()
                raise HTTPException(409, {"message": "정확히 일치하는 논문이 없습니다. 후보에서 선택하세요.", "candidates": cands})
        if not db.get(ProjectReference, (pr.id, p.id)):
            db.add(ProjectReference(project_id=pr.id, paper_id=p.id, role=body.role))
        pr.updated_at = now()
        db.commit()
        return project_json(db, pr, full=True)


class RefPatch(BaseModel):
    role: str | None = None
    memo: str | None = None


@app.patch("/api/projects/{prid}/references/{pid}")
def patch_reference(prid: int, pid: int, body: RefPatch):
    with Session() as db:
        r = db.get(ProjectReference, (prid, pid)) or _404()
        if body.role is not None:
            if body.role not in ROLES:
                raise HTTPException(400, f"역할은 {', '.join(ROLES)} 중 하나입니다.")
            r.role = body.role
        if body.memo is not None:
            r.memo = body.memo
        db.commit()
        return {"role": r.role, "memo": r.memo}


@app.delete("/api/projects/{prid}/references/{pid}")
def delete_reference(prid: int, pid: int):
    with Session() as db:
        r = db.get(ProjectReference, (prid, pid)) or _404()
        db.delete(r)
        db.commit()
    return {"deleted": pid}


@app.get("/api/projects/{prid}/bibtex", response_class=PlainTextResponse)
def project_bibtex(prid: int):
    with Session() as db:
        pr = db.get(Project, prid) or _404()
        papers = [p for _, p in db.query(ProjectReference, Paper).join(Paper).filter(ProjectReference.project_id == prid)
                  .order_by(Paper.year.desc().nullslast())]
        name = quote(f"{notes.safe_name(pr.name)}.bib")  # RFC 5987: keeps Korean project names
        return PlainTextResponse(bibtex.export(papers), media_type="application/x-bibtex; charset=utf-8",
                                 headers={"Content-Disposition": f"attachment; filename=\"references.bib\"; filename*=UTF-8''{name}"})


# ================= P2: Research World =================

_world_lock = threading.Lock()


@app.get("/api/world")
def get_world():
    with _world_lock, Session() as db:
        return world.graph(db)


@app.post("/api/world/recluster")
def recluster():
    with _world_lock, Session() as db:
        world.recluster(db)
        db.commit()
        return world.graph(db)


@app.post("/api/world/candidates")
def candidates_to_subfield():
    with _world_lock, Session() as db:
        if world.make_subfield_from_candidates(db) is None:
            raise HTTPException(400, "새 세부 분야 후보가 없습니다.")
        return world.graph(db)


class NameIn(BaseModel):
    name: str


@app.patch("/api/world/fields/{fid}")
def rename_field(fid: int, body: NameIn):
    with _world_lock, Session() as db:
        f = db.get(Field, fid) or _404()
        f.name, f.name_locked = body.name.strip() or f.name, True
        db.commit()
        return {"id": f.id, "name": f.name}


class SubfieldPatch(BaseModel):
    name: str | None = None
    field_id: int | None = None


@app.patch("/api/world/subfields/{sid}")
def patch_subfield(sid: int, body: SubfieldPatch):
    with _world_lock, Session() as db:
        s = db.get(Subfield, sid) or _404()
        if body.name and body.name.strip():
            s.name, s.name_locked = body.name.strip(), True
        if body.field_id is not None:
            db.get(Field, body.field_id) or _404()
            s.field_id, s.field_pinned = body.field_id, True
            world._cleanup(db)
        db.commit()
        return {"id": s.id, "name": s.name, "field_id": s.field_id}


class MergeIn(BaseModel):
    into: int


@app.post("/api/world/subfields/{sid}/merge")
def merge_subfield(sid: int, body: MergeIn):
    with _world_lock, Session() as db:
        src, dst = db.get(Subfield, sid) or _404(), db.get(Subfield, body.into) or _404()
        if src.id == dst.id:
            raise HTTPException(400, "같은 세부 분야입니다.")
        for p in db.query(Paper).filter(Paper.subfield_id.in_([src.id, dst.id])):
            p.subfield_id, p.subfield_pinned = dst.id, True  # pin both sides: reclustering must not split it again
        world._cleanup(db)
        db.commit()
        return world.graph(db)


@app.post("/api/world/fields/{fid}/merge")
def merge_field(fid: int, body: MergeIn):
    with _world_lock, Session() as db:
        src, dst = db.get(Field, fid) or _404(), db.get(Field, body.into) or _404()
        if src.id == dst.id:
            raise HTTPException(400, "같은 분야입니다.")
        for s in db.query(Subfield).filter(Subfield.field_id.in_([src.id, dst.id])):
            s.field_id, s.field_pinned = dst.id, True
        world._cleanup(db)
        db.commit()
        return world.graph(db)


class MoveIn(BaseModel):
    subfield_id: int


@app.patch("/api/papers/{pid}/subfield")
def move_paper(pid: int, body: MoveIn):
    with _world_lock, Session() as db:
        p = db.get(Paper, pid) or _404()
        db.get(Subfield, body.subfield_id) or _404()
        p.subfield_id, p.subfield_pinned = body.subfield_id, True
        world._cleanup(db)
        db.commit()
        return {"id": p.id, "subfield_id": p.subfield_id}


# ================= Library: starred papers + user groups =================

@app.get("/api/library")
def library():
    with Session() as db:
        papers = db.query(Paper).filter(Paper.starred.is_(True))             .order_by(Paper.starred_at.desc().nullslast(), Paper.id.desc()).all()
        ids = [p.id for p in papers]
        member: dict[int, list] = {}
        for it in db.query(LibraryItem).filter(LibraryItem.paper_id.in_(ids)):
            member.setdefault(it.paper_id, []).append(it.group_id)
        srcs = _sources_of(db, ids)
        groups = db.query(LibraryGroup).order_by(LibraryGroup.created_at).all()
        return {
            "groups": [{"id": g.id, "name": g.name, "count": sum(g.id in member.get(pid, []) for pid in ids)} for g in groups],
            "papers": [{**paper_json(p, srcs.get(p.id)), "group_ids": member.get(p.id, [])} for p in papers],
        }


@app.post("/api/library/groups")
def create_group(body: NameIn):
    if not body.name.strip():
        raise HTTPException(400, "그룹 이름을 입력하세요.")
    with Session() as db:
        g = LibraryGroup(name=body.name.strip())
        db.add(g)
        db.commit()
        return {"id": g.id, "name": g.name}


@app.patch("/api/library/groups/{gid}")
def rename_group(gid: int, body: NameIn):
    with Session() as db:
        g = db.get(LibraryGroup, gid) or _404()
        if body.name.strip():
            g.name = body.name.strip()
        db.commit()
        return {"id": g.id, "name": g.name}


@app.delete("/api/library/groups/{gid}")
def delete_group(gid: int):
    """Removes the group only; its papers stay starred in the Library."""
    with Session() as db:
        db.delete(db.get(LibraryGroup, gid) or _404())
        db.commit()
    return {"deleted": gid}


@app.put("/api/library/groups/{gid}/papers/{pid}")
def add_to_group(gid: int, pid: int):
    with Session() as db:
        db.get(LibraryGroup, gid) or _404()
        p = db.get(Paper, pid) or _404()
        if not p.starred:  # Library == starred papers, so grouping a paper stars it
            p.starred, p.starred_at = True, now()
        if not db.get(LibraryItem, (gid, pid)):
            db.add(LibraryItem(group_id=gid, paper_id=pid))
        db.commit()
        return {"group_id": gid, "paper_id": pid}


@app.delete("/api/library/groups/{gid}/papers/{pid}")
def remove_from_group(gid: int, pid: int):
    with Session() as db:
        it = db.get(LibraryItem, (gid, pid))
        if it:
            db.delete(it)
            db.commit()
    return {"group_id": gid, "paper_id": pid}


# Built frontend (Docker image / `npm run build`): one port serves UI + API. Must stay after all /api routes.
_DIST = ROOT / "frontend" / "dist"
if _DIST.is_dir():
    app.mount("/", StaticFiles(directory=_DIST, html=True), name="ui")
