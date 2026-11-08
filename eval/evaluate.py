"""Before/after evaluation of the keyword + embedding model (no LLM, CPU only).

Data (downloaded into eval/data/, never committed):
  * KP20k test (memray/kp20k, CC BY-NC-SA 4.0): CS abstracts + author keyphrases -> keyword F1@5
  * arXiv API metadata (CC0): 5 fields x 20 papers, fixed date window       -> kNN field accuracy
Each set: 100 items, fixed split 30 tuning / 70 final. Variants are chosen on tuning only; the final
70 are scored once per variant for the report.

Run from the repo root:  .venv\\Scripts\\python.exe eval\\evaluate.py
"""
import json
import random
import re
import sys
import time
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

import httpx
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app import keywords  # noqa: E402  (same code the app serves)
from app.settings import MODEL_DIR  # noqa: E402

DATA = ROOT / "eval" / "data"
OUT = ROOT / "eval" / "results.json"
KP20K = "https://huggingface.co/datasets/memray/kp20k/resolve/4b619bc005616bb21a040001500f322fc37582e1/test.json"
FIELDS = ["cs.CV", "cs.CL", "cs.RO", "cs.CR", "cs.DB"]
WINDOW = "submittedDate:[202501010000 TO 202503312359]"
SEED = 42
UA = {"User-Agent": "ResearchTracker-eval/0.1"}


# ---------- data ----------

def kp20k():
    f = DATA / "kp20k_100.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    raw = httpx.get(KP20K, headers={**UA, "Range": "bytes=0-3000000"}, follow_redirects=True, timeout=60).text
    rows = []
    for line in raw.splitlines()[:-1]:  # last line may be cut by the range request
        r = json.loads(line)
        kws = [k.strip() for k in r["keywords"].split(";") if k.strip()]
        if len(r["abstract"]) > 300 and len(kws) >= 3:
            rows.append({"title": r["title"], "abstract": r["abstract"], "keywords": kws})
    random.Random(SEED).shuffle(rows)
    rows = rows[:100]
    DATA.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    return rows


def arxiv():
    f = DATA / "arxiv_100.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    ns = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
    rows = []
    for cat in FIELDS:
        q = {"search_query": f"cat:{cat} AND {WINDOW}", "start": 0, "max_results": 60, "sortBy": "submittedDate", "sortOrder": "ascending"}
        xml = httpx.get("https://export.arxiv.org/api/query", params=q, headers=UA, timeout=60).text
        got = []
        for e in ET.fromstring(xml).findall("a:entry", ns):
            prim = e.find("arxiv:primary_category", ns)
            if prim is not None and prim.get("term") == cat:  # primary field only: clean labels
                got.append({"title": re.sub(r"\s+", " ", e.findtext("a:title", "", ns)).strip(),
                            "abstract": re.sub(r"\s+", " ", e.findtext("a:summary", "", ns)).strip(), "label": cat})
        if len(got) < 20:
            raise SystemExit(f"arXiv returned only {len(got)} primary {cat} papers")
        rows += got[:20]
        time.sleep(3.1)  # arXiv API etiquette
    DATA.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    return rows


def split_kw(rows):
    return rows[:30], rows[30:]


def split_cls(rows):  # stratified: 6 tuning / 14 final per field
    tune, final = [], []
    for cat in FIELDS:
        xs = [r for r in rows if r["label"] == cat]
        tune += xs[:6]
        final += xs[6:]
    return tune, final


# ---------- metrics ----------

def norm(p):
    """lowercase, hyphen==space, light plural stemming (networks -> network, queries -> query)."""
    out = []
    for w in re.sub(r"[-_/]", " ", p.lower()).split():
        w = re.sub(r"[^a-z0-9]", "", w)
        if len(w) > 4 and w.endswith("ies"):
            w = w[:-3] + "y"
        elif len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]
        if w:
            out.append(w)
    return " ".join(out)


def f1_at5(preds, golds, present_only):
    ps, rs, fs = [], [], []
    for pred, (gold, text) in zip(preds, golds):
        g = {norm(k) for k in gold}
        if present_only:
            t = " " + norm(text) + " "
            g = {k for k in g if f" {k} " in t}
        if not g:
            continue
        p = [norm(k) for k in pred[:5]]
        hit = len(set(p) & g)
        prec, rec = hit / 5, hit / len(g)
        ps.append(prec)
        rs.append(rec)
        fs.append(0 if hit == 0 else 2 * prec * rec / (prec + rec))
    return {"precision": round(float(np.mean(ps)), 4), "recall": round(float(np.mean(rs)), 4),
            "f1": round(float(np.mean(fs)), 4), "n": len(fs)}


def knn_acc(kb, labelled, query, k=3):
    doc = lambda r: f"{r['title']}. {r['abstract']}"  # noqa: E731
    A, Q = keywords.embed_with(kb, [doc(r) for r in labelled]), keywords.embed_with(kb, [doc(r) for r in query])
    S = Q @ A.T
    correct = 0
    for i, r in enumerate(query):
        top = np.argsort(-S[i])[:k]
        votes = Counter(labelled[j]["label"] for j in top)
        best = max(votes.values())
        pred = next(labelled[j]["label"] for j in top if votes[labelled[j]["label"]] == best)  # tie -> nearest
        correct += pred == r["label"]
    return round(correct / len(query), 4)


