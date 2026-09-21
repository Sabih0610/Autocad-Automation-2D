"""The FastAPI app must reconcile multi-file project jobs stranded by a
previous process crash (`src.cad.orchestrator.reconcile_interrupted_jobs`)
once, at startup — before anything could try to execute a job left stuck
at status="running". This only proves the wiring calls the real function;
`reconcile_interrupted_jobs`'s own behavior is tested directly in
tests/project/test_orchestrator.py.
"""
from fastapi.testclient import TestClient

import src.api.main as main_module


def test_app_startup_calls_reconcile_interrupted_jobs(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "src.cad.orchestrator.reconcile_interrupted_jobs",
        lambda: calls.append(True) or [],
    )

    # Using TestClient as a context manager triggers FastAPI's startup
    # (and shutdown) events; a bare TestClient(app) call does not.
    with TestClient(main_module.app):
        pass

    assert calls == [True]
