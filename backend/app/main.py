import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import timedelta

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy import String, cast, func, or_

from . import collect, llm
from .models import Author, Paper, PaperChange, PaperSource, Session, Source, UpdateRun, now
from .settings import CFG

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
        if update_due(db):
            log.info("last update >= %s days ago: starting automatic weekly update", CFG["update_interval_days"])
            submit("weekly", collect.weekly_update, "auto")
    yield


app = FastAPI(title="Research Tracker", lifespan=lifespan)


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
                                         Paper.starred.is_(False), Paper.summary.is_(None))
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
