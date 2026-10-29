"""KeyBERT keywords on CPU with a small sentence-embedding model (cached in ./models)."""
import logging
import threading

from .settings import CFG, MODEL_DIR

log = logging.getLogger("keywords")
_model = None
_lock = threading.Lock()


def _kw():
    global _model
    with _lock:
        if _model is None:
            import os

            if (MODEL_DIR / ("models--" + CFG["keywords"]["model"].replace("/", "--"))).exists():
                os.environ.setdefault("HF_HUB_OFFLINE", "1")  # already downloaded: no network on load
            from keybert import KeyBERT
            from sentence_transformers import SentenceTransformer

            name = CFG["keywords"]["model"]
            log.info("loading embedding model %s on CPU", name)
            _model = KeyBERT(SentenceTransformer(name, device="cpu", cache_folder=str(MODEL_DIR)))
        return _model


def extract(docs: list[str]) -> list[list[str]]:
    if not docs:
        return []
    res = _kw().extract_keywords(docs, keyphrase_ngram_range=(1, 2), stop_words="english",
                                 use_mmr=True, diversity=0.5, top_n=CFG["keywords"]["top_n"])
    if docs and res and isinstance(res[0], tuple):  # KeyBERT returns a flat list for a single doc
        res = [res]
    return [[k for k, _ in r] for r in res]


if __name__ == "__main__":
    out = extract(["3D Gaussian splatting for real-time novel view synthesis of dynamic scenes.",
                   "Hyperspectral imaging with a compact snapshot camera and deep reconstruction."])
    print(out)
    assert len(out) == 2 and all(1 <= len(k) <= CFG["keywords"]["top_n"] for k in out)
