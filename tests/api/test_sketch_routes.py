from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.api.routes import sketch as sketch_routes
from src.parametric.vessel.dwg_export import AutoCADNotRunningError


FAKE_COMMAND_SEQUENCE = {
    "schema_version": "1.0",
    "summary": "Simple rectangle",
    "estimated_drawing_type": "test",
    "assumptions": ["Draft-quality test."],
    "commands": [
        {"command": "LAYER", "layer_name": "TEST"},
        {"command": "LINE", "from": [0, 0], "to": [100, 0], "layer": "TEST"},
    ],
}

FAKE_VERIFIER_RESULT = {
    "schema_version": "1.0",
    "verdict": "APPROVE",
    "summary": "The command sequence appears internally consistent.",
    "issues": [],
    "command_annotations": [],
}


FAKE_ORCHESTRATED_RESULT = {
    "ok": True,
    "command_sequence": FAKE_COMMAND_SEQUENCE,
    "verifier_result": FAKE_VERIFIER_RESULT,
    "verifier_verdict": "APPROVE",
    "repair_attempts_used": 1,
    "repair_history": [
        {
            "reason": "schema_validation_failed",
            "errors": ["commands.0.to is required"],
            "verdict": None,
        }
    ],
}


FAKE_CHUNKED_RESULT = {
    "ok": True,
    "task_plan": {
        "schema_version": "1.0",
        "drawing_type": "P&ID-style sketch",
        "summary": "Central vessel with piping.",
        "assumptions": ["Draft layout."],
        "chunks": [
            {
                "chunk_id": "equipment",
                "title": "Equipment",
                "goal": "Draw vessel.",
                "priority": 1,
                "expected_elements": ["vessel"],
            }
        ],
    },
    "command_sequence": FAKE_COMMAND_SEQUENCE,
    "verifier_result": FAKE_VERIFIER_RESULT,
    "verifier_verdict": "APPROVE",
    "chunk_count": 1,
    "chunk_results": [],
    "chunk_repair_attempts_used": 0,
    "final_repair_attempts_used": 0,
    "repair_history": [],
}


@pytest.fixture(autouse=True)
def clear_sketch_token_cache():
    sketch_routes._token_cache.clear()
    yield
    sketch_routes._token_cache.clear()


@pytest.fixture
def client():
    return TestClient(app)


def _patch_generate_stack(monkeypatch, captured: dict | None = None):
    captured = captured if captured is not None else {}
    captured.setdefault("generate_calls", [])
    captured.setdefault("orchestrator_calls", [])
    captured.setdefault("chunked_orchestrator_calls", [])
    captured.setdefault("preview_calls", [])

    def fake_generate(prompt):
        captured["generate_calls"].append(prompt)
        return FAKE_COMMAND_SEQUENCE

    def fake_orchestrate(
        prompt,
        max_repair_attempts=2,
        repair_on_approve_with_notes=False,
    ):
        captured["orchestrator_calls"].append(
            {
                "prompt": prompt,
                "max_repair_attempts": max_repair_attempts,
                "repair_on_approve_with_notes": repair_on_approve_with_notes,
            }
        )
        return FAKE_ORCHESTRATED_RESULT

    def fake_chunked_orchestrate(
        prompt,
        max_chunks=6,
        max_repair_attempts_per_chunk=1,
        final_repair_attempts=1,
        repair_on_approve_with_notes=False,
    ):
        captured["chunked_orchestrator_calls"].append(
            {
                "prompt": prompt,
                "max_chunks": max_chunks,
                "max_repair_attempts_per_chunk": max_repair_attempts_per_chunk,
                "final_repair_attempts": final_repair_attempts,
                "repair_on_approve_with_notes": repair_on_approve_with_notes,
            }
        )
        return FAKE_CHUNKED_RESULT

    def fake_preview(command_sequence, output_path):
        captured["preview_calls"].append((command_sequence, output_path))
        return output_path

    monkeypatch.setattr(sketch_routes, "generate_commands", fake_generate)
    monkeypatch.setattr(sketch_routes, "generate_verified_command_sequence", fake_orchestrate)
    monkeypatch.setattr(sketch_routes, "generate_chunked_verified_command_sequence", fake_chunked_orchestrate)
    monkeypatch.setattr(sketch_routes, "render_preview_sequence", fake_preview)

    return captured


