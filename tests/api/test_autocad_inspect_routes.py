from __future__ import annotations

import sys

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.api.routes import autocad_inspect as inspect_routes
from src.parametric.vessel.dwg_export import AutoCADNotRunningError


FAKE_INSPECTION = {
    "ok": True,
    "document_name": "Drawing10.dwg",
    "dwg_path": "",
    "entity_count_total": 6,
    "entity_count_returned": 6,
    "truncated": False,
    "entities": [
        {
            "index": 0,
            "handle": "268",
            "object_name": "AcDbLine",
            "entity_type": "AcDbLine",
            "layer": "BORDER",
            "color": None,
            "linetype": None,
            "position": None,
            "center": None,
            "radius": None,
            "start_point": [0.0, 0.0, 0.0],
            "end_point": [1000.0, 0.0, 0.0],
            "text": None,
            "bbox": None,
        }
    ],
}


class FakePythoncom:
    def __init__(self):
        self.initialized = 0
        self.uninitialized = 0

    def CoInitialize(self):
        self.initialized += 1

    def CoUninitialize(self):
        self.uninitialized += 1


@pytest.fixture(autouse=True)
def fake_pythoncom(monkeypatch):
    fake_module = FakePythoncom()
    monkeypatch.setitem(sys.modules, "pythoncom", fake_module)
    return fake_module


@pytest.fixture
def client():
    return TestClient(app)


def _patch_inspector(monkeypatch, captured: dict | None = None):
    captured = captured if captured is not None else {}
    captured.setdefault("max_entities", [])

    def fake_inspect(max_entities=500):
        captured["max_entities"].append(max_entities)
        return FAKE_INSPECTION

    def fake_summary(inspection):
        assert inspection == FAKE_INSPECTION
        return "Drawing10.dwg: 6 entities returned."

    monkeypatch.setattr(inspect_routes, "inspect_active_drawing", fake_inspect)
    monkeypatch.setattr(inspect_routes, "summarize_drawing_state", fake_summary)

    return captured


def test_inspect_returns_200_with_fake_inspection(client, monkeypatch) -> None:
    _patch_inspector(monkeypatch)

    response = client.get("/api/autocad/inspect")

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["inspection"] == FAKE_INSPECTION


def test_inspect_response_includes_ok_summary_and_inspection(client, monkeypatch) -> None:
    _patch_inspector(monkeypatch)

    response = client.get("/api/autocad/inspect")

    data = response.json()
    assert "ok" in data
    assert data["summary"] == "Drawing10.dwg: 6 entities returned."
    assert "inspection" in data


def test_max_entities_is_passed_to_inspector(client, monkeypatch) -> None:
    captured = _patch_inspector(monkeypatch)

    response = client.get("/api/autocad/inspect?max_entities=123")

    assert response.status_code == 200
    assert captured["max_entities"] == [123]


def test_invalid_max_entities_zero_returns_validation_error(client, monkeypatch) -> None:
    _patch_inspector(monkeypatch)

    response = client.get("/api/autocad/inspect?max_entities=0")

    assert response.status_code in {400, 422}


def test_invalid_max_entities_too_high_returns_validation_error(client, monkeypatch) -> None:
    _patch_inspector(monkeypatch)

    response = client.get("/api/autocad/inspect?max_entities=3000")

    assert response.status_code in {400, 422}


def test_autocad_not_running_returns_503(client, monkeypatch) -> None:
    def fake_inspect(max_entities=500):
        raise AutoCADNotRunningError("AutoCAD unavailable")

    monkeypatch.setattr(inspect_routes, "inspect_active_drawing", fake_inspect)

    response = client.get("/api/autocad/inspect")

    assert response.status_code == 503
    assert (
        response.json()["detail"]
        == "AutoCAD is not running. Open AutoCAD with a drawing active and try again."
    )


def test_generic_inspection_error_returns_500(client, monkeypatch) -> None:
    def fake_inspect(max_entities=500):
        raise RuntimeError("inspection failed")

    monkeypatch.setattr(inspect_routes, "inspect_active_drawing", fake_inspect)

    response = client.get("/api/autocad/inspect")

    assert response.status_code == 500
    assert "AutoCAD drawing inspection failed" in response.json()["detail"]
    assert "RuntimeError: inspection failed" in response.json()["detail"]


def test_api_main_imports_with_autocad_inspect_router() -> None:
    from src.api.main import app as imported_app

    paths = [
        route.path
        for route in imported_app.routes
        if hasattr(route, "path")
    ]

    assert "/api/autocad/inspect" in paths
