"""Test environment, set before any app module is imported: throw-away DB, fake LLM endpoint and keys."""
import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="pu-test-")
os.environ.update(
    DB_URL=f"sqlite:///{_tmp}/test.db",
    LLM_BASE_URL="http://llm.invalid",      # never a real gateway
    FACTCHAT_API_KEY="test-secret-key",     # fake values only
    LLM_API_KEY="old-env-key",
    APP_VERSION="sha-test",
)
