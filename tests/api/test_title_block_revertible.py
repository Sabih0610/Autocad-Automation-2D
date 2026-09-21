from __future__ import annotations

import sys
from types import SimpleNamespace

from src.api.schemas import (
    TitleBlockUpdateRequest,
)
from src.api.routes import (
    title_block
    as title_block_routes,
)
from src.use_cases import (
    update_title_block
    as use_case,
)


def test_title_block_api_wraps_each_real_write_in_changeset(
    tmp_path,
    monkeypatch,
):
    drawing = (
        tmp_path
        / "drawing_001.dwg"
    )

    drawing.write_bytes(
        b"fake-dwg"
    )

    monkeypatch.setitem(
        sys.modules,
        "pythoncom",
        SimpleNamespace(
            CoInitialize=lambda: None,
            CoUninitialize=lambda: None,
        ),
    )

    monkeypatch.setattr(
        use_case,
        "get_acad",
        lambda: SimpleNamespace(
            Caption="Fake AutoCAD"
        ),
    )

    process_calls = []

    def fake_process_one_file(
        path,
        updates,
        *,
        create_backup=True,
    ):
        process_calls.append(
            {
                "path": path,
                "updates":
                    dict(updates),
                "create_backup":
                    create_backup,
            }
        )

        return {
            "file": path.name,
            "backup": None,
            "blocks_found": 1,
            "changes": 2,
            "status": "ok",
            "error": None,
        }

    monkeypatch.setattr(
        use_case,
        "process_one_file",
        fake_process_one_file,
    )

    revertible_calls = []

    def fake_run_revertible(
        target_dwg_path,
        summary,
        execute,
        *,
        save,
    ):
        revertible_calls.append(
            {
                "target_dwg_path":
                    target_dwg_path,
                "summary":
                    summary,
                "save":
                    save,
            }
        )

        return (
            execute(),
            "cs-title-001",
            None,
        )

    monkeypatch.setattr(
        title_block_routes,
        "run_revertible",
        fake_run_revertible,
    )

    response = (
        title_block_routes
        .title_block_update(
            TitleBlockUpdateRequest(
                drawings_folder=
                    str(tmp_path),
                file_pattern=
                    "drawing_*.dwg",
                title_block_name=
                    "TITLE_BLOCK_TEST",
                updates={
                    "REV": "G",
                    "DATE":
                        "2026-09-21",
                },
                dry_run=False,
            )
        )
    )

    assert response["ok"] is True
    assert (
        response["summary"]["ok"]
        == 1
    )

    assert revertible_calls == [
        {
            "target_dwg_path":
                str(drawing),
            "summary":
                (
                    "Update title block "
                    "TITLE_BLOCK_TEST "
                    "in drawing_001.dwg"
                ),
            "save": True,
        }
    ]

    assert len(process_calls) == 1

    assert (
        process_calls[0][
            "create_backup"
        ]
        is False
    )

    file_result = (
        response["files"][0]
    )

    assert (
        file_result[
            "change_set_id"
        ]
        == "cs-title-001"
    )

    assert (
        file_result[
            "change_set_skipped_reason"
        ]
        is None
    )


def test_title_block_dry_run_reports_changeset_skip(
    tmp_path,
    monkeypatch,
):
    drawing = (
        tmp_path
        / "drawing_001.dwg"
    )

    drawing.write_bytes(
        b"fake-dwg"
    )

    monkeypatch.setitem(
        sys.modules,
        "pythoncom",
        SimpleNamespace(
            CoInitialize=lambda: None,
            CoUninitialize=lambda: None,
        ),
    )

    monkeypatch.setattr(
        use_case,
        "get_acad",
        lambda: SimpleNamespace(
            Caption="Fake AutoCAD"
        ),
    )

    def fake_process_one_file(
        path,
        updates,
        *,
        create_backup=True,
    ):
        return {
            "file": path.name,
            "backup": None,
            "blocks_found": 1,
            "changes": 2,
            "status": "dry_run",
            "error": None,
        }

    monkeypatch.setattr(
        use_case,
        "process_one_file",
        fake_process_one_file,
    )

    calls = []

    def fake_run_revertible(
        target_dwg_path,
        summary,
        execute,
        *,
        save,
    ):
        calls.append(save)

        return (
            execute(),
            None,
            (
                "No changeset: "
                "save=false, so nothing "
                "is written to disk."
            ),
        )

    monkeypatch.setattr(
        title_block_routes,
        "run_revertible",
        fake_run_revertible,
    )

    response = (
        title_block_routes
        .title_block_update(
            TitleBlockUpdateRequest(
                drawings_folder=
                    str(tmp_path),
                file_pattern=
                    "drawing_*.dwg",
                dry_run=True,
            )
        )
    )

    assert calls == [False]

    assert (
        response["files"][0][
            "change_set_id"
        ]
        is None
    )

    assert (
        "save=false"
        in response["files"][0][
            "change_set_skipped_reason"
        ]
    )
