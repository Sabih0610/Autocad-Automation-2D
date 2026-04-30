"""
Tests for Phase 20 AI vessel planner helpers.

These tests do not call the live AI provider.
They test:
- AI output conversion into VesselParameters
- duplicate nozzle repair
- review formatting
- plan_vessel() wrapper using a mocked ask_ai()
"""

from __future__ import annotations

from src.ai import vessel_planner
from src.ai.vessel_planner import (
    extracted_to_vessel_parameters,
    format_for_review,
    plan_vessel,
)
from src.parametric.vessel.parameters import (
    NozzlePosition,
    validate_parameters,
)


def _sample_extracted() -> dict:
    return {
        "tag": "V-301",
        "internal_diameter_mm": 2400,
        "tangent_to_tangent_mm": 6000,
        "wall_thickness_mm": 12,
        "head_type": "ELLIPSOIDAL_2_1",
        "orientation": "HORIZONTAL",
        "nozzles": [
            {
                "tag": "N1",
                "nominal_size_inches": 6,
                "position": "TOP",
                "axial_position_mm": 3000,
                "radial_angle_degrees": 0,
            },
            {
                "tag": "N2",
                "nominal_size_inches": 8,
                "position": "BOTTOM",
                "axial_position_mm": 3000,
                "radial_angle_degrees": 0,
            },
        ],
        "saddles": [],
        "assumptions": ["test sample only"],
    }


def test_extracted_to_vessel_parameters_converts_cleanly() -> None:
    extracted = _sample_extracted()

    params = extracted_to_vessel_parameters(extracted)

    assert params.tag == "V-301"
    assert params.internal_diameter_mm == 2400
    assert params.tangent_to_tangent_mm == 6000
    assert params.wall_thickness_mm == 12
    assert len(params.nozzles) == 2
    assert params.nozzles[0].position == NozzlePosition.TOP


def test_extracted_to_vessel_parameters_validates_cleanly() -> None:
    extracted = _sample_extracted()

    params = extracted_to_vessel_parameters(extracted)

    assert validate_parameters(params) == []


def test_format_for_review_includes_main_values() -> None:
    extracted = _sample_extracted()

    review = format_for_review(extracted)

    assert "V-301" in review
    assert "Internal diameter: 2400 mm" in review
    assert "Tangent-to-tangent: 6000 mm" in review
    assert 'N1: 6" TOP' in review
    assert "Assumptions made:" in review


def test_postprocess_repairs_duplicate_top_relief_nozzle() -> None:
    extracted = {
        "tag": "V-201",
        "internal_diameter_mm": 2000,
        "tangent_to_tangent_mm": 4500,
        "wall_thickness_mm": 10,
        "head_type": "ELLIPSOIDAL_2_1",
        "orientation": "HORIZONTAL",
        "nozzles": [
            {
                "tag": "N1",
                "nominal_size_inches": 6,
                "position": "TOP",
                "axial_position_mm": 2250,
            },
            {
                "tag": "N4",
                "nominal_size_inches": 3,
                "position": "TOP",
                "axial_position_mm": 2250,
            },
        ],
        "saddles": [],
        "assumptions": [],
    }

    fixed = vessel_planner._postprocess_extracted(
        extracted,
        "Generate vessel with a 6 inch top inlet and a 3 inch relief valve at top.",
    )

    assert fixed["nozzles"][0]["axial_position_mm"] == 2250
    assert fixed["nozzles"][1]["axial_position_mm"] == 500

    params = extracted_to_vessel_parameters(fixed)

    assert validate_parameters(params) == []


def test_postprocess_adds_missing_defaults() -> None:
    extracted = {
        "tag": "V-400",
        "internal_diameter_mm": 1000,
        "tangent_to_tangent_mm": 3000,
        "nozzles": [],
    }

    fixed = vessel_planner._postprocess_extracted(
        extracted,
        "Generate vessel V-400.",
    )

    assert fixed["head_type"] == "ELLIPSOIDAL_2_1"
    assert fixed["orientation"] == "HORIZONTAL"
    assert fixed["wall_thickness_mm"] == 10.0
    assert fixed["saddles"] == []
    assert len(fixed["assumptions"]) >= 1


def test_plan_vessel_uses_mocked_ask_ai(monkeypatch) -> None:
    sample = _sample_extracted()

    def fake_ask_ai(prompt, schema, system_prompt=None, max_retries=1):
        assert "horizontal vessel" in prompt.lower()
        assert schema == vessel_planner.VESSEL_PARAMETER_SCHEMA
        assert system_prompt == vessel_planner.VESSEL_EXTRACTION_SYSTEM_PROMPT
        assert max_retries == 2
        return sample

    monkeypatch.setattr(vessel_planner, "ask_ai", fake_ask_ai)

    extracted = plan_vessel(
        "Generate horizontal vessel V-301 with 2400mm ID and 6000mm T/T."
    )

    assert extracted["tag"] == "V-301"
    assert len(extracted["nozzles"]) == 2


def test_plan_vessel_rejects_empty_prompt() -> None:
    try:
        plan_vessel("")
    except ValueError as exc:
        assert "must not be empty" in str(exc)
    else:
        raise AssertionError("Expected ValueError for empty prompt.")