def model_mb(name, revision):
    snap = MODEL_DIR / ("models--" + name.replace("/", "--")) / "snapshots" / revision
    return round(sum(p.stat().st_size for p in snap.rglob("*") if p.is_file()) / 1e6, 1) if snap.exists() else None


def score(cfg, kw_rows, cls_labelled, cls_query):
    kb = keywords.load(cfg["model"], cfg["revision"])
    docs = [f"{r['title']}. {r['abstract']}" for r in kw_rows]
    keywords.extract_with(kb, docs[:2], cfg, top_n=5)  # warm-up (exclude model load from timing)
    t = time.perf_counter()
    preds = keywords.extract_with(kb, docs, cfg, top_n=5)
    keywords.embed_with(kb, docs)
    per_paper = (time.perf_counter() - t) / len(docs)
    golds = [(r["keywords"], d) for r, d in zip(kw_rows, docs)]
    return {"keyword_f1@5_present": f1_at5(preds, golds, True), "keyword_f1@5_all": f1_at5(preds, golds, False),
            "knn_field_accuracy": knn_acc(kb, cls_labelled, cls_query),
            "cpu_ms_per_paper": round(per_paper * 1000, 1), "model_mb": model_mb(cfg["model"], cfg["revision"]),
            "examples": [{"title": r["title"][:80], "gold": r["keywords"][:6], "pred": p} for r, p in zip(kw_rows[:3], preds[:3])]}


BASE = {"model": "sentence-transformers/all-MiniLM-L6-v2", "revision": "1110a243fdf4706b3f48f1d95db1a4f5529b4d41",
        "preprocess": "basic", "ngram_max": 2, "diversity": 0.5, "top_n": 5}
CANDIDATES = {
    "BAAI/bge-small-en-v1.5": "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a",
    "sentence-transformers/all-MiniLM-L12-v2": "a50ef00143b4d5391434df20ae11632588ac25be",
}


def tune_value(s):
    return s["keyword_f1@5_present"]["f1"] + s["knn_field_accuracy"]  # equal weight: keywords + grouping


def main():
    kw, cls = kp20k(), arxiv()
    kw_tune, kw_final = split_kw(kw)
    cls_tune, cls_final = split_cls(cls)
    log ={"data": {"kp20k": {"tune": len(kw_tune), "final": len(kw_final), "license": "CC BY-NC-SA 4.0"},
                    "arxiv": {"tune": len(cls_tune), "final": len(cls_final), "fields": FIELDS, "window": WINDOW,
                              "license": "arXiv metadata CC0"}}, "tuning": []}

    def tune_score(cfg):
        kb = keywords.load(cfg["model"], cfg["revision"])
        docs = [f"{r['title']}. {r['abstract']}" for r in kw_tune]
        preds = keywords.extract_with(kb, docs, cfg, top_n=5)
        f1 = f1_at5(preds, [(r["keywords"], d) for r, d in zip(kw_tune, docs)], True)["f1"]
        # kNN on tuning only: each tuning paper predicted from the other 29
        A = keywords.embed_with(kb, [f"{r['title']}. {r['abstract']}" for r in cls_tune])
        S = A @ A.T
        np.fill_diagonal(S, -1)
        acc = np.mean([Counter(cls_tune[j]["label"] for j in np.argsort(-S[i])[:3]).most_common(1)[0][0] == r["label"]
                       for i, r in enumerate(cls_tune)])
        s = {"keyword_f1@5_present": {"f1": round(f1, 4)}, "knn_field_accuracy": round(float(acc), 4)}
        log["tuning"].append({"cfg": {k: cfg[k] for k in ("model", "preprocess", "ngram_max", "diversity")}, **s})
        print("  tune", log["tuning"][-1])
        return s

    print("baseline (tuning)")
    tune_score(BASE)
    # attempt 1: preprocessing only (same model)
    print("attempt 1: preprocessing")
    grid1 = [{**BASE, "preprocess": "v2", "ngram_max": n, "diversity": d} for n in (2, 3) for d in (0.3, 0.5, 0.7)]
    best1 = max(grid1, key=lambda c: tune_value(tune_score(c)))
    # attempt 2: model swap with the attempt-1 preprocessing
    print("attempt 2: model swap")
    grid2 = [{**best1, "model": m, "revision": r} for m, r in CANDIDATES.items()]
    best2 = max(grid2, key=lambda c: tune_value(tune_score(c)))
    by_tune = {json.dumps(e["cfg"], sort_keys=True): e for e in log["tuning"]}
    pick = max([BASE, best1, best2], key=lambda c: tune_value(by_tune[json.dumps({k: c[k] for k in ("model", "preprocess", "ngram_max", "diversity")}, sort_keys=True)]))

    print("final evaluation (70 + 70, scored once per variant)")
    log["final"] = {}
    for name, cfg in (("baseline", BASE), ("attempt1_preprocess", best1), ("attempt2_model", best2)):
        log["final"][name] = {"cfg": cfg, **score(cfg, kw_final, cls_tune, cls_final)}
        f = log["final"][name]
        print(f"  {name}: F1@5(present)={f['keyword_f1@5_present']['f1']} kNN={f['knn_field_accuracy']} "
              f"{f['cpu_ms_per_paper']}ms/paper {f['model_mb']}MB")
    log["selected"] = pick
    OUT.write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    print("selected (by tuning set):", pick["model"], pick["preprocess"], pick["ngram_max"], pick["diversity"])


if __name__ == "__main__":
    main()
