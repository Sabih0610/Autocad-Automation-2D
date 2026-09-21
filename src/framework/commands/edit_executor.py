"""Deterministic executor for validated live edit plans.

This module applies structured edit plans to AutoCAD. It deletes existing
entities by handle and delegates added/replacement geometry to the existing
structured command executor. It does not call AI, expose API routes, or accept
raw AutoCAD script.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.backup import backup_file
from src.cad.session import (
    _same_document_identity,
    _snapshot_open_documents,
    close_document,
    open_document,
    serialized,
    summarize_bookkeeping_warnings,
)
from src.framework.commands.edit_schema import validate_edit_plan
from src.framework.commands.executor import execute_commands_in_document
from src.parametric.vessel.dwg_export import (
    AutoCADNotRunningError,
    _com_retry,
    _get_acad,
)


class EditExecutionError(Exception):
    """Raised when an edit plan cannot be executed."""


def _active_document(acad: Any):
    try:
        doc = _com_retry(lambda: acad.ActiveDocument, "getting active document")
    except Exception as exc:
        raise EditExecutionError("No active AutoCAD document is available.") from exc

    if doc is None:
        raise EditExecutionError("No active AutoCAD document is available.")

    return doc


def _get_document(
    acad: Any,
    target_dwg_path: str | None,
    bookkeeping_warnings: list[str] | None = None,
):
    """Resolve the edit target while preserving ownership across retries."""
    if target_dwg_path is not None:
        open_before_retry = (
            _snapshot_open_documents(acad)
        )

        doc, _attempt_opened_here = _com_retry(
            lambda: open_document(
                acad,
                str(target_dwg_path),
                bookkeeping_warnings=bookkeeping_warnings,
            ),
            f"opening DWG {target_dwg_path}",
        )

        opened_here = not any(
            _same_document_identity(
                doc,
                existing_doc,
            )
            for existing_doc
            in open_before_retry
        )

        return doc, opened_here

    return _active_document(acad), False


def _safe_close_document(
    doc: Any,
    target_dwg_path: str,
    bookkeeping_warnings: list[str] | None = None,
) -> None:
    try:
        close_document(
            doc,
            target_dwg_path,
            bookkeeping_warnings=bookkeeping_warnings,
        )
    except Exception:
        pass


def _safe_get_document_name(doc) -> str | None:
    try:
        return _com_retry(lambda: getattr(doc, "Name", None), "reading document name")
    except Exception:
        return None


def _safe_get_dwg_path(doc) -> str | None:
    try:
        return _com_retry(lambda: getattr(doc, "FullName", None), "reading document path")
    except Exception:
        return None


def _document_path(doc, target_dwg_path: str | None) -> str | None:
    if target_dwg_path:
        return str(Path(target_dwg_path))

    return _safe_get_dwg_path(doc)


def _safe_modelspace_count(msp) -> int | None:
    try:
        return int(_com_retry(lambda: msp.Count, "reading modelspace count"))
    except Exception:
        pass

    try:
        return len(msp)
    except Exception:
        return None


def _activate_regen_zoom(acad, doc) -> tuple[bool, str | None]:
    try:
        _com_retry(lambda: doc.Activate(), "activating document")
        _com_retry(lambda: doc.Regen(1), "regenerating document")
        _com_retry(lambda: acad.ZoomExtents(), "zooming extents")
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"

    return True, None


def _delete_entity_by_handle(doc, handle: str) -> None:
    entity = _com_retry(
        lambda: doc.HandleToObject(handle),
        f"getting entity handle {handle}",
    )
    _com_retry(
        lambda: entity.Delete(),
        f"deleting entity handle {handle}",
    )


def _format_error(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"


def _normalize_add_errors(add_result: dict) -> list[dict]:
    normalized_errors = []

    for error in add_result.get("errors", []) or []:
        if isinstance(error, dict):
            normalized = {"type": "add"}
            normalized.update(error)
            normalized_errors.append(normalized)
        else:
            normalized_errors.append(
                {
                    "type": "add",
                    "error": str(error),
                }
            )

    if add_result.get("ok") is False and not normalized_errors:
        normalized_errors.append(
            {
                "type": "add",
                "error": "Addition command execution failed.",
            }
        )

    return normalized_errors

@serialized
def execute_edit_plan(
    edit_plan: dict,
    target_dwg_path: str | None = None,
    save: bool = True,
    continue_on_error: bool = True,
    zoom_extents: bool = True,
) -> dict:
    """Apply a validated live edit plan to AutoCAD."""
    validation_errors = validate_edit_plan(
        edit_plan
    )

    if validation_errors:
        joined_errors = "\n".join(
            f"- {error}"
            for error in validation_errors
        )

        raise EditExecutionError(
            f"Invalid edit plan:\n"
            f"{joined_errors}"
        )

    acad = _get_acad()

    bookkeeping_warnings: list[str] = []
    result: dict | None = None

    doc, opened_here = _get_document(
        acad,
        target_dwg_path,
        bookkeeping_warnings,
    )

    try:
        msp = _com_retry(
            lambda: doc.ModelSpace,
            "getting model space",
        )

        document_name = (
            _safe_get_document_name(doc)
        )

        dwg_path = _document_path(
            doc,
            target_dwg_path,
        )

        entity_count_before = (
            _safe_modelspace_count(msp)
        )

        backup_path = None
        backup_skipped_reason = None

        if save:
            if (
                dwg_path
                and Path(dwg_path).is_file()
            ):
                backup_path = str(
                    backup_file(
                        Path(dwg_path)
                    )
                )

            elif not dwg_path:
                backup_skipped_reason = (
                    "Backup skipped because the active "
                    "document is unsaved/untitled and "
                    "has no file path."
                )

            else:
                backup_skipped_reason = (
                    "Backup skipped because the drawing "
                    "path is not an existing file: "
                    f"{dwg_path}"
                )

        errors: list[dict[str, Any]] = []

        deleted_count = 0
        delete_handles = (
            edit_plan.get(
                "delete_handles",
                [],
            )
        )

        commands = edit_plan.get(
            "commands",
            [],
        )

        additions_blocked = False

        for handle in delete_handles:
            try:
                _delete_entity_by_handle(
                    doc,
                    handle,
                )

                deleted_count += 1

            except Exception as exc:
                errors.append(
                    {
                        "type": "delete",
                        "handle": handle,
                        "error":
                            _format_error(exc),
                    }
                )

                if not continue_on_error:
                    additions_blocked = True
                    break

        added_executed_count = 0
        added_total_count = len(commands)

        if (
            commands
            and not additions_blocked
        ):
            try:
                add_result = (
                    execute_commands_in_document(
                        commands,
                        doc,
                        continue_on_error=
                            continue_on_error,
                    )
                )

                added_executed_count = int(
                    add_result.get(
                        "executed_count",
                        0,
                    )
                )

                added_total_count = int(
                    add_result.get(
                        "total_count",
                        len(commands),
                    )
                )

                errors.extend(
                    _normalize_add_errors(
                        add_result
                    )
                )

            except Exception as exc:
                errors.append(
                    {
                        "type": "add",
                        "error":
                            _format_error(exc),
                    }
                )

        if save and not errors:
            try:
                _com_retry(
                    lambda: doc.Save(),
                    "saving edited document",
                )
            except Exception as exc:
                errors.append(
                    {
                        "type": "save",
                        "error":
                            _format_error(exc),
                    }
                )

        entity_count_after = (
            _safe_modelspace_count(msp)
        )

        zoom_extents_called = False
        zoom_error = None

        if zoom_extents:
            (
                zoom_extents_called,
                zoom_error,
            ) = _activate_regen_zoom(
                acad,
                doc,
            )

        result = {
            "ok":
                not errors,
            "edit_intent":
                edit_plan.get(
                    "edit_intent"
                ),
            "summary":
                edit_plan.get("summary"),
            "deleted_count":
                deleted_count,
            "delete_count":
                len(delete_handles),
            "added_executed_count":
                added_executed_count,
            "added_total_count":
                added_total_count,
            "errors":
                errors,
            "document_name":
                document_name,
            "dwg_path":
                dwg_path,
            "entity_count_before":
                entity_count_before,
            "entity_count_after":
                entity_count_after,
            "zoom_extents_called":
                zoom_extents_called,
            "zoom_error":
                zoom_error,
            "backup_path":
                backup_path,
            "backup_skipped_reason":
                backup_skipped_reason,
            "session_bookkeeping_skipped_reason":
                None,
        }

    finally:
        if opened_here:
            _safe_close_document(
                doc,
                str(target_dwg_path),
                bookkeeping_warnings,
            )

    if result is None:
        raise EditExecutionError(
            "Edit execution produced no result"
        )

    result[
        "session_bookkeeping_skipped_reason"
    ] = summarize_bookkeeping_warnings(
        bookkeeping_warnings
    )

    return result