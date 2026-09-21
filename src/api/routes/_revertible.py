"""Run a live-drawing write inside a file-level changeset.

Shared by every legacy write route (sketch, P&ID, CAD3D, vessel,
place-symbol, autocad/edit, title-block) so they all gain Keep/Revert through
the one mechanism the project route already uses, instead of each carrying its
own token cache and no undo at all.
"""

from __future__ import annotations

from typing import Any, Callable

from fastapi import HTTPException

from src.cad.changes import ChangeManager


def require_explicit_target(target_dwg_path: str | None, use_active_document: bool) -> None:
    """Refuse to write to whatever drawing happens to be focused.

    The project path resolves every document by absolute path, and the test
    suite enforces it — `fake_cad.Acad.ActiveDocument` raises outright. The
    older routes never got that: they accepted an *optional* target and
    silently fell back to `ActiveDocument`, so a request could land in a
    drawing the caller never named, and with `save=true` overwrite it.

    Writing to the active document is still allowed, but it now has to be
    asked for. Raised before any COM call, so nothing is opened or written.
    """
    # `is not None`, not truthiness: an explicitly-sent empty string is a
    # caller naming a target badly, not a caller declining to name one. It
    # gets forwarded and rejected downstream with an error about the path
    # itself, rather than being lumped in with "no target given" — the same
    # distinction the inspector and edit routes already make.
    if target_dwg_path is not None or use_active_document:
        return
    raise HTTPException(
        status_code=400,
        detail=(
            "Refusing to write to whichever drawing AutoCAD currently has focused. "
            "Pass target_dwg_path to name the drawing explicitly, or set "
            "use_active_document=true to accept the active one."
        ),
    )


def run_revertible(
    target_dwg_path: str | None,
    summary: str,
    execute: Callable[[], Any],
    *,
    save: bool,
) -> tuple[Any, str | None, str | None]:
    """Execute `execute`, wrapped in a changeset when one is possible.

    Returns `(result, change_set_id, skipped_reason)`. Exactly one of
    `change_set_id` / `skipped_reason` is set, so a caller can always tell the
    difference between "revertible" and "deliberately not revertible" — and
    never has to infer it from a missing field.

    A changeset needs two things: somewhere to restore from, and something to
    restore. With `save=False` nothing is written to disk, so there is nothing
    to undo. Without an explicit target the write goes to whatever document
    AutoCAD has focused, whose path is not knowable until after the call — too
    late to have taken a backup.
    """
    if not save:
        return execute(), None, "No changeset: save=false, so nothing is written to disk."

    if not target_dwg_path:
        return (
            execute(),
            None,
            "No changeset: no target_dwg_path was given, so the write goes to the "
            "active document and cannot be backed up before it happens.",
        )

    result, change_set_id = ChangeManager().apply_file_edit(
        [target_dwg_path], summary, execute
    )
    return result, change_set_id, None