def _patch_executor(monkeypatch, captured: dict | None = None, error: Exception | None = None):
    captured = captured if captured is not None else {}
    captured.setdefault("execute_calls", [])

    def fake_execute(command_sequence, target_dwg_path=None, save=True):
        captured["execute_calls"].append(
            {
                "command_sequence": command_sequence,
                "target_dwg_path": target_dwg_path,
                "save": save,
            }
        )

        if error is not None:
            raise error

        return {
            "ok": True,
            "executed_count": 2,
            "total_count": 2,
            "errors": [],
            "dwg_path": target_dwg_path,
        }

    monkeypatch.setattr(sketch_routes, "execute_command_sequence", fake_execute)

    return captured


def _generate(client, monkeypatch, payload: dict | None = None, captured: dict | None = None):
    captured = _patch_generate_stack(monkeypatch, captured)
    response = client.post(
        "/api/sketch/generate",
        json=payload or {"prompt": "draw a rectangle"},
    )
    return response, captured


def _complex_prompt() -> str:
    return (
        "Draw a P&ID-style layout with one central vessel, one top header, "
        "two branches, two gate valves, two instrument bubbles, inlet, outlet, "
        "and clean schematic layout."
    )


def test_looks_complex_prompt_returns_false_for_simple_rectangle() -> None:
    assert sketch_routes._looks_complex_prompt("Draw a rectangle 1000 by 500.") is False


def test_looks_complex_prompt_returns_true_for_pid_prompt() -> None:
    assert sketch_routes._looks_complex_prompt(_complex_prompt()) is True


def test_generate_with_valid_prompt_returns_200_and_token(client, monkeypatch) -> None:
    response, _captured = _generate(client, monkeypatch)

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["token"]


def test_generate_response_includes_summary_verifier_and_counts(client, monkeypatch) -> None:
    response, _captured = _generate(client, monkeypatch)

    data = response.json()
    assert data["summary"] == "Simple rectangle"
    assert data["assumptions"] == ["Draft-quality test."]
    assert data["command_count"] == 2
    assert data["verifier_result"] == FAKE_VERIFIER_RESULT
    assert data["verifier_verdict"] == "APPROVE"


def test_generate_run_verifier_true_calls_orchestrator(client, monkeypatch) -> None:
    response, captured = _generate(client, monkeypatch)

    assert response.status_code == 200
    assert captured["orchestrator_calls"] == [
        {
            "prompt": "draw a rectangle",
            "max_repair_attempts": 2,
            "repair_on_approve_with_notes": False,
        }
    ]
    assert captured["generate_calls"] == []
    assert captured["chunked_orchestrator_calls"] == []


def test_generate_response_includes_repair_metadata(client, monkeypatch) -> None:
    response, _captured = _generate(client, monkeypatch)

    data = response.json()
    assert response.status_code == 200
    assert data["repair_attempts_used"] == 1
    assert data["repair_history"] == FAKE_ORCHESTRATED_RESULT["repair_history"]
    assert data["generation_strategy"] == "normal"


def test_generate_complex_prompt_uses_chunked_orchestrator(client, monkeypatch) -> None:
    response, captured = _generate(
        client,
        monkeypatch,
        payload={"prompt": _complex_prompt()},
    )

    assert response.status_code == 200
    assert captured["orchestrator_calls"] == []
    assert captured["chunked_orchestrator_calls"] == [
        {
            "prompt": _complex_prompt(),
            "max_chunks": 6,
            "max_repair_attempts_per_chunk": 1,
            "final_repair_attempts": 1,
            "repair_on_approve_with_notes": False,
        }
    ]


def test_complex_generate_response_includes_chunked_strategy_and_task_plan(client, monkeypatch) -> None:
    response, _captured = _generate(
        client,
        monkeypatch,
        payload={"prompt": _complex_prompt()},
    )

    data = response.json()
    assert response.status_code == 200
    assert data["generation_strategy"] == "chunked"
    assert data["task_plan"] == FAKE_CHUNKED_RESULT["task_plan"]
    assert data["chunk_count"] == 1
    assert data["chunk_repair_attempts_used"] == 0
    assert data["repair_attempts_used"] == 0


