from __future__ import annotations

from copy import deepcopy

from src.framework.commands.verification_schema import (
    VERIFICATION_SCHEMA_VERSION,
    is_valid_verification_result,
    validate_verification_result,
)


def _valid_approve_result() -> dict:
    return {
        "schema_version": VERIFICATION_SCHEMA_VERSION,
        "verdict": "APPROVE",
        "summary": "The command sequence appears internally consistent.",
        "issues": [],
        "command_annotations": [],
    }


def _valid_approve_with_notes_result() -> dict:
    return {
        "schema_version": VERIFICATION_SCHEMA_VERSION,
        "verdict": "APPROVE_WITH_NOTES",
        "summary": "The sequence can execute, but one text label may overlap nearby geometry.",
        "issues": [
            {
                "severity": "WARNING",
                "description": "Text label may overlap the rectangle border.",
                "command_index": 5,
                "suggested_fix": "Move the text label upward by 100 mm.",
            }
        ],
        "command_annotations": [
            {
                "command_index": 5,
                "annotation": "Possible text overlap near upper border.",
                "concern_level": "MINOR",
            }
        ],
    }


def test_valid_approve_result_with_no_issues_passes() -> None:
    assert validate_verification_result(_valid_approve_result()) == []


def test_valid_approve_with_notes_result_with_warning_issue_passes() -> None:
    assert validate_verification_result(_valid_approve_with_notes_result()) == []


def test_valid_reject_result_with_blocker_issue_passes() -> None:
    result = {
        "schema_version": VERIFICATION_SCHEMA_VERSION,
        "verdict": "REJECT",
        "summary": "The sequence should not execute because it contains a blocker issue.",
        "issues": [
            {
                "severity": "BLOCKER",
                "description": "Required geometry is missing.",
                "command_index": 2,
            }
        ],
        "command_annotations": [
            {
                "command_index": 2,
                "annotation": "This command does not close the required boundary.",
                "concern_level": "MAJOR",
            }
        ],
    }

    assert validate_verification_result(result) == []


def test_missing_top_level_verdict_fails() -> None:
    result = _valid_approve_result()
    result.pop("verdict")

    assert validate_verification_result(result)


def test_invalid_verdict_value_fails() -> None:
    result = _valid_approve_result()
    result["verdict"] = "MAYBE"

    assert validate_verification_result(result)


def test_missing_schema_version_fails() -> None:
    result = _valid_approve_result()
    result.pop("schema_version")

    assert validate_verification_result(result)


def test_wrong_schema_version_fails() -> None:
    result = _valid_approve_result()
    result["schema_version"] = "2.0"

    assert validate_verification_result(result)


def test_empty_summary_fails() -> None:
    result = _valid_approve_result()
    result["summary"] = ""

    assert validate_verification_result(result)


def test_issue_with_invalid_severity_fails() -> None:
    result = _valid_approve_with_notes_result()
    result["issues"][0]["severity"] = "CRITICAL"

    assert validate_verification_result(result)


def test_issue_with_negative_command_index_fails() -> None:
    result = _valid_approve_with_notes_result()
    result["issues"][0]["command_index"] = -1

    assert validate_verification_result(result)


def test_annotation_with_invalid_concern_level_fails() -> None:
    result = _valid_approve_with_notes_result()
    result["command_annotations"][0]["concern_level"] = "LOW"

    assert validate_verification_result(result)


def test_extra_unexpected_top_level_property_fails() -> None:
    result = _valid_approve_result()
    result["extra"] = True

    assert validate_verification_result(result)


def test_extra_unexpected_issue_property_fails() -> None:
    result = _valid_approve_with_notes_result()
    result["issues"][0]["extra"] = True

    assert validate_verification_result(result)


def test_is_valid_verification_result_returns_true_false_correctly() -> None:
    valid_result = _valid_approve_result()
    invalid_result = deepcopy(valid_result)
    invalid_result["verdict"] = "INVALID"

    assert is_valid_verification_result(valid_result) is True
    assert is_valid_verification_result(invalid_result) is False
