from __future__ import annotations

from src.framework.commands.schema import validate_command_sequence
from src.framework.pid.component_builder import render_pid_component_scene_data
from src.framework.pid.component_schema import validate_pid_component_scene_data
from src.framework.pid.component_templates import (
    available_pid_component_templates,
    choose_pid_component_template,
    horizontal_separator_template_scene,
    pump_tank_template_scene,
    vertical_vessel_template_scene,
)


def _component_texts(scene: dict) -> set[str]:
    texts: set[str] = set()
    for component in scene["components"]:
        for key in ("label", "text", "tag", "instrument_tag", "controller_tag"):
            if component.get(key):
                texts.add(component[key])
    return texts


def test_horizontal_separator_template_scene_validates() -> None:
    assert validate_pid_component_scene_data(horizontal_separator_template_scene()) == []


def test_vertical_vessel_template_scene_validates() -> None:
    assert validate_pid_component_scene_data(vertical_vessel_template_scene()) == []


def test_pump_tank_template_scene_validates() -> None:
    assert validate_pid_component_scene_data(pump_tank_template_scene()) == []


def test_available_pid_component_templates_contains_all_names() -> None:
    assert {"horizontal_separator", "vertical_vessel", "pump_tank"} <= set(
        available_pid_component_templates()
    )


def test_choose_horizontal_separator_template() -> None:
    template_name, scene = choose_pid_component_template(
        "horizontal 3 phase separator with oil water vapor"
    )

    assert template_name == "horizontal_separator"
    assert validate_pid_component_scene_data(scene) == []


def test_choose_vertical_vessel_template() -> None:
    template_name, scene = choose_pid_component_template("vertical vessel with vapor outlet")

    assert template_name == "vertical_vessel"
    assert validate_pid_component_scene_data(scene) == []


def test_choose_pump_tank_template() -> None:
    template_name, scene = choose_pid_component_template("tank pump suction discharge")

    assert template_name == "pump_tank"
    assert validate_pid_component_scene_data(scene) == []


def test_choose_unknown_prompt_defaults_to_horizontal_separator() -> None:
    template_name, scene = choose_pid_component_template("generic plant process sketch")

    assert template_name == "horizontal_separator"
    assert validate_pid_component_scene_data(scene) == []


def test_horizontal_template_contains_expected_text_references() -> None:
    texts = _component_texts(horizontal_separator_template_scene())

    assert {"3 Phase Inlet", "Vapor Outlet", "Oil Outlet", "Water Outlet"} <= texts


def test_vertical_template_contains_expected_text_references() -> None:
    texts = _component_texts(vertical_vessel_template_scene())

    assert {"Feed Inlet", "Vapor Outlet", "Liquid Outlet"} <= texts


def test_pump_template_contains_expected_text_references() -> None:
    texts = _component_texts(pump_tank_template_scene())

    assert {"Pump P-101", "Suction", "Discharge"} <= texts


def test_every_template_can_be_rendered() -> None:
    for builder in available_pid_component_templates().values():
        sequence = render_pid_component_scene_data(builder())
        assert sequence["commands"]


def test_every_rendered_template_command_sequence_validates() -> None:
    for builder in available_pid_component_templates().values():
        sequence = render_pid_component_scene_data(builder())
        assert validate_command_sequence(sequence) == []
