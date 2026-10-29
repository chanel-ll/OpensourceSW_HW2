"""Academic API clients (OpenAlex, Semantic Scholar, DBLP, arXiv), source collection and weekly diff.

Role split:
  OpenAlex  - author candidates (affiliation) + main 2-year works list
  S2        - author candidates + works (abstracts, venue acronyms)
  DBLP      - venue acronyms, auto-matched only when titles overlap (homonym guard); skipped if it serves a bot check
  arXiv     - categories, abstract/pdf fallback for papers with an arXiv id
"""
import html
import logging
import random
import re
import threading
import time
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import date, timedelta

import httpx

from . import llm
from .models import Author, Paper, PaperChange, PaperSource, Session, Source, UpdateRun, now
from .settings import CFG, OPENALEX_API_KEY, S2_API_KEY

log = logging.getLogger("collect")
UA = f"ResearchTracker/0.1 (personal research tracker{'; mailto:' + CFG['contact_email'] if CFG['contact_email'] else ''})"
RETRY_STATUS = {429, 500, 502, 503, 504}
MIN_INTERVAL = {"openalex": 0.15, "s2": 0.3 if S2_API_KEY else 1.1, "dblp": 1.0, "arxiv": 3.1, "page": 0}
_last_call: dict[str, float] = {}
_pace_lock = threading.Lock()
client = httpx.Client(headers={"User-Agent": UA}, timeout=30, follow_redirects=True)


class ApiError(Exception):
    pass


def _pace(provider):
    with _pace_lock:
        wait = _last_call.get(provider, 0) + MIN_INTERVAL.get(provider, 0) - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_call[provider] = time.monotonic()


def fetch(provider, url, params=None, headers=None, retries=5, base_delay=1.0, as_json=True):
    """GET with exponential backoff on 429/5xx/network errors. Raises ApiError with a human-readable cause."""
    err = ""
    for attempt in range(retries + 1):
        _pace(provider)
        retry_after = None
        try:
            r = client.get(url, params=params, headers=headers)
        except httpx.HTTPError as e:
            err = f"네트워크 오류 {type(e).__name__}: {e}"
        else:
            if r.status_code == 200:
                if not as_json:
                    return r.text
                try:
                    return r.json()
                except ValueError:
                    raise ApiError(f"{provider}: JSON이 아닌 응답 (HTTP 200, {r.headers.get('content-type')})")
            if "not a bot" in r.text[:2000]:
                raise ApiError(f"{provider}: 봇 확인 페이지 반환 (HTTP {r.status_code}) — 우회하지 않고 건너뜀")
            err = f"HTTP {r.status_code} {r.text[:150]!r}"
            if r.status_code not in RETRY_STATUS:
                raise ApiError(f"{provider}: {err}")
            if r.headers.get("retry-after", "").isdigit():
                retry_after = int(r.headers["retry-after"])
        if attempt == retries:
            break
        delay = min(retry_after or base_delay * 2 ** attempt + random.random() * 0.5, 60)
        log.warning("%s %s -> %s; retry %d/%d in %.1fs", provider, url, err, attempt + 1, retries, delay)
        time.sleep(delay)
    raise ApiError(f"{provider}: {err} — {retries}회 재시도(지수 백오프) 후 실패")


# ---------- helpers ----------

def norm_title(t):
    return re.sub(r"[^a-z0-9]+", "", (t or "").lower())


def norm_name(n):
    return re.sub(r"[^a-z]", "", (n or "").lower())


STOP = {"of", "and", "the", "for", "in", "at", "de"}


def acronym(name):
    return "".join(w[0] for w in re.findall(r"[A-Za-z]+", name) if w.lower() not in STOP).upper()


def cutoff_date():
    return date.today() - timedelta(days=CFG["lookback_days"])


def is_preprint_venue(v):
    v = (v or "").lower()
    return not v or "arxiv" in v or v in {"corr", "biorxiv", "medrxiv", "ssrn"}