def test_generate_with_empty_prompt_returns_400(client, monkeypatch) -> None:
    _patch_generate_stack(monkeypatch)

    response = client.post("/api/sketch/generate", json={"prompt": "   "})

    assert response.status_code == 400


def test_generate_run_verifier_false_skips_orchestrator_and_uses_generate_commands(client, monkeypatch) -> None:
    response, captured = _generate(
        client,
        monkeypatch,
        payload={"prompt": "draw a rectangle", "run_verifier": False},
    )

    data = response.json()
    assert response.status_code == 200
    assert captured["orchestrator_calls"] == []
    assert captured["chunked_orchestrator_calls"] == []
    assert captured["generate_calls"] == ["draw a rectangle"]
    assert data["verifier_result"] is None
    assert data["verifier_verdict"] is None
    assert data["repair_attempts_used"] == 0
    assert data["repair_history"] == []
    assert data["generation_strategy"] == "direct"
    assert data["chunk_count"] is None
    assert data["chunk_repair_attempts_used"] is None
    assert data["task_plan"] is None


def test_generate_orchestration_error_returns_502(client, monkeypatch) -> None:
    _patch_generate_stack(monkeypatch)

    def fake_orchestrate(
        prompt,
        max_repair_attempts=2,
        repair_on_approve_with_notes=False,
    ):
        raise sketch_routes.CommandOrchestrationError("repair attempts exhausted")

    monkeypatch.setattr(sketch_routes, "generate_verified_command_sequence", fake_orchestrate)

    response = client.post("/api/sketch/generate", json={"prompt": "draw a rectangle"})

    assert response.status_code == 502
    assert response.json()["detail"].startswith("Command orchestration failed:")


def test_generate_chunked_orchestration_error_returns_502(client, monkeypatch) -> None:
    _patch_generate_stack(monkeypatch)

    def fake_chunked_orchestrate(
        prompt,
        max_chunks=6,
        max_repair_attempts_per_chunk=1,
        final_repair_attempts=1,
        repair_on_approve_with_notes=False,
    ):
        raise sketch_routes.ChunkedCommandOrchestrationError("chunked repair failed")

    monkeypatch.setattr(
        sketch_routes,
        "generate_chunked_verified_command_sequence",
        fake_chunked_orchestrate,
    )

    response = client.post("/api/sketch/generate", json={"prompt": _complex_prompt()})

    assert response.status_code == 502
    assert response.json()["detail"].startswith("Chunked command orchestration failed:")


def test_generate_create_preview_false_skips_preview(client, monkeypatch) -> None:
    response, captured = _generate(
        client,
        monkeypatch,
        payload={"prompt": "draw a rectangle", "create_preview": False},
    )

    data = response.json()
    assert response.status_code == 200
    assert captured["preview_calls"] == []
    assert data["preview_download_url"] is None


def test_generate_preview_enabled_calls_renderer_and_returns_download_url(client, monkeypatch) -> None:
    response, captured = _generate(client, monkeypatch)

    data = response.json()
    assert response.status_code == 200
    assert len(captured["preview_calls"]) == 1
    assert captured["preview_calls"][0][0] == FAKE_COMMAND_SEQUENCE
    assert data["preview_download_url"].startswith("/api/download/previews/")
    assert data["preview_download_url"].endswith(".dxf")


def test_preview_generation_works_with_chunked_command_sequence(client, monkeypatch) -> None:
    response, captured = _generate(
        client,
        monkeypatch,
        payload={"prompt": _complex_prompt()},
    )

    data = response.json()
    assert response.status_code == 200
    assert data["generation_strategy"] == "chunked"
    assert len(captured["preview_calls"]) == 1
    assert captured["preview_calls"][0][0] == FAKE_COMMAND_SEQUENCE
    assert data["preview_download_url"].startswith("/api/download/previews/")


