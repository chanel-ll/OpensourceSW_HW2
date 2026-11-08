"""KeyBERT keywords + sentence embeddings on CPU (model cached in ./models).

The same functions are used by the app and by eval/evaluate.py, so evaluation measures exactly what is served.
"""
import logging
import re
import threading

from .settings import CFG, MODEL_DIR

log = logging.getLogger("keywords")
_models: dict = {}
_lock = threading.Lock()

# v2 preprocessing: keep hyphenated terms whole (time-of-flight, super-resolution) and drop
# filler words that otherwise glue onto keyphrases ("appreciation using", "semanticdraw new").
TOKEN_PATTERN = r"(?u)\b\w[\w-]*\w\b"
FILLER = {
    "using", "used", "use", "uses", "based", "new", "novel", "propose", "proposed", "proposes", "paper", "approach",
    "approaches", "method", "methods", "result", "results", "show", "shows", "shown", "present", "presents", "work",
    "study", "task", "tasks", "framework", "model", "models", "problem", "problems", "existing", "effective",
    "efficient", "various", "different", "given", "able", "via", "also", "well", "high", "low", "large", "train",
    "training", "trained", "achieve", "achieves", "demonstrate", "demonstrates", "experiments", "experimental",
    "performance", "state-of-the-art", "art", "state", "significantly", "furthermore", "however", "moreover", "prior",
}


def model_id(cfg=None) -> str:
    """Identifies everything that changes stored keywords/embeddings (model, revision, preprocessing)."""
    k = cfg or CFG["keywords"]
    return f"{k['model']}@{k.get('revision') or 'main'}|{k.get('preprocess', 'basic')}|ng{k.get('ngram_max', 2)}|div{k.get('diversity', 0.5)}"


def load(name: str, revision: str | None = None):
    with _lock:
        key = (name, revision)
        if key not in _models:
            from keybert import KeyBERT
            from sentence_transformers import SentenceTransformer

            snap = MODEL_DIR / ("models--" + name.replace("/", "--")) / "snapshots" / (revision or "")
            cached = bool(revision) and snap.is_dir()  # this exact revision downloaded: never touch the network
            log.info("loading embedding model %s@%s on CPU%s", name, revision, " (cached)" if cached else "")
            _models[key] = KeyBERT(SentenceTransformer(name, revision=revision, device="cpu", cache_folder=str(MODEL_DIR),
                                                       local_files_only=cached))
        return _models[key]


def _kw():
    return load(CFG["keywords"]["model"], CFG["keywords"].get("revision"))


def _vectorizer(cfg):
    from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, CountVectorizer

    ngram = (1, int(cfg.get("ngram_max", 2)))
    if cfg.get("preprocess", "basic") == "basic":  # original behaviour (KeyBERT default tokenizer)
        return CountVectorizer(ngram_range=ngram, stop_words="english")
    return CountVectorizer(ngram_range=ngram, stop_words=sorted(ENGLISH_STOP_WORDS | FILLER), token_pattern=TOKEN_PATTERN)


def _clean(doc: str) -> str:
    return re.sub(r"\s+", " ", doc).strip()


def extract_with(kb, docs: list[str], cfg: dict, top_n: int | None = None) -> list[list[str]]:
    if not docs:
        return []
    docs = [_clean(d) for d in docs]
    res = kb.extract_keywords(docs, vectorizer=_vectorizer(cfg), use_mmr=True, diversity=float(cfg.get("diversity", 0.5)),
                              top_n=top_n or cfg["top_n"])
    if res and isinstance(res[0], tuple):  # KeyBERT returns a flat list for a single doc
        res = [res]
    return [[k for k, _ in r] for r in res]


def embed_with(kb, docs: list[str]):
    """Unit-normalized float32 vectors (cosine similarity == dot product)."""
    import numpy as np

    if not docs:
        return np.zeros((0, 0), dtype=np.float32)
    return kb.model.embedding_model.encode([_clean(d) for d in docs], normalize_embeddings=True,
                                           convert_to_numpy=True).astype(np.float32)


def embed(docs: list[str]):
    return embed_with(_kw(), docs)


def extract(docs: list[str]) -> list[list[str]]:
    return extract_with(_kw(), docs, CFG["keywords"])


if __name__ == "__main__":
    out = extract(["3D Gaussian splatting for real-time novel view synthesis of dynamic scenes.",
                   "Hyperspectral imaging with a compact snapshot camera and deep reconstruction."])
    print(out)
    assert len(out) == 2 and all(1 <= len(k) <= CFG["keywords"]["top_n"] for k in out)
    v = embed(["gaussian splatting for novel view synthesis", "3d gaussian splats rendering", "urinary paraben survey"])
    assert v.ndim == 2 and v.shape[0] == 3 and abs(float(v[0] @ v[0]) - 1) < 1e-3, v.shape
    assert float(v[0] @ v[1]) > float(v[0] @ v[2]) + 0.2  # related texts must embed closer than unrelated ones
    print("model ok:", model_id(), "dim", v.shape[1])