VENUE_SHORT = {  # long names APIs return -> the label researchers use; extend in place
    "acm transactions on graphics": "ACM TOG", "computer graphics forum": "CGF",
    "ieee transactions on pattern analysis and machine intelligence": "TPAMI",
    "ieee robotics and automation letters": "RA-L", "international journal of computer vision": "IJCV",
    "ieee transactions on visualization and computer graphics": "TVCG",
    "neural information processing systems": "NeurIPS", "international conference on machine learning": "ICML",
    "international conference on learning representations": "ICLR",
    "computer vision and pattern recognition": "CVPR", "european conference on computer vision": "ECCV",
    "siggraph asia conference papers": "SIGGRAPH Asia", "acm siggraph conference papers": "SIGGRAPH",
}


def short_venue(v):
    if not v:
        return v
    m = re.search(r"\(([A-Z][A-Za-z0-9\-]{1,11})\)\s*$", v)  # "... Computer Vision (ICCV)" -> ICCV
    if m:
        return m.group(1)
    low = v.lower()
    return next((s for k, s in VENUE_SHORT.items() if k in low), v)


def arxiv_from(text):
    m = re.search(r"(\d{4}\.\d{4,5})", text or "")
    return m.group(1) if m else None


# ---------- page inspection (step 1-3 of source registration) ----------

NAME_EN = r"([A-Z][a-zA-Z\-]+\.?(?:\s+[A-Z][a-zA-Z\-]*\.?){1,3})"
NAME_PATTERNS = [
    re.compile(r"(?:led by|directed by|headed by|Prof(?:essor)?\.?|Principal Investigator:?|PI:)\s+" + NAME_EN),
    re.compile(r"([가-힣]{2,4})\s*교수"),
]


def inspect_page(url):
    try:
        text = fetch("page", url, retries=2, as_json=False, headers={"Accept": "text/html"})
    except ApiError as e:
        return {"title": "", "org_type": "university", "names": [], "error": str(e)}
    m = re.search(r"<title[^>]*>(.*?)</title>", text, re.S | re.I)
    title = html.unescape(re.sub(r"\s+", " ", m.group(1))).strip() if m else ""
    body = html.unescape(re.sub(r"<[^>]+>", " ", text))
    names = []
    for pat in NAME_PATTERNS:
        for hit in pat.findall(title + " \n " + body):
            hit = hit.strip()
            if hit not in names and hit.lower() not in {"professor", "prof"}:
                names.append(hit)
    lower = (url + " " + title).lower()
    org = "university" if re.search(r"\.ac\.|\.edu|univ|대학|kaist|postech|lab\b|laborator", lower) else "company"
    return {"title": title, "org_type": org, "names": names[:6], "error": ""}


# ---------- author candidates (step 4) ----------

def _rank(cands, name, hint):
    hint_l = (hint or "").lower()
    nn = norm_name(name)

    def score(c):
        aff = c["affiliation"]
        aff_hit = bool(hint_l) and any(a.lower() in hint_l or (len(acronym(a)) > 2 and acronym(a).lower() in hint_l)
                                       for a in aff.split("; ") if a)
        return (aff_hit, norm_name(c["name"]) == nn, c["paper_count"] or 0)

    return sorted(cands, key=score, reverse=True)


