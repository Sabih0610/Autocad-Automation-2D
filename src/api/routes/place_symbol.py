from fastapi import APIRouter, HTTPException

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

        insert_result = insert_symbol(
            doc=doc,
            spec=planned_spec,
            dry_run=not request.execute,
        )

        return {
            "ok": bool(insert_result.get("ok")),
            "prompt": prompt,
            "planned_spec": planned_spec,
            "insert_result": insert_result,
            "connected_to": getattr(acad, "Caption", None),
            "active_drawing": getattr(doc, "Name", None),
        }
    finally:
        pythoncom.CoUninitialize()
