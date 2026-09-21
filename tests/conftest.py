import os
from pathlib import Path
import tempfile

import pytest


# Set this before importing src.logging.db. It protects collection, fixture
# teardown gaps, module reloads, and subprocesses in addition to the per-test
# monkeypatch below. The unconditional assignment prevents a caller's
# environment from accidentally directing tests back to the live database.
_TEST_STORAGE = tempfile.TemporaryDirectory(prefix="autocad-ai-tests-")
_SESSION_DB_PATH = Path(_TEST_STORAGE.name) / "jobs.db"
_LIVE_DB_PATH = Path(__file__).resolve().parents[1] / "jobs.db"
assert _SESSION_DB_PATH.resolve() != _LIVE_DB_PATH.resolve()
os.environ["AUTOCAD_AI_DB_PATH"] = str(_SESSION_DB_PATH)

from src.logging import db


@pytest.fixture(autouse=True)
def isolated_test_storage(tmp_path, tmp_path_factory, monkeypatch):
    """Prevent every test subtree from ever writing live audit or backup data."""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "jobs.db")

    from src import backup

    monkeypatch.setattr(
        backup,
        "BACKUP_ROOT",
        tmp_path_factory.mktemp("test-cad-backups"),
    )