def candidates_openalex(name, hint=""):
    params = {"search": name, "per-page": 25, "select": "id,display_name,last_known_institutions,works_count"}
    if OPENALEX_API_KEY:
        params["api_key"] = OPENALEX_API_KEY
    data = fetch("openalex", "https://api.openalex.org/authors", params, retries=3)
    cands = [{
        "provider": "openalex", "id": r["id"].rsplit("/", 1)[-1], "name": r["display_name"],
        "affiliation": "; ".join(i["display_name"] for i in (r.get("last_known_institutions") or [])),
        "paper_count": r.get("works_count"), "recent_papers": [],
    } for r in data["results"]]
    cands = _rank(cands, name, hint)[:6]
    if cands:  # one call for everyone's recent works
        p = {"filter": "author.id:" + "|".join(c["id"] for c in cands), "sort": "publication_date:desc",
             "per-page": 200, "select": "title,publication_year,authorships"}
        if OPENALEX_API_KEY:
            p["api_key"] = OPENALEX_API_KEY
        works = fetch("openalex", "https://api.openalex.org/works", p, retries=3)["results"]
        by_id = {c["id"]: c for c in cands}
        for w in works:
            for a in w.get("authorships") or []:
                c = by_id.get((a["author"].get("id") or "").rsplit("/", 1)[-1])
                if c and len(c["recent_papers"]) < 3:
                    c["recent_papers"].append({"title": w["title"], "year": w["publication_year"]})
    return cands


def candidates_s2(name, hint=""):
    headers = {"x-api-key": S2_API_KEY} if S2_API_KEY else None
    data = fetch("s2", "https://api.semanticscholar.org/graph/v1/author/search",
                 {"query": name, "limit": 15, "fields": "name,affiliations,paperCount,papers.title,papers.year"},
                 headers=headers, retries=3)
    cands = []
    for r in data.get("data", []):
        papers = sorted((p for p in r.get("papers") or [] if p.get("year")), key=lambda p: -p["year"])[:3]
        cands.append({"provider": "s2", "id": r["authorId"], "name": r["name"],
                      "affiliation": "; ".join(r.get("affiliations") or []), "paper_count": r.get("paperCount"),
                      "recent_papers": [{"title": p["title"], "year": p["year"]} for p in papers]})
    return _rank(cands, name, hint)[:6]


def author_candidates(name, hint=""):
    out, errors = [], []
    for prov, fn in (("openalex", candidates_openalex), ("s2", candidates_s2)):
        if not CFG["sources"].get({"s2": "semantic_scholar"}.get(prov, prov), True):
            continue
        try:
            out += fn(name, hint)
        except ApiError as e:
            log.warning("candidates %s failed: %s", prov, e)
            errors.append(str(e))
    return {"candidates": out, "errors": errors}


# ---------- works per provider ----------

def _rec(**kw):
    base = {"title": "", "abstract": "", "year": None, "pub_date": None, "venue": "", "authors": [], "doi": None,
            "arxiv_id": None, "s2_id": None, "openalex_id": None, "links": {}, "provider": ""}
    base.update(kw)
    return base


def works_openalex(author_id):
    params = {"filter": f"author.id:{author_id},from_publication_date:{cutoff_date().isoformat()}",
              "per-page": 200, "cursor": "*", "select": "id,doi,title,publication_year,publication_date,"
              "abstract_inverted_index,primary_location,locations,authorships,ids,type"}
    if OPENALEX_API_KEY:
        params["api_key"] = OPENALEX_API_KEY
    recs = []
    while True:
        data = fetch("openalex", "https://api.openalex.org/works", params)
        for w in data["results"]:
            if not w.get("title") or w.get("type") in {"peer-review", "erratum", "paratext"}:
                continue
            inv = w.get("abstract_inverted_index") or {}
            abstract = " ".join(word for _, word in sorted((p, k) for k, ps in inv.items() for p in ps))
            arx, pdf, venue_names = None, None, []
            for loc in w.get("locations") or []:
                src = loc.get("source") or {}
                venue_names.append((src.get("display_name") or "", src.get("type")))
                if "arxiv" in (src.get("display_name") or "").lower() or "arxiv.org" in (loc.get("landing_page_url") or ""):
                    arx = arx or arxiv_from(loc.get("landing_page_url"))
                pdf = pdf or loc.get("pdf_url")
            doi = (w.get("doi") or "").replace("https://doi.org/", "") or None
            if doi and "arxiv" in doi.lower():
                arx, doi = arx or arxiv_from(doi), None
            primary = ((w.get("primary_location") or {}).get("source") or {})
            venue = primary.get("display_name") or ""
            if primary.get("type") == "repository":  # prefer a journal/conference location if one exists
                venue = next((n for n, t in venue_names if t in {"journal", "conference"}), venue)
            recs.append(_rec(
                provider="openalex", title=w["title"], abstract=abstract, year=w.get("publication_year"),
                pub_date=w.get("publication_date"), venue=venue, doi=doi, arxiv_id=arx,
                openalex_id=w["id"].rsplit("/", 1)[-1],
                authors=[{"name": a["author"]["display_name"], "openalex_id": (a["author"].get("id") or "").rsplit("/", 1)[-1]}
                         for a in w.get("authorships") or []],
                links={k: v for k, v in {"pdf": pdf, "doi": doi and f"https://doi.org/{doi}"}.items() if v}))
        cursor = data["meta"].get("next_cursor")
        if not cursor or not data["results"]:
            return recs
        params["cursor"] = cursor


