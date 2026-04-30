from __future__ import annotations

import re


CHAT_ROUTE_PID = "pid_generate"
CHAT_ROUTE_SKETCH = "sketch_generate"
CHAT_ROUTE_EDIT = "autocad_edit"


def _normalize_prompt(prompt: str) -> str:
    return re.sub(r"\s+", " ", str(prompt or "").lower()).strip()


def is_new_drawing_request(prompt: str) -> bool:
    normalized = _normalize_prompt(prompt)
    create_words = (
        "draw ",
        "create ",
        "generate ",
        "build ",
        "make ",
        "design ",
        "prepare ",
        "draft ",
    )
    return any(normalized.startswith(word) for word in create_words)


def is_pid_request(prompt: str) -> bool:
    normalized = _normalize_prompt(prompt)

    strong_pid_signals = (
        "p&id",
        "p and id",
        "piping and instrumentation",
        "piping & instrumentation",
        "instrumentation diagram",
        "process diagram",
        "process unit",
    )
    if re.search(r"(^|[^a-z0-9])pid([^a-z0-9]|$)", normalized):
        return True
    if any(signal in normalized for signal in strong_pid_signals):
        return True

    weighted_pid_signals = (
        "separator",
        "horizontal separator",
        "vertical vessel",
        "storage tank",
        "vessel",
        "scrubber",
        "tank",
        "pump",
        "pumps",
        "exchanger",
        "heat exchanger",
        "3 phase",
        "three phase",
        "vapor outlet",
        "oil outlet",
        "water outlet",
        "feed inlet",
        "liquid outlet",
        "suction",
        "discharge",
        "gate valve",
        "control valve",
        "valves",
        "instrument",
        "instruments",
        "instrument bubble",
        "level control",
        "pressure control",
        "pi-",
        "pt-",
        "lt-",
        "lc-",
        "fi-",
        "ti-",
    )
    score = sum(1 for signal in weighted_pid_signals if signal in normalized)
    return score >= 2


def is_edit_request(prompt: str) -> bool:
    if is_new_drawing_request(prompt):
        return False

    normalized = _normalize_prompt(prompt)

    direct_edit_verbs = (
        "delete",
        "remove",
        "erase",
        "move",
        "shift",
        "change",
        "rename",
        "modify",
        "update",
        "replace",
        "resize",
        "extend",
        "trim",
        "rotate",
        "edit",
    )
    context_edit_verbs = direct_edit_verbs + ("add", "connect")
    existing_context_words = (
        "existing",
        "current drawing",
        "current autocad",
        "this drawing",
        "active drawing",
        "the title",
        "title text",
        "the circle",
        "the vessel",
        "the valve",
        "the line",
        "the text",
        "this line",
        "this vessel",
        "that circle",
        "outlet line",
        "separator outlet",
    )

    starts_with_direct_edit_verb = any(
        normalized == verb or normalized.startswith(f"{verb} ") for verb in direct_edit_verbs
    )
    has_context_edit_verb = any(
        normalized == verb or f"{verb} " in normalized for verb in context_edit_verbs
    )
    has_existing_context = any(context in normalized for context in existing_context_words)

    return starts_with_direct_edit_verb or (has_context_edit_verb and has_existing_context)


def decide_chat_route(prompt: str) -> str:
    new_drawing_request = is_new_drawing_request(prompt)
    pid_request = is_pid_request(prompt)
    edit_request = is_edit_request(prompt)

    if new_drawing_request and pid_request:
        return CHAT_ROUTE_PID
    if new_drawing_request:
        return CHAT_ROUTE_SKETCH
    if edit_request:
        return CHAT_ROUTE_EDIT
    if pid_request:
        return CHAT_ROUTE_PID
    return CHAT_ROUTE_SKETCH
