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
    "keywords": {"model": "sentence-transformers/all-MiniLM-L6-v2", "top_n": 4},
    "sources": {"semantic_scholar": True, "openalex": True, "dblp": True, "arxiv": True},
}


def _load_yaml() -> dict:
    p = ROOT / "config.yaml"
    if not p.exists():
        p = ROOT / "config.example.yaml"
    data = yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else {}
    cfg = {**DEFAULTS, **(data or {})}
    for k in ("keywords", "sources"):
        cfg[k] = {**DEFAULTS[k], **((data or {}).get(k) or {})}
    return cfg


CFG = _load_yaml()

LLM_BASE_URL = os.getenv("LLM_BASE_URL", "").rstrip("/")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-5.4-nano")
S2_API_KEY = os.getenv("S2_API_KEY", "")
OPENALEX_API_KEY = os.getenv("OPENALEX_API_KEY", "")  # without it, OpenAlex shares a small daily budget per IP

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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[logging.FileHandler(ROOT / "logs" / "app.log", encoding="utf-8"), logging.StreamHandler()],
)
for noisy in ("httpx", "httpx2", "httpcore", "huggingface_hub", "sentence_transformers"):
    logging.getLogger(noisy).setLevel(logging.WARNING)
