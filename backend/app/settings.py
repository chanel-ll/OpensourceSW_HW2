"""Load .env (secrets) and config.yaml (personal settings) from the project root."""
import logging
import os
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

DEFAULTS = {
    "contact_email": "",            # OpenAlex/arXiv polite pool (User-Agent mailto)
    "lookback_days": 730,            # "최근 2년"
    "update_interval_days": 7,
    # revision = Hugging Face commit, pinned so every machine/image gets the same weights
    "keywords": {"model": "sentence-transformers/all-MiniLM-L6-v2", "revision": "1110a243fdf4706b3f48f1d95db1a4f5529b4d41",
                 "top_n": 4, "preprocess": "basic", "ngram_max": 2, "diversity": 0.5},
    "sources": {"semantic_scholar": True, "openalex": True, "dblp": True, "arxiv": True},
    "notes_dir": "notes",            # markdown notes; can point at (a folder inside) an Obsidian vault
    "world": {"assign_threshold": 0.3, "candidate_min": 3, "similar_top_k": 3, "similar_min": 0.5},
}


def _load_yaml() -> dict:
    p = ROOT / "config.yaml"
    if not p.exists():
        p = ROOT / "config.example.yaml"
    data = yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else {}
    cfg = {**DEFAULTS, **(data or {})}
    for k in ("keywords", "sources", "world"):
        cfg[k] = {**DEFAULTS[k], **((data or {}).get(k) or {})}
    return cfg


CFG = _load_yaml()

LLM_BASE_URL = os.getenv("LLM_BASE_URL", "").rstrip("/")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-5.4-nano")
S2_API_KEY = os.getenv("S2_API_KEY", "")
OPENALEX_API_KEY = os.getenv("OPENALEX_API_KEY", "")
APP_VERSION = os.getenv("APP_VERSION", "dev")  # image tag baked in at docker build (sha-<commit>)  # without it, OpenAlex shares a small daily budget per IP

for stream in (sys.stdout, sys.stderr):  # Windows cp949 console must not crash on en-dash etc.
    try:
        stream.reconfigure(errors="replace")
    except AttributeError:
        pass

DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
(ROOT / "logs").mkdir(exist_ok=True)
DB_URL = os.getenv("DB_URL", f"sqlite:///{(DATA_DIR / 'research_tracker.db').as_posix()}")
MODEL_DIR = ROOT / "models"
NOTES_DIR = Path(os.getenv("NOTES_DIR") or ROOT / CFG["notes_dir"])

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[logging.FileHandler(ROOT / "logs" / "app.log", encoding="utf-8"), logging.StreamHandler()],
)
for noisy in ("httpx", "httpx2", "httpcore", "huggingface_hub", "sentence_transformers"):
    logging.getLogger(noisy).setLevel(logging.WARNING)
