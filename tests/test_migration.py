"""Deployment review D5: a model migration that fails half-way must not leave papers without keywords/embeddings
(the old container keeps serving them from the same DB)."""
import sys
import types

import pytest

from app import collect
from app.models import AppMeta, Paper, Session


def test_failed_migration_keeps_old_keywords_and_embeddings(monkeypatch):
    stub = types.SimpleNamespace(model_id=lambda: "new-kw-model",
                                 extract=lambda docs: [["k"] for _ in docs],
                                 embed=lambda docs: (_ for _ in ()).throw(RuntimeError("model crashed")))
    monkeypatch.setitem(sys.modules, "app.keywords", stub)
    with Session() as db:
        p = Paper(norm_title="migration test paper", title="Migration Test Paper", abstract="a", authors=[], links={},
                  keywords=["old kw"], embedding=b"old-vector")
        db.add(p)
        db.merge(AppMeta(key="embedding_model", value="old-model"))
        db.merge(AppMeta(key="keyword_model", value="old-kw-model"))
        db.commit()
        pid = p.id
    with pytest.raises(RuntimeError):
        collect.migrate_models()
    with Session() as db:
        p = db.get(Paper, pid)
        assert p.keywords == ["old kw"] and p.embedding == b"old-vector"
