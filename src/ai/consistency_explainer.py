"""
AI consistency report explainer.

This module turns deterministic mismatch results into a plain-English
explanation for engineers, drafters, or managers.

Important:
- This does NOT compare data.
- This does NOT touch AutoCAD.
- The deterministic checker remains the source of truth.
- AI only explains the already-found mismatches.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from src.ai.client import ask_ai


CONSISTENCY_EXPLANATION_SCHEMA = {
    "type": "object",
    "properties": {
        "overall_status": {
            "type": "string",
            "enum": ["PASS", "FAIL"],
        },
        "summary": {
            "type": "string",
            "minLength": 1,
        },
        "issue_count": {
            "type": "number",
        },
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "line_no": {"type": "string", "minLength": 1},
                    "field": {"type": "string", "minLength": 1},
                    "problem": {"type": "string", "minLength": 1},
                    "likely_impact": {"type": "string", "minLength": 1},
                    "recommended_action": {"type": "string", "minLength": 1},
                },
                "required": [
                    "line_no",
                    "field",
                    "problem",
                    "likely_impact",
                    "recommended_action",
                ],
                "additionalProperties": False,
            },
        },
        "manager_message": {
            "type": "string",
            "minLength": 1,
        },
    },
    "required": [
        "overall_status",
        "summary",
        "issue_count",
        "issues",
        "manager_message",
    ],
    "additionalProperties": False,
}


CONSISTENCY_EXPLAINER_SYSTEM_PROMPT = """
You explain AutoCAD drafting consistency check results.

Rules:
- The deterministic mismatch list is the source of truth.
- Do not invent new mismatches.
- Do not remove any mismatch.
- Keep the explanation professional and concise.
- Explain in simple plain English.
- Focus on what is wrong, why it matters, and what should be checked manually.
- Return JSON only.
"""


def explain_consistency_mismatches(
    mismatches: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Convert mismatch rows into a plain-English AI explanation.

    Args:
        mismatches:
            List of mismatch dictionaries from consistency_check.py

    Returns:
        JSON matching CONSISTENCY_EXPLANATION_SCHEMA.
    """
    if not mismatches:
        return {
            "overall_status": "PASS",
            "summary": "No mismatches were found. The P&ID and Excel line list are consistent.",
            "issue_count": 0,
            "issues": [],
            "manager_message": "The consistency check passed. No action is required for the tested P&ID and line list.",
        }

    prompt = (
        "Explain these AutoCAD/P&ID consistency mismatches in plain English.\n\n"
        "Mismatch data:\n"
        f"{json.dumps(mismatches, indent=2)}"
    )

    return ask_ai(
        prompt=prompt,
        schema=CONSISTENCY_EXPLANATION_SCHEMA,
        system_prompt=CONSISTENCY_EXPLAINER_SYSTEM_PROMPT,
    )