from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException

from src.api.schemas import ConsistencyCheckRequest


router = APIRouter(prefix="/api", tags=["consistency"])


def _output_reference(path: Path | None) -> str | None:
    if path is None:
        return None
    return f"outputs/{path.name}"


def _download_reference(path: Path | None) -> str | None:
    if path is None:
        return None
    return f"/api/download/{path.name}"


@router.post("/consistency-check")
def consistency_check(request: ConsistencyCheckRequest):
    import pythoncom
    from src.ai.consistency_explainer import explain_consistency_mismatches
    from src.use_cases import consistency_check as deterministic
    from src.use_cases import consistency_check_ai as ai_wrapper

    pythoncom.CoInitialize()
    pid_path = Path(request.pid_path)
    try:
        if not pid_path.exists():
            raise HTTPException(
                status_code=404,
                detail=f"P&ID file not found: {pid_path}",
            )

        if request.excel_path.strip():
            excel_path = Path(request.excel_path)
            if not excel_path.exists():
                raise HTTPException(
                    status_code=404,
                    detail=f"Excel file not found: {excel_path}",
                )
        else:
            try:
                excel_path = deterministic.find_latest_line_list_excel()
            except SystemExit as exc:
                raise HTTPException(
                    status_code=404,
                    detail="No clean generated line list Excel file was found in outputs/.",
                ) from exc

        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        base_name = f"consistency_report_{pid_path.stem}_{timestamp}"
        report_path = deterministic.OUTPUT_FOLDER / f"{base_name}.xlsx"

        try:
            pid_rows = deterministic.extract_pid_lines(pid_path)
        except SystemExit as exc:
            raise HTTPException(
                status_code=503,
                detail="Could not extract P&ID data. Ensure AutoCAD is running and the drawing can be opened.",
            ) from exc

        excel_rows = deterministic.read_excel_line_list(excel_path)
        mismatches = deterministic.compare_pid_vs_excel(pid_rows, excel_rows)

        deterministic.write_report(
            report_path=report_path,
            pid_path=pid_path,
            excel_path=excel_path,
            pid_rows=pid_rows,
            excel_rows=excel_rows,
            mismatches=mismatches,
        )

        explanation = None
        json_path = None
        txt_path = None

        if request.use_ai_explanation:
            try:
                explanation = explain_consistency_mismatches(mismatches)
            except Exception as exc:
                raise HTTPException(
                    status_code=502,
                    detail=(
                        "AI explanation failed after the deterministic report was created: "
                        f"{type(exc).__name__}: {exc}"
                    ),
                ) from exc

            json_path, txt_path = ai_wrapper.write_ai_outputs(
                explanation=explanation,
                base_name=base_name,
            )

        return {
            "ok": True,
            "result": "PASS" if not mismatches else "FAIL",
            "pid_path": str(pid_path),
            "excel_path": str(excel_path),
            "pid_rows": len(pid_rows),
            "excel_rows": len(excel_rows),
            "mismatch_count": len(mismatches),
            "mismatches": mismatches,
            "ai_explanation": explanation,
            "report_file": _output_reference(report_path),
            "report_download_url": _download_reference(report_path),
            "ai_explanation_file": _output_reference(json_path),
            "ai_explanation_download_url": _download_reference(json_path),
            "manager_summary_file": _output_reference(txt_path),
            "manager_summary_download_url": _download_reference(txt_path),
        }
    finally:
        pythoncom.CoUninitialize()
