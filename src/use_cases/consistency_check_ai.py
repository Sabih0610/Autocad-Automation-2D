"""
Phase 6 — Consistency Checker with AI Explanation.

This combines:
1. Deterministic P&ID vs Excel comparison
2. Excel mismatch report
3. AI-generated plain-English explanation

Important:
- The deterministic checker remains the source of truth.
- AI does NOT decide whether something matches.
- AI only explains the mismatches already found by code.

Run clean/latest line list:
    python -m src.use_cases.consistency_check_ai

Run against mismatch test file:
    python -m src.use_cases.consistency_check_ai --excel "E:\\RC-Projects\\autocad-ai\\outputs\\line_list_pid_001_MISMATCH_TEST_2026-04-27_21-02-18.xlsx"

AutoCAD must be running.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from pprint import pprint

from src.ai.consistency_explainer import explain_consistency_mismatches
from src.logging.decorators import log_job
from src.use_cases.consistency_check import (
    DEFAULT_PID_DWG,
    OUTPUT_FOLDER,
    compare_pid_vs_excel,
    extract_pid_lines,
    find_latest_line_list_excel,
    read_excel_line_list,
    write_report,
)


def write_ai_outputs(
    explanation: dict,
    base_name: str,
) -> tuple[Path, Path]:
    """
    Write AI explanation as JSON and manager-friendly TXT.
    """
    OUTPUT_FOLDER.mkdir(parents=True, exist_ok=True)

    json_path = OUTPUT_FOLDER / f"{base_name}_ai_explanation.json"
    txt_path = OUTPUT_FOLDER / f"{base_name}_manager_summary.txt"

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(explanation, f, indent=2)

    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("AI Consistency Check Explanation\n")
        f.write("=" * 40)
        f.write("\n\n")

        f.write(f"Overall Status: {explanation.get('overall_status')}\n")
        f.write(f"Issue Count: {explanation.get('issue_count')}\n\n")

        f.write("Summary:\n")
        f.write(str(explanation.get("summary", "")))
        f.write("\n\n")

        issues = explanation.get("issues", [])

        if issues:
            f.write("Issues:\n")
            for index, issue in enumerate(issues, start=1):
                f.write(f"\n{index}. Line: {issue.get('line_no')}\n")
                f.write(f"   Field: {issue.get('field')}\n")
                f.write(f"   Problem: {issue.get('problem')}\n")
                f.write(f"   Likely impact: {issue.get('likely_impact')}\n")
                f.write(f"   Recommended action: {issue.get('recommended_action')}\n")
        else:
            f.write("Issues:\n")
            f.write("No issues found.\n")

        f.write("\n\nManager Message:\n")
        f.write(str(explanation.get("manager_message", "")))
        f.write("\n")

    return json_path, txt_path


@log_job("consistency_check_ai")
def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--pid",
        type=str,
        default=str(DEFAULT_PID_DWG),
        help="Path to P&ID DWG file.",
    )

    parser.add_argument(
        "--excel",
        type=str,
        default="",
        help="Path to line list Excel file. If omitted, latest generated line list is used.",
    )

    parser.add_argument(
        "--report",
        type=str,
        default="",
        help="Output Excel report path. If omitted, timestamped report is written to outputs/.",
    )

    args = parser.parse_args()

    pid_path = Path(args.pid)

    if args.excel.strip():
        excel_path = Path(args.excel)
    else:
        excel_path = find_latest_line_list_excel()

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    base_name = f"consistency_report_pid_001_{timestamp}"

    if args.report.strip():
        report_path = Path(args.report)
    else:
        report_path = OUTPUT_FOLDER / f"{base_name}.xlsx"

    print("=" * 80)
    print("PHASE 6 CONSISTENCY CHECK WITH AI EXPLANATION")
    print("=" * 80)

    print("\nStep 1: Extracting P&ID lines...")
    pid_rows = extract_pid_lines(pid_path)

    print("\nStep 2: Reading Excel line list...")
    excel_rows = read_excel_line_list(excel_path)

    print("\nStep 3: Comparing deterministic data...")
    mismatches = compare_pid_vs_excel(pid_rows, excel_rows)

    print("\nComparison summary:")
    print(f"  P&ID rows:       {len(pid_rows)}")
    print(f"  Excel rows:      {len(excel_rows)}")
    print(f"  Mismatches:      {len(mismatches)}")

    if mismatches:
        print("\nMismatches found:")
        for item in mismatches:
            print(
                f"  - {item['type']} | line={item['line_no']} | "
                f"field={item['field']} | P&ID={item['pid_value']!r} | "
                f"Excel={item['excel_value']!r}"
            )
    else:
        print("\nNo mismatches found.")

    print("\nStep 4: Writing deterministic Excel report...")
    write_report(
        report_path=report_path,
        pid_path=pid_path,
        excel_path=excel_path,
        pid_rows=pid_rows,
        excel_rows=excel_rows,
        mismatches=mismatches,
    )

    print(f"Excel report written to: {report_path}")

    print("\nStep 5: Generating AI explanation...")
    try:
        explanation = explain_consistency_mismatches(mismatches)
    except Exception as e:
        print("ERROR: AI explanation failed.")
        print(f"Details: {type(e).__name__}: {e}")
        print("Deterministic report was still created successfully.")
        sys.exit(1)

    print("\nAI explanation:")
    pprint(explanation)

    json_path, txt_path = write_ai_outputs(
        explanation=explanation,
        base_name=base_name,
    )

    print("\nAI explanation files written:")
    print(f"  JSON: {json_path}")
    print(f"  TXT:  {txt_path}")

    if mismatches:
        print("\nResult: FAIL — mismatches found and explained.")
    else:
        print("\nResult: PASS — no mismatches found.")


if __name__ == "__main__":
    main()