def _s2_venue(p):
    pv = p.get("publicationVenue") or {}
    acr = [a for a in pv.get("alternate_names") or [] if re.fullmatch(r"[A-Z][A-Za-z\-]{1,11}", a)]
    return min(acr, key=len) if acr else (p.get("venue") or pv.get("name") or "")


def works_s2(author_id):
    headers = {"x-api-key": S2_API_KEY} if S2_API_KEY else None
    fields = "title,year,venue,publicationVenue,externalIds,abstract,authors,publicationDate,openAccessPdf"
    data = fetch("s2", f"https://api.semanticscholar.org/graph/v1/author/{author_id}/papers",
                 {"fields": fields, "limit": 1000}, headers=headers)
    cut = cutoff_date()
    recs = []
    for p in data.get("data", []):
        d, y = p.get("publicationDate"), p.get("year")
        if (d and d < cut.isoformat()) or (not d and (not y or y < cut.year)) or not p.get("title"):
            continue
        ext = p.get("externalIds") or {}
        arx = ext.get("ArXiv")
        pdf = (p.get("openAccessPdf") or {}).get("url") or None
        recs.append(_rec(
            provider="s2", title=p["title"], abstract=p.get("abstract") or "", year=y, pub_date=d,
            venue=_s2_venue(p), doi=ext.get("DOI") if ext.get("DOI") and "arxiv" not in ext["DOI"].lower() else None,
            arxiv_id=arx, s2_id=p["paperId"],
            authors=[{"name": a["name"], "s2_id": a.get("authorId")} for a in p.get("authors") or []],
            links={k: v for k, v in {"pdf": pdf, "s2": f"https://www.semanticscholar.org/paper/{p['paperId']}"}.items() if v}))
    return recs


def works_dblp(name, known_titles):
    """Pick the DBLP pid whose publication list overlaps our titles (never trust the name alone)."""
    hits = fetch("dblp", "https://dblp.org/search/author/api", {"q": name, "format": "json", "h": 3}, retries=2)
    hits = (hits.get("result", {}).get("hits", {}).get("hit")) or []
    cut = cutoff_date().year
    for h in hits:
        pid = h["info"]["url"].split("/pid/")[-1]
        root = ET.fromstring(fetch("dblp", f"https://dblp.org/pid/{pid}.xml", retries=2, as_json=False))
        recs = []
        for r in root.iter("r"):
            pub = next(iter(r), None)
            if pub is None or int(pub.findtext("year") or 0) < cut:
                continue
            title = re.sub(r"\.$", "", "".join(pub.find("title").itertext()) if pub.find("title") is not None else "")
            venue = pub.findtext("booktitle") or pub.findtext("journal") or ""
            ee = pub.findtext("ee") or ""
            recs.append(_rec(provider="dblp", title=title, year=int(pub.findtext("year")), venue=venue,
                             arxiv_id=arxiv_from(ee) if "arxiv" in ee else None,
                             authors=[{"name": re.sub(r"\s\d{4}$", "", a.text or "")} for a in pub.findall("author")]))
        overlap = sum(norm_title(r["title"]) in known_titles for r in recs)
        if overlap >= min(2, len(known_titles)) and overlap > 0:
            return pid, recs
    return None, []


