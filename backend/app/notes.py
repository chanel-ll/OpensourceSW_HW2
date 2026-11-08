"""Markdown notes on disk (Obsidian-compatible). Files are the source of truth, so edits made in Obsidian show up here.

notes/papers/<title>.md               one memo per paper (user-written only; auto info is never written here)
notes/projects/<project>/<note>.md     project notes (private: never sent to the LLM)
notes/.trash/                          deleted project folders / notes are moved here, not erased
"""
import re
import shutil
import time
from pathlib import Path

from .collect import norm_title
from .settings import NOTES_DIR

LINK = re.compile(r"\[\[([^\[\]|#]+)(?:[#|][^\[\]]*)?\]\]")
PAPERS = NOTES_DIR / "papers"
PROJECTS = NOTES_DIR / "projects"
TRASH = NOTES_DIR / ".trash"


def safe_name(name, limit=120):
    """File-system safe on Windows; [[safe name]] still resolves because links are matched by norm_title."""
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", name or "")
    s = re.sub(r"\s+", " ", s).strip().rstrip(". ")[:limit].rstrip(". ")
    return s or "untitled"


def unique_path(folder: Path, stem: str) -> Path:
    p, i = folder / f"{stem}.md", 2
    while p.exists():
        p, i = folder / f"{stem} ({i}).md", i + 1
    return p


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def write(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".md.tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)  # atomic: an autosave crash never leaves a half-written note


def trash(path: Path):
    if path.exists():
        TRASH.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(TRASH / f"{int(time.time())}_{path.name}"))


def links(text: str) -> list[str]:
    """Normalized [[targets]] (alias / heading parts dropped)."""
    return [norm_title(t) for t in LINK.findall(text or "") if norm_title(t)]


def all_notes():
    """Yield (kind, owner_key, path, text). owner_key = paper note file name or project folder name."""
    if PAPERS.exists():
        for f in PAPERS.glob("*.md"):
            yield "paper", f.name, f, read(f)
    if PROJECTS.exists():
        for f in PROJECTS.glob("*/*.md"):
            yield "project", f.parent.name, f, read(f)
