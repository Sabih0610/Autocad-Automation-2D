"""No write route may silently target whichever drawing AutoCAD has focused.

The project path resolves every document by absolute path, and the test suite
enforces it — `fake_cad.Acad.ActiveDocument` raises outright. The older write
routes never got that: they accepted an optional `target_dwg_path` and fell
back to `ActiveDocument`, so a request could land in a drawing the caller
never named and, with save=true, overwrite it.

Using the active document is still allowed. It just has to be asked for.
"""
import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.api.routes import cad3d as cad3d_routes
from src.api.routes import pid as pid_routes
from src.api.routes import sketch as sketch_routes


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def clear_caches():
    for cache in (sketch_routes._token_cache, pid_routes._PID_CACHE, cad3d_routes._CAD3D_CACHE):
        cache.clear()
    yield
    for cache in (sketch_routes._token_cache, pid_routes._PID_CACHE, cad3d_routes._CAD3D_CACHE):
        cache.clear()


def _seed_pid_token(token="tok"):
    pid_routes._PID_CACHE[token] = {
        "command_sequence": {"schema_version": "1.0", "commands": []},
        "component_scene": {"title": "t"},
        "component_count": 0,
        "created_at": pid_routes._now(),
    }
    return token


def _seed_cad3d_token(token="tok"):
    cad3d_routes._CAD3D_CACHE[token] = {
        "scene_data": {"title": "t", "components": []},
        "created_at": cad3d_routes._now(),
        "generation_strategy": "test",
        "example_name": "test",
    }
    return token


def _no_com(monkeypatch):
    """Any COM call reaching through means the guard did not stop the request."""
    def forbidden(*args, **kwargs):
        raise AssertionError("a COM call was attempted despite no explicit target")

    monkeypatch.setattr(sketch_routes, "execute_command_sequence", forbidden)
    monkeypatch.setattr(pid_routes, "execute_command_sequence", forbidden)
    monkeypatch.setattr(cad3d_routes, "execute_cad3d_scene", forbidden)


def test_pid_approve_refuses_without_a_target_or_opt_in(client, monkeypatch):
    _no_com(monkeypatch)
    token = _seed_pid_token()

    response = client.post("/api/pid/approve", json={"token": token})

    assert response.status_code == 400
    assert "target_dwg_path" in response.json()["detail"]
    assert "use_active_document" in response.json()["detail"]


def test_cad3d_approve_refuses_without_a_target_or_opt_in(client, monkeypatch):
    _no_com(monkeypatch)
    token = _seed_cad3d_token()

    response = client.post("/api/cad3d/approve", json={"token": token})

    assert response.status_code == 400


def test_autocad_edit_refuses_without_a_target_or_opt_in(client, monkeypatch):
    response = client.post("/api/autocad/edit", json={"prompt": "delete the title"})

    assert response.status_code == 400
    assert "target_dwg_path" in response.json()["detail"]


def test_the_opt_in_is_honoured(client, monkeypatch):
    """Opting in must actually reach the executor — the guard is a gate, not a
    ban."""
    calls = []
    monkeypatch.setattr(
        pid_routes,
        "execute_command_sequence",
        lambda *a, **k: calls.append(k) or {"ok": True, "executed_count": 0, "total_count": 0, "errors": []},
    )
    token = _seed_pid_token()

    response = client.post(
        "/api/pid/approve", json={"token": token, "use_active_document": True}
    )

    assert response.status_code == 200
    assert len(calls) == 1


def test_an_explicit_empty_target_is_not_treated_as_no_target(client, monkeypatch):
    """An empty string is a caller naming a target badly, not declining to name
    one. It must be forwarded and rejected on its own terms, not folded into
    the "no target given" case."""
    token = _seed_pid_token()
    monkeypatch.setattr(
        pid_routes,
        "execute_command_sequence",
        lambda *a, **k: {"ok": True, "executed_count": 0, "total_count": 0, "errors": []},
    )

    response = client.post(
        "/api/pid/approve", json={"token": token, "target_dwg_path": ""}
    )

    # Whatever happens next, it must not be the "you did not name a target"
    # rejection — that would erase the distinction.
    if response.status_code == 400:
        assert "use_active_document" not in response.json()["detail"]


def test_a_refused_request_does_not_consume_its_token(client, monkeypatch):
    """The guard runs before any work, so a rejected approve must leave the
    token usable once the caller adds a target."""
    _no_com(monkeypatch)
    token = _seed_pid_token()

    assert client.post("/api/pid/approve", json={"token": token}).status_code == 400
    assert token in pid_routes._PID_CACHE