ATOM = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}


def arxiv_meta(ids):
    out = {}
    for i in range(0, len(ids), 50):
        chunk = ids[i:i + 50]
        xml = fetch("arxiv", "https://export.arxiv.org/api/query",
                    {"id_list": ",".join(chunk), "max_results": len(chunk)}, as_json=False)
        for e in ET.fromstring(xml).findall("a:entry", ATOM):
            aid = arxiv_from(e.findtext("a:id", "", ATOM))
            if aid:
                out[aid] = {"categories": [c.get("term") for c in e.findall("a:category", ATOM)],
                            "abstract": re.sub(r"\s+", " ", e.findtext("a:summary", "", ATOM)).strip()}
    return out


# ---------- merge + upsert ----------

PRIORITY = {"openalex": 0, "s2": 1, "dblp": 2}


def merge(recs):
    """Group provider records by normalized title, folding in records that share an arXiv id / DOI
    (preprint and published version with different titles)."""
    groups: dict[str, list] = {}
    by_id: dict[str, str] = {}
    for r in recs:
        key = norm_title(r["title"])
        if not key:
            continue
        ids = [f"{f}:{r[f].lower()}" for f in ("arxiv_id", "doi") if r[f]]
        key = next((by_id[i] for i in ids if i in by_id), key) if key not in groups else key
        groups.setdefault(key, []).append(r)
        for i in ids:
            by_id.setdefault(i, key)
    out = {}
    for key, rs in groups.items():
        rs.sort(key=lambda r: PRIORITY[r["provider"]])
        m = _rec()
        for r in rs:
            for f in ("title", "year", "pub_date", "doi", "arxiv_id", "s2_id", "openalex_id"):
                m[f] = m[f] or r[f]
            if not m["authors"] and r["authors"]:
                m["authors"] = [dict(a) for a in r["authors"]]
            m["links"] = {**r["links"], **m["links"]}
        # S2 abstracts are cleaner than OpenAlex's reconstructed ones
        m["abstract"] = next((r["abstract"] for r in sorted(rs, key=lambda r: r["provider"] != "s2") if r["abstract"]), "")
        # venue: DBLP acronym > S2 acronym > OpenAlex name; anything arXiv-ish means preprint
        venues = [r["venue"] for r in sorted(rs, key=lambda r: {"dblp": 0, "s2": 1, "openalex": 2}[r["provider"]])]
        m["venue"] = short_venue(next((v for v in venues if not is_preprint_venue(v)), ""))
        s2a = next((r["authors"] for r in rs if r["provider"] == "s2"), [])
        if len(s2a) == len(m["authors"]):
            for a, b in zip(m["authors"], s2a):
                a.setdefault("s2_id", b.get("s2_id"))
        out[key] = m
    return out


def _links(m):
    links = dict(m["links"])
    if m["arxiv_id"]:
        links["arxiv"] = f"https://arxiv.org/abs/{m['arxiv_id']}"
        links.setdefault("pdf", f"https://arxiv.org/pdf/{m['arxiv_id']}")
    return links


