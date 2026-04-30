"""
Optional live AI tests for Phase 20.

These tests call the real AI provider through src.ai.client.ask_ai().
They are skipped by default.

Run only when needed:

    $env:RUN_LIVE_AI="1"
    pytest tests/parametric/test_vessel_planner_live.py -q
"""

from __future__ import annotations

import os

import pytest

from src.ai.vessel_planner import (
    extracted_to_vessel_parameters,
    plan_vessel,
)
from src.parametric.vessel.parameters import validate_parameters


if os.getenv("RUN_LIVE_AI") != "1":
    pytest.skip(
        "Skipping live AI tests. Set RUN_LIVE_AI=1 to run.",
        allow_module_level=True,
    )


V201_PROMPT = (
    "Generate horizontal vessel V-201, 2000mm internal diameter, "
    "4500mm tangent-to-tangent length, 2:1 ellipsoidal heads, "
    "with a 6-inch process inlet at top center, "
    "an 8-inch process outlet at bottom center, "
    "a 2-inch level instrument on the side, "
    "and a 3-inch relief valve at top."
)


def test_live_ai_extracts_v201_and_validates_cleanly() -> None:
    extracted = plan_vessel(V201_PROMPT)

    assert extracted["tag"] == "V-201"
    assert extracted["internal_diameter_mm"] == 2000
    assert extracted["tangent_to_tangent_mm"] == 4500
    assert extracted["head_type"] == "ELLIPSOIDAL_2_1"
    assert extracted["orientation"] == "HORIZONTAL"

    assert len(extracted["nozzles"]) == 4

    sizes = sorted(
        float(nozzle["nominal_size_inches"])
        for nozzle in extracted["nozzles"]
    )

    assert sizes == [2.0, 3.0, 6.0, 8.0]

    positions = [
        nozzle["position"]
        for nozzle in extracted["nozzles"]
    ]

    assert positions.count("TOP") == 2
    assert positions.count("BOTTOM") == 1
    assert positions.count("SIDE_FRONT") == 1

    assert "assumptions" in extracted
    assert len(extracted["assumptions"]) >= 1

    params = extracted_to_vessel_parameters(extracted)

    assert validate_parameters(params) == []