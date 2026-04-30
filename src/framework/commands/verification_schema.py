"""Strict JSON schema for Mode 2 verifier output.

Verdict meanings:
- APPROVE: no meaningful issues found.
- APPROVE_WITH_NOTES: minor concerns exist, engineer should review.
- REJECT: blocker issues exist; command sequence should not execute without
  correction.
"""

from __future__ import annotations

from typing import Any

from jsonschema import Draft7Validator


VERIFICATION_SCHEMA_VERSION = "1.0"


_VERDICTS = [
    "APPROVE",
    "APPROVE_WITH_NOTES",
    "REJECT",
]

_SEVERITIES = [
    "BLOCKER",
    "WARNING",
    "INFO",
]

_CONCERN_LEVELS = [
    "NONE",
    "MINOR",
    "MAJOR",
]


VERIFICATION_SCHEMA: dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "AutoCAD AI Command Verification Result",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "verdict",
        "summary",
        "issues",
        "command_annotations",
    ],
    "properties": {
        "schema_version": {
            "const": VERIFICATION_SCHEMA_VERSION,
        },
        "verdict": {
            "type": "string",
            "enum": _VERDICTS,
        },
        "summary": {
            "type": "string",
            "minLength": 1,
        },
        "issues": {
            "type": "array",
            "items": {
                "$ref": "#/definitions/issue",
            },
        },
        "command_annotations": {
            "type": "array",
            "items": {
                "$ref": "#/definitions/command_annotation",
            },
        },
    },
    "definitions": {
        "issue": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "severity",
                "description",
            ],
            "properties": {
                "severity": {
                    "type": "string",
                    "enum": _SEVERITIES,
                },
                "description": {
                    "type": "string",
                    "minLength": 1,
                },
                "command_index": {
                    "type": "integer",
                    "minimum": 0,
                },
                "suggested_fix": {
                    "type": "string",
                    "minLength": 1,
                },
            },
        },
        "command_annotation": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "command_index",
                "annotation",
                "concern_level",
            ],
            "properties": {
                "command_index": {
                    "type": "integer",
                    "minimum": 0,
                },
                "annotation": {
                    "type": "string",
                    "minLength": 1,
                },
                "concern_level": {
                    "type": "string",
                    "enum": _CONCERN_LEVELS,
                },
            },
        },
    },
}


_VALIDATOR = Draft7Validator(VERIFICATION_SCHEMA)


def _format_path(path_parts: Any) -> str:
    path = "root"

    for part in path_parts:
        if isinstance(part, int):
            path += f"[{part}]"
        else:
            path += f".{part}"

    return path


def _format_error(error: Any) -> str:
    path = _format_path(error.absolute_path)
    return f"{path}: {error.message}"


def validate_verification_result(data: dict) -> list[str]:
    """Return readable validation errors for a verifier result."""
    errors = sorted(
        _VALIDATOR.iter_errors(data),
        key=lambda error: (
            [str(part) for part in error.absolute_path],
            error.message,
        ),
    )

    return [_format_error(error) for error in errors]


def is_valid_verification_result(data: dict) -> bool:
    """Return True when the verifier result satisfies VERIFICATION_SCHEMA."""
    return not validate_verification_result(data)