def test_approve_with_valid_token_calls_executor_and_returns_result(client, monkeypatch) -> None:
    response, captured = _generate(client, monkeypatch)
    token = response.json()["token"]
    _patch_executor(monkeypatch, captured)

    approve_response = client.post("/api/sketch/approve", json={"token": token, "use_active_document": True})

    data = approve_response.json()
    assert approve_response.status_code == 200
    assert data["ok"] is True
    assert data["execution_result"]["executed_count"] == 2
    assert len(captured["execute_calls"]) == 1


def test_token_cache_stores_orchestrated_command_sequence_and_approve_executes_it(client, monkeypatch) -> None:
    response, captured = _generate(client, monkeypatch)
    token = response.json()["token"]

    assert sketch_routes._token_cache[token]["command_sequence"] == FAKE_COMMAND_SEQUENCE
    assert sketch_routes._token_cache[token]["repair_attempts_used"] == 1
    assert sketch_routes._token_cache[token]["repair_history"] == FAKE_ORCHESTRATED_RESULT["repair_history"]

    _patch_executor(monkeypatch, captured)
    approve_response = client.post("/api/sketch/approve", json={"token": token, "use_active_document": True})

    assert approve_response.status_code == 200
    assert captured["execute_calls"][0]["command_sequence"] == FAKE_COMMAND_SEQUENCE


def test_approve_with_unknown_token_returns_404(client, monkeypatch) -> None:
    _patch_executor(monkeypatch)

    response = client.post("/api/sketch/approve", json={"token": "missing", "use_active_document": True})

    assert response.status_code == 404


def test_approve_passes_save_false_to_executor(client, monkeypatch) -> None:
    response, captured = _generate(client, monkeypatch)
    token = response.json()["token"]
    _patch_executor(monkeypatch, captured)

    approve_response = client.post(
        "/api/sketch/approve",
        json={"token": token, "save": False, "use_active_document": True},
    )

    assert approve_response.status_code == 200
    assert captured["execute_calls"][0]["save"] is False


def test_approve_passes_target_dwg_path_to_executor(client, monkeypatch, tmp_path) -> None:
    response, captured = _generate(client, monkeypatch)
    token = response.json()["token"]
    _patch_executor(monkeypatch, captured)

    # A real file: an approve with save=true now wraps the write in a
    # file-level changeset, which has to back the drawing up first and so
    # cannot accept a path that does not exist.
    target = tmp_path / "test.dwg"
    target.write_bytes(b"")

    approve_response = client.post(
        "/api/sketch/approve",
        json={
            "token": token,
            "target_dwg_path": str(target),
        },
    )

    assert approve_response.status_code == 200
    assert captured["execute_calls"][0]["target_dwg_path"] == str(target)
    assert approve_response.json()["change_set_id"]


def test_autocad_not_running_returns_503_and_keeps_token_for_retry(client, monkeypatch) -> None:
    response, captured = _generate(client, monkeypatch)
    token = response.json()["token"]
    _patch_executor(monkeypatch, captured, error=AutoCADNotRunningError("AutoCAD missing"))

    first_approve = client.post("/api/sketch/approve", json={"token": token, "use_active_document": True})

    assert first_approve.status_code == 503
    assert token in sketch_routes._token_cache

    _patch_executor(monkeypatch, captured, error=None)
    second_approve = client.post("/api/sketch/approve", json={"token": token, "use_active_document": True})

    assert second_approve.status_code == 200
    assert second_approve.json()["ok"] is True


def test_api_main_imports_with_new_router() -> None:
    from src.api.main import app as imported_app

    paths = [
        route.path
        for route in imported_app.routes
        if hasattr(route, "path")
    ]

    assert "/api/sketch/generate" in paths
    assert "/api/sketch/approve" in paths


def test_existing_route_imports_still_work() -> None:
    from src.api.routes.consistency import router as consistency_router
    from src.api.routes.line_list import router as line_list_router
    from src.api.routes.place_symbol import router as place_symbol_router
    from src.api.routes.title_block import router as title_block_router
    from src.api.routes.vessel import router as vessel_router

    assert consistency_router is not None
    assert line_list_router is not None
    assert place_symbol_router is not None
    assert title_block_router is not None
    assert vessel_router is not None
