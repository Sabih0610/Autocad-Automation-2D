from fastapi import APIRouter, HTTPException

from src.api.routes._revertible import run_revertible
from src.api.schemas import PlaceSymbolRequest


router = APIRouter(prefix="/api", tags=["place-symbol"])


@router.post("/place-symbol")
def place_symbol(request: PlaceSymbolRequest):
    import pythoncom
    from src.ai.symbol_planner import plan_symbol_placement
    from src.use_cases.place_symbol import connect_to_autocad, insert_symbol

    pythoncom.CoInitialize()
    prompt = request.prompt.strip()
    try:
        if not prompt:
            raise HTTPException(status_code=400, detail="Prompt cannot be empty.")

        try:
            planned_spec = plan_symbol_placement(prompt)
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=f"AI planning failed: {type(exc).__name__}: {exc}",
            ) from exc

        try:
            acad, doc = connect_to_autocad()
        except SystemExit as exc:
            raise HTTPException(
                status_code=503,
                detail="AutoCAD is not reachable. Ensure AutoCAD is running with a drawing open.",
            ) from exc

        # `connect_to_autocad` resolves the active document, so the path is
        # only knowable here — but it is knowable *before* the write, which is
        # what a backup needs. A dry run changes nothing, so it gets no
        # changeset.
        document_path = getattr(doc, "FullName", None) if request.execute else None
        insert_result, change_set_id, change_set_skipped_reason = run_revertible(
            document_path,
            f"Place symbol: {prompt}",
            lambda: insert_symbol(
                doc=doc,
                spec=planned_spec,
                dry_run=not request.execute,
            ),
            save=bool(request.execute),
        )

        return {
            "ok": bool(insert_result.get("ok")),
            "prompt": prompt,
            "planned_spec": planned_spec,
            "insert_result": insert_result,
            "connected_to": getattr(acad, "Caption", None),
            "active_drawing": getattr(doc, "Name", None),
            "change_set_id": change_set_id,
            "change_set_skipped_reason": change_set_skipped_reason,
        }
    finally:
        pythoncom.CoUninitialize()
