from __future__ import annotations

import re


CHAT_ROUTE_CAD3D = "cad3d_generate"
CHAT_ROUTE_CAD3D_EDIT = "cad3d_edit"
CHAT_ROUTE_PID = "pid_generate"
CHAT_ROUTE_SKETCH = "sketch_generate"
CHAT_ROUTE_EDIT = "autocad_edit"


def normalize_prompt(prompt: str) -> str:
    return re.sub(r"\s+", " ", str(prompt or "").lower()).strip()


def _normalize_prompt(prompt: str) -> str:
    return normalize_prompt(prompt)


def is_new_drawing_request(prompt: str) -> bool:
    normalized = normalize_prompt(prompt)
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


_THREE_D_INTENT_PATTERNS = (
    r"\b3d\b",
    r"\b3-d\b",
    r"\b3 dimensional\b",
    r"\b3-dimensional\b",
    r"\bthree dimensional\b",
    r"\bthree-dimensional\b",
    r"\bsolid model\b",
    r"\bisometric model\b",
)


_NEGATED_3D_PATTERNS = (
    r"\bnot\s+(?:a\s+|an\s+)?(?:3d|3-d|3 dimensional|3-dimensional|three dimensional|three-dimensional|solid model|isometric model)\b",
    r"\bno\s+(?:3d|3-d|3 dimensional|3-dimensional|three dimensional|three-dimensional|solid model|isometric model)\b",
    r"\b(?:do not|don't|dont)\s+(?:create|make|generate|build|draw|use|include)?\s*(?:a\s+|an\s+)?(?:3d|3-d|3 dimensional|3-dimensional|three dimensional|three-dimensional|solid model|isometric model)\b",
    r"\b(?:2d|2-d)\s*,?\s*not\s+(?:a\s+|an\s+)?(?:3d|3-d|3 dimensional|3-dimensional|three dimensional|three-dimensional|solid model|isometric model)\b",
    r"\b(?:3d|3-d|3 dimensional|3-dimensional|three dimensional|three-dimensional|solid model|isometric model)\s+(?:is\s+)?not\b",
)


_TWO_D_INTENT_PATTERNS = (
    r"\b2d\b",
    r"\b2-d\b",
    r"\btwo dimensional\b",
    r"\btwo-dimensional\b",
    r"\bflat\b",
    r"\bflat diagram\b",
    r"\b2d drawing\b",
    r"\b2d process layout\b",
    r"\b2d autocad drawing\b",
)


def has_negated_3d_intent(prompt: str) -> bool:
    normalized = normalize_prompt(prompt)
    return any(re.search(pattern, normalized) for pattern in _NEGATED_3D_PATTERNS)


def has_explicit_3d_intent(prompt: str) -> bool:
    normalized = normalize_prompt(prompt)
    return any(re.search(pattern, normalized) for pattern in _THREE_D_INTENT_PATTERNS)


def has_explicit_2d_intent(prompt: str) -> bool:
    normalized = normalize_prompt(prompt)
    return any(re.search(pattern, normalized) for pattern in _TWO_D_INTENT_PATTERNS)


def is_3d_request(prompt: str) -> bool:
    return has_explicit_3d_intent(prompt) and not has_negated_3d_intent(prompt)


def is_pid_request(prompt: str) -> bool:
    normalized = normalize_prompt(prompt)

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

    normalized = normalize_prompt(prompt)

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


_CAD3D_EDIT_VERBS = (
    "move",
    "shift",
    "relocate",
    "change",
    "set",
    "update",
    "resize",
    "increase",
    "decrease",
    "delete",
    "remove",
    "add",
    "place",
    "lengthen",
    "shorten",
)


_CAD3D_EQUIPMENT_TERMS = (
    "pump",
    "tank",
    "vessel",
    "separator",
    "exchanger",
    "heat exchanger",
    "valve",
    "flange",
    "support",
    "support leg",
    "support legs",
    "skid",
    "nozzle",
    "pipe",
    "routed pipe",
)


_CAD3D_COMPONENT_ID_PATTERN = re.compile(r"\b[A-Z]{1,4}-?\d{2,4}[A-Z]?\b", re.IGNORECASE)


def has_cad3d_edit_intent(prompt: str) -> bool:
    if is_new_drawing_request(prompt):
        return False
    if has_explicit_2d_intent(prompt):
        return False

    normalized = normalize_prompt(prompt)
    if not normalized:
        return False

    has_edit_verb = any(
        normalized == verb or normalized.startswith(f"{verb} ") or f" {verb} " in f" {normalized} "
        for verb in _CAD3D_EDIT_VERBS
    )
    if not has_edit_verb:
        return False

    has_component_id = bool(_CAD3D_COMPONENT_ID_PATTERN.search(prompt or ""))
    has_equipment_term = any(term in normalized for term in _CAD3D_EQUIPMENT_TERMS)
    explicit_3d_context = is_3d_request(prompt)

    if has_component_id:
        return True

    return explicit_3d_context and has_equipment_term


def decide_chat_route(prompt: str) -> str:
    new_drawing_request = is_new_drawing_request(prompt)
    cad3d_request = is_3d_request(prompt)
    pid_request = is_pid_request(prompt)
    cad3d_edit_request = has_cad3d_edit_intent(prompt)
    edit_request = is_edit_request(prompt)

    if new_drawing_request:
        if cad3d_request:
            return CHAT_ROUTE_CAD3D
        if pid_request:
            return CHAT_ROUTE_PID
        return CHAT_ROUTE_SKETCH
    if cad3d_edit_request:
        return CHAT_ROUTE_CAD3D_EDIT
    if edit_request:
        return CHAT_ROUTE_EDIT
    if cad3d_request:
        return CHAT_ROUTE_CAD3D
    if pid_request:
        return CHAT_ROUTE_PID
    return CHAT_ROUTE_SKETCH