def upsert(db, key, m, source_id, run_id):
    """Insert or refresh one paper. Never blanks a field because a provider failed this round.
    Records NEW/ACCEPTED/UPDATED only during weekly runs (run_id set)."""
    p = db.query(Paper).filter_by(norm_title=key).one_or_none()
    for f in ("openalex_id", "s2_id", "arxiv_id", "doi"):  # retitled paper: same ids, new title
        if p is None and m[f]:
            p = db.query(Paper).filter(getattr(Paper, f) == m[f]).first()
    links = _links(m)
    preprint = not m["venue"]
    changes = []
    if p is None:
        p = Paper(norm_title=key, title=m["title"], abstract=m["abstract"], year=m["year"], pub_date=m["pub_date"],
                  venue=m["venue"], is_preprint=preprint, authors=m["authors"], doi=m["doi"], arxiv_id=m["arxiv_id"],
                  s2_id=m["s2_id"], openalex_id=m["openalex_id"], links=links)
        db.add(p)
        db.flush()
        changes.append(("NEW", ""))
    else:
        diff = []
        if key != p.norm_title:
            diff.append("제목")
            p.title, p.norm_title = m["title"], key
        if m["authors"] and [a["name"] for a in m["authors"]] != [a["name"] for a in p.authors or []]:
            diff.append("저자")
            p.authors = m["authors"]
        new_links = {**(p.links or {}), **links}
        if new_links != (p.links or {}):
            diff.append("링크(" + ", ".join(sorted(set(new_links) - set(p.links or {})) or ["변경"]) + ")")
            p.links = new_links
        if p.is_preprint and not preprint:
            changes.append(("ACCEPTED", m["venue"]))
            p.is_preprint, p.venue = False, m["venue"]
        elif m["venue"] and not preprint:
            p.venue = m["venue"]
        for f in ("abstract", "year", "pub_date", "doi", "arxiv_id", "s2_id", "openalex_id"):
            if m[f] and not getattr(p, f):
                setattr(p, f, m[f])
        if diff:
            changes.append(("UPDATED", ", ".join(diff)))
            p.updated_at = now()
    if not db.get(PaperSource, (p.id, source_id)):
        db.add(PaperSource(paper_id=p.id, source_id=source_id))
    if run_id:
        for kind, detail in changes:
            if not db.query(PaperChange).filter_by(run_id=run_id, paper_id=p.id, kind=kind).first():
                db.add(PaperChange(run_id=run_id, paper_id=p.id, source_id=source_id, kind=kind, detail=detail))
    return p, [k for k, _ in changes]


# ---------- pipeline ----------

def collect_source(source_id, run_id=None, progress=lambda msg: None):
    """Collect the 2-year window for one source. Returns (stats, errors). Provider failures are partial, not fatal."""
    from . import keywords  # heavy import (torch) only when collecting

    errors, recs = [], []
    with Session() as db:
        src = db.get(Source, source_id)
        authors = [(a.id, a.name, a.openalex_id, a.s2_id) for a in src.authors]
        src.status, src.status_message = "collecting", "수집 중..."
        db.commit()
    enabled = CFG["sources"]
    for _, name, oa, s2 in authors:
        if oa and enabled.get("openalex"):
            progress(f"OpenAlex: {name}")
            try:
                recs += works_openalex(oa)
            except ApiError as e:
                errors.append(str(e))
        if s2 and enabled.get("semantic_scholar"):
            progress(f"Semantic Scholar: {name}")
            try:
                recs += works_s2(s2)
            except ApiError as e:
                errors.append(str(e))
    known = {norm_title(r["title"]) for r in recs}
    if enabled.get("dblp") and known:
        for aid, name, _, _ in authors:
            progress(f"DBLP: {name}")
            try:
                pid, drecs = works_dblp(name, known)
                recs += drecs
                if pid:
                    with Session() as db:
                        db.get(Author, aid).dblp_pid = pid
                        db.commit()
            except (ApiError, ET.ParseError) as e:
                errors.append(f"dblp: {e}" if isinstance(e, ET.ParseError) else str(e))
                break  # a bot check / outage applies to every author
    merged = merge(recs)
    meta = {}
    if enabled.get("arxiv"):
        ids = sorted({m["arxiv_id"] for m in merged.values() if m["arxiv_id"]})
        if ids:
            progress(f"arXiv: {len(ids)}편 메타데이터")
            try:
                meta = arxiv_meta(ids)
            except (ApiError, ET.ParseError) as e:
                errors.append(f"arxiv: {e}")
        for m in merged.values():
            am = meta.get(m["arxiv_id"]) if m["arxiv_id"] else None
            m["categories"] = am["categories"] if am else []
            if am and not m["abstract"]:
                m["abstract"] = am["abstract"]
    stats = Counter()
    with Session() as db:
        for key, m in merged.items():
            p, kinds = upsert(db, key, m, source_id, run_id)
            if m.get("categories"):
                p.categories = m["categories"]
            stats["papers"] += 1
            stats.update(kinds)
        db.commit()
        todo = [p for p in db.query(Paper).join(PaperSource).filter(PaperSource.source_id == source_id)
                if not p.keywords]
        if todo:
            progress(f"키워드 추출: {len(todo)}편 (KeyBERT, CPU)")
            for p, kws in zip(todo, keywords.extract([f"{p.title}. {p.abstract or ''}" for p in todo])):
                p.keywords = kws
        src = db.get(Source, source_id)
        src.keywords = [k for k, _ in Counter(k for p in db.query(Paper).join(PaperSource)
                                              .filter(PaperSource.source_id == source_id) for k in p.keywords or []).most_common(5)]
        name_tab(src)
        if not merged and errors:
            src.status, src.status_message = "error", "논문을 가져오지 못했습니다: " + " | ".join(errors)
        else:
            src.status = "ready"
            src.status_message = ("일부 API 실패: " + " | ".join(errors)) if errors else ""
            src.last_updated = now()
        db.commit()
    log.info("source %s collected: %s errors=%s", source_id, dict(stats), errors)
    return dict(stats), errors


def name_tab(src):
    """'기관 · 연구실명 · 주력 분야'. LLM once (if available), else heuristic; user/LLM names are never regenerated."""
    if src.name_source in ("user", "llm"):
        return
    affs = Counter(a.affiliation.split("; ")[0] for a in src.authors if a.affiliation)
    inst = affs.most_common(1)[0][0] if affs else ""
    inst_short = acronym(inst) if len(inst) > 20 and len(acronym(inst)) >= 3 else inst
    if llm.available():
        try:
            src.name = llm.tab_name(src.page_title, inst, [a.name for a in src.authors], src.keywords)
            src.name_source = "llm"
            return
        except llm.LLMError as e:
            log.warning("tab name via LLM failed, using heuristic: %s", e)
    lab = re.split(r"\s[\(\|\-–,:]|,", src.page_title or "")[0].strip() or (src.authors[0].name if src.authors else "")
    if inst_short and lab.lower().startswith(inst_short.lower()):
        lab = lab[len(inst_short):].strip()
    src.name = " · ".join(x for x in (inst_short, lab, src.keywords[0] if src.keywords else "") if x)
    src.name_source = "auto"


def weekly_update(trigger="manual", progress=lambda msg: None):
    with Session() as db:
        run = UpdateRun(trigger=trigger)
        db.add(run)
        db.commit()
        run_id = run.id
        sources = [(s.id, s.name) for s in db.query(Source).filter(Source.status.in_(["ready", "error"]))]
    errors = []
    for sid, name in sources:
        progress(f"[{name}] 업데이트 중")
        try:
            _, errs = collect_source(sid, run_id, progress=lambda m, n=name: progress(f"[{n}] {m}"))
            errors += [f"[{name}] {e}" for e in errs]
        except Exception as e:  # one broken source must not stop the others
            log.exception("weekly update failed for source %s", sid)
            errors.append(f"[{name}] {type(e).__name__}: {e}")
    with Session() as db:
        run = db.get(UpdateRun, run_id)
        run.finished_at, run.errors = now(), errors
        run.status = "partial" if errors else "ok"
        db.commit()
    return run_id
