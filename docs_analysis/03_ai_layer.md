# AI Planning/Generation Layer (`src/ai/`) — Deep Reference

This document is a complete, standalone reference to `F:\RC-Projects\autocad-ai\autocad-ai\src\ai\`.
It assumes no other context. Every file under `src/ai/` was read in full, along with the
corresponding tests under `tests/framework/`, and the API routes in `src/api/routes/` that call
into this layer (used only for cross-referencing "who calls what" — the routes themselves belong
to a different layer).

---

## 1. Role in the system

`src/ai/` is the **AI planning layer**. Its single job is: take a natural-language user request
(plus, for "edit" flows, a read-only snapshot of current state) and turn it into **JSON that
matches a strict, hand-written JSON Schema** (owned by `src/framework/commands/*schema.py`,
`src/framework/pid/component_schema.py`, `src/framework/cad3d/scene_schema.py`,
`src/framework/cad3d/edit_schema.py`, `src/framework/commands/planning_schema.py`,
`src/framework/commands/edit_schema.py`, `src/framework/commands/verification_schema.py`).

Every module in this layer explicitly documents in its module docstring that it does **not**:
- touch AutoCAD or call COM,
- execute commands,
- expose FastAPI routes,
- render previews.

Callers (FastAPI routes in `src/api/routes/*.py`, or `src/use_cases/*.py`) take the validated
JSON this layer returns and hand it to the **deterministic framework/executor layer**
(`src/framework/commands/executor.py`, `src/framework/commands/edit_executor.py`,
`src/framework/cad3d/autocad_3d_executor.py`, `src/framework/pid/component_builder.py`, etc.)
which is the only code that actually drives AutoCAD via `pywin32`/COM.

So the pipeline shape everywhere in this codebase is:

```
user prompt --> src/ai/* (LLM call -> JSON, schema-validated, possibly repaired) --> validated JSON
             --> src/framework/* deterministic executor (COM/pywin32) --> AutoCAD
```

The AI layer is allowed to fail loudly (raise `ValueError`, custom exceptions) — it never tries to
"partially" apply anything to AutoCAD, since it never touches AutoCAD at all. Several planners
(P&ID, CAD3D scene, CAD3D edit) additionally implement a **"resilient" wrapper** that falls back to
a deterministic, non-AI template/heuristic if the AI call/validation fails, so the system can still
produce *something* usable even when DeepSeek is unavailable or returns bad JSON.

---

## 2. `client.py` — the shared LLM call primitive

Path: `src/ai/client.py` (245 lines). This is the **only file in `src/ai/` that imports `openai`**
and the only place that reads AI-provider environment variables. Every other module in `src/ai/`
imports `ask_ai` from here and never touches `OpenAI(...)` or env vars directly.

### Public surface
- `ask_ai(prompt: str, schema: dict, system_prompt: str | None = None, max_retries: int = 1, max_tokens: int | None = None) -> dict` — the **only function every other AI module calls**.
- Exceptions: `AIConfigError` (bad/missing provider config, e.g. missing `AI_PROVIDER`/`DEEPSEEK_API_KEY`, unsupported provider), `AIResponseError` (empty content, invalid JSON, or retries exhausted).
- Internal helpers (prefixed `_`, not meant for external use but monkeypatched directly in some tests): `_load_env`, `_get_provider`, `_get_deepseek_client`, `_validate_schema`, `_validate_response`, `_extract_json`, `_build_system_prompt`, `_resolve_max_tokens`, `_ask_deepseek`.

### Construction / env vars
- `_load_env()` calls `dotenv.load_dotenv()` — loads `.env` from project root (python-dotenv default search).
- `_get_provider()` reads `AI_PROVIDER` env var, `.strip().lower()`s it; raises `AIConfigError("AI_PROVIDER is missing in .env")` if empty.
- `_get_deepseek_client()` reads `DEEPSEEK_API_KEY` (required — raises `AIConfigError("DEEPSEEK_API_KEY is missing in .env")` if blank) and `DEEPSEEK_BASE_URL` (optional, defaults to `"https://api.deepseek.com"`). Constructs `openai.OpenAI(api_key=..., base_url=...)`. This is the **only supported provider currently**; if `AI_PROVIDER` is anything other than `"deepseek"`, `ask_ai` raises `AIConfigError(f"Unsupported AI_PROVIDER='{provider}'. Currently supported: deepseek")`. The module docstring notes `openai` and `anthropic` are "future providers" but no code path implements them yet.
- Model name comes from `DEEPSEEK_MODEL` env var, defaulting to `"deepseek-chat"` (read inside `_ask_deepseek`, not at client-construction time).

### Request shape ("chat completion -> JSON" call)
`_ask_deepseek(prompt, schema, system_prompt=None, max_retries=1, max_tokens=None)`:
- Builds a 2-message list: `role="system"` with content from `_build_system_prompt(schema, system_prompt)`, and `role="user"` with content `f"Return valid JSON for this request:\n{prompt}"`.
- `_build_system_prompt` embeds the **entire JSON schema, pretty-printed with `json.dumps(schema, indent=2)`**, inside a fixed boilerplate block: "You are an AI planner for an AutoCAD automation system... Return JSON only... The JSON must match this schema exactly... Do not invent fields... If a value is unknown, use null only if the schema allows it." followed by `JSON schema:\n{schema_text}`. If a module-specific `system_prompt` (called `extra_system_prompt` inside this function) is supplied, it's appended as `\n\nExtra rules:\n{extra_system_prompt.strip()}`. So every module's own system prompt (e.g. `COMMAND_GENERATOR_SYSTEM_PROMPT`) is **appended after**, not instead of, this generic JSON-schema-enforcement boilerplate.
- Calls `client.chat.completions.create(model=model, messages=messages, response_format={"type": "json_object"}, temperature=0, max_tokens=resolved_max_tokens)`. Uses OpenAI's JSON-mode `response_format`, `temperature=0` (deterministic), and always passes `max_tokens`.
- `_resolve_max_tokens(None)` defaults to **800**. If a caller passes a non-`None` value it must be a positive `int` (not `bool`, not `float`, not numeric string) or `_resolve_max_tokens` raises `ValueError("max_tokens must be a positive integer")`. `ask_ai` calls `_resolve_max_tokens(max_tokens)` up front (before dispatching to a provider) purely to validate — the resolved value is discarded and re-resolved again inside `_ask_deepseek`.

### JSON parsing/validation
- `_extract_json(content)`: `json.loads`; on `json.JSONDecodeError` raises `AIResponseError(f"AI returned invalid JSON: {e}")`; if the parsed value isn't a `dict`, raises `AIResponseError("AI JSON response must be an object/dictionary")`.
- `_validate_response(data, schema)`: builds a `jsonschema.Draft7Validator(schema)`, collects `validator.iter_errors(data)` sorted by `.path`, and if any exist raises `jsonschema.ValidationError` (imported directly, **not** wrapped in `AIResponseError`) with message `f"{path}: {first_error.message}"` where `path` is the dotted JSON path of the first error or `"root"`.
- `ask_ai` itself calls `_validate_schema(schema)` first (checks `schema` is a dict, `schema["type"] == "object"`, and runs `Draft7Validator.check_schema(schema)` — validates the *schema itself* is well-formed, raising `AIConfigError` for structural problems).

### Retry behavior
- `_ask_deepseek` loops `for attempt in range(max_retries + 1)` (so `max_retries=2` means up to 3 total API calls).
- On any `Exception` (JSON parse failure, schema `ValidationError`, empty-content `AIResponseError`, or any OpenAI SDK exception) during an attempt that isn't the last, it appends a **new user message** to the running `messages` list: `"Your previous response failed validation. Exact error: {type(e).__name__}: {e}. Return one complete valid JSON object only. Do not include markdown, comments, or prose. If the JSON would be too long, shorten arrays or text values while preserving the required schema."` — i.e. retries are **conversational** (full message history including the bad prior response is *not* re-appended, only this corrective instruction — note the assistant's bad reply itself is never added back into `messages`, only the corrective user message is appended before the next `create()` call, which effectively resends the same system+user+correction each time; each retry still uses the ORIGINAL user message plus growing correction messages).
- If the final attempt still fails, raises `AIResponseError(f"AI failed after retry. Last error: {last_error}")`.
- Default `max_retries=1` in both `_ask_deepseek` and `ask_ai`; individual planner modules commonly pass `max_retries=2` explicitly (see per-module sections).

### Timeout behavior
No explicit timeout is configured anywhere in this file — relies on the OpenAI SDK's own default HTTP timeout. There is no explicit `timeout=` argument passed to `OpenAI(...)` or to `.create(...)`.

### Error types raised (summary)
| Exception | Raised when |
|---|---|
| `AIConfigError` | Missing `AI_PROVIDER`/`DEEPSEEK_API_KEY`, unsupported provider, malformed schema argument (not dict / `type != "object"` / fails `Draft7Validator.check_schema`) |
| `AIResponseError` | Empty LLM content, invalid JSON, or retries exhausted (wraps last error's string) |
| `jsonschema.ValidationError` | Schema-validation failure inside a single attempt (caught internally and turned into a retry message; only escapes to the caller wrapped inside the final `AIResponseError` string after retries are exhausted) |
| `ValueError` | Directly from `_resolve_max_tokens` for bad `max_tokens` |

### Tests (`tests/framework/test_ai_client.py`, 62 lines)
Two tests only:
1. `test_ask_ai_passes_max_tokens_to_provider` — monkeypatches `_load_env`, `_get_provider` (forced to `"deepseek"`), and `_ask_deepseek` itself (not the OpenAI client) to a fake capturing function; asserts `ask_ai(...)` forwards `prompt`, `schema`, `system_prompt`, `max_retries`, `max_tokens` verbatim and returns the fake's dict unchanged.
2. `test_ask_ai_invalid_max_tokens_raises_value_error` — parametrized over `[0, -1, 1.5, True, "100"]`, asserts `ValueError` with message `"max_tokens must be a positive integer"`.

**Gap:** No test in this file exercises `_ask_deepseek`'s actual retry loop, the OpenAI client construction, `_build_system_prompt`, `_extract_json`, or `_validate_response` directly — those are only exercised indirectly (and only for the "happy path") by every other module's tests, which monkeypatch `ask_ai` itself rather than `_ask_deepseek`. There is no test proving retries actually append the corrective message, no test for `AIConfigError` on missing env vars, and no test for the "unsupported provider" branch.

---

## 3. Per-module reference

### 3.1 `command_generator.py` (104 lines) — Mode 2 draft command generator

**Purpose:** Convert one natural-language drawing request directly into one validated AutoCAD
"command sequence" JSON object (the flat LAYER/LINE/CIRCLE/... instruction list the deterministic
executor eventually plays back). This is the simplest, non-chunked, non-verified generator — the
foundation every other command-oriented module (`command_orchestrator`, `command_repairer`,
`chunked_command_generator`) builds on or calls.

**Public function:** `generate_commands(user_request: str) -> dict`.

**Prompt construction:** `COMMAND_GENERATOR_SYSTEM_PROMPT` (module-level constant, f-string interpolating `COMMAND_SCHEMA_VERSION`) is a fixed system prompt (no per-call templating) describing:
- Required top-level output shape: `{"schema_version": "1.0", "summary": "...", "estimated_drawing_type": "...", "assumptions": [...], "commands": []}`.
- Output rules: JSON only, no markdown/code fences/raw AutoCAD script, no invented command types, always include `schema_version` and `assumptions` (even empty), max 1000 commands.
- Coordinate convention: **millimeters**, origin `(0,0)` bottom-left unless stated, X right / Y up.
- The **closed set of allowed `command` values**: `LAYER, LINE, CIRCLE, ARC, ELLIPSE, POLYLINE, TEXT, INSERT, DIM_LINEAR` (this list is duplicated — not shared — across `command_generator.py`, `command_repairer.py`, and is separately the authoritative `_COMMAND_TYPES` list in `src/framework/commands/schema.py`).
- Layer-naming convention suggestions (`BORDER, SHELL, NOZZLE, CENTERLINE, DIMENSION, TEXT, EQUIPMENT, PIPING`) and "create layers before drawing on them."
- Explicit worked examples embedded as prose ("Good example for 'draw a rectangle 1000 by 500': ...").
- A safety instruction: this is draft/concept quality, not fabrication-grade; if the user asks for engineering precision, add an assumption that dimensions must be engineer-verified.

The **user prompt is the raw stripped request**, passed through unmodified as `ask_ai`'s `prompt` argument (no wrapping template beyond what `client.py` itself adds).

**Call into `ask_ai`:** `ask_ai(prompt=clean_request, schema=COMMAND_SCHEMA, system_prompt=COMMAND_GENERATOR_SYSTEM_PROMPT, max_retries=2)` — no `max_tokens` override (defaults to 800 inside `client.py`).

**Expected JSON schema:** `COMMAND_SCHEMA` from `src/framework/commands/schema.py`. Top-level `required`: `schema_version` (`const "1.0"`), `summary` (non-empty string), `assumptions` (array of strings), `commands` (array, `minItems: 1`, each item requires `command` from the enum above, plus per-command-type fields via `allOf`). `estimated_drawing_type` is optional. `additionalProperties: False` at the top level.

**Validation/repair here:** `generate_commands` itself does **not** call the repairer — it validates once (`result.setdefault("schema_version", COMMAND_SCHEMA_VERSION)` then `validate_command_sequence(result)`) and if validation fails, raises `ValueError(f"Generated command sequence failed validation:\n{joined_errors}")` (bullet-joined per-error strings) — it never retries via `command_repairer`. Repair/retry only happens one layer up, in `command_orchestrator.py` or `chunked_command_generator.py`.

**Returns:** the validated dict (with `schema_version` guaranteed present).

**Callers:** `src/api/routes/sketch.py` imports `generate_commands` directly for the `generation_strategy == "direct"` path (when the request's `run_verifier` flag is false) — see §4/§6 cross-reference. Also called internally by `chunked_command_generator.generate_commands_for_chunk` (per-chunk) and by `command_orchestrator.generate_verified_command_sequence` (first step).

**Tests (`test_command_generator.py`, 134 lines):** monkeypatches `command_generator.ask_ai`. Covers: empty-prompt `ValueError`; exact args forwarded to `ask_ai` (prompt stripped, schema, system prompt identity, `max_retries==2`); happy path returns AI dict unchanged; missing `schema_version` gets defaulted; invalid command JSON (LINE missing `to`) raises `ValueError` matching `"Generated command sequence failed validation"`; round-trip `is_valid_command_sequence` check. One `RUN_LIVE_AI_TESTS`-gated live test hits real DeepSeek and asserts ≥4 commands including a LINE for "rectangle 1000x500".

---

### 3.2 `command_verifier.py` (141 lines) — reviews a generated command sequence

**Purpose:** Take a generator's output and ask a **second** LLM call to review it for "mechanical/drafting" issues (not engineering correctness) and produce a structured verdict.

**Public function:** `verify_commands(user_request: str, generator_output: dict) -> dict`.

**Preconditions:** `user_request` non-empty after `.strip()` else `ValueError("user_request cannot be empty")`; `generator_output` must be a `dict` else `ValueError("generator_output must be a dict")`; `_require_generator_fields` checks `summary`, `assumptions`, `commands` are present, else `ValueError("generator_output missing required fields: " + ", ".join(missing))`.

**Prompt construction:** `COMMAND_VERIFIER_SYSTEM_PROMPT` (fixed, f-string interpolating `VERIFICATION_SCHEMA_VERSION`) instructs the model to check only mechanical/internal issues: inconsistent layer usage, missing closing side of rectangle/polyline "when obvious", non-positive dimensions/radii, zero-length lines/arcs, unclear text placement, disconnected dimension commands, "coordinate jumps that look accidental", accidental duplicate geometry, commands not satisfying the user request, "obvious overlap warnings" — and explicitly **not** to claim ASME/ANSI/API/pressure-design/pipe-schedule/fabrication-readiness verification. Defines verdict semantics: `APPROVE` (internally consistent/executable), `APPROVE_WITH_NOTES` (executable but warnings exist), `REJECT` (blocker exists).

`_build_verifier_prompt(user_request, generator_output)` builds the **user** message: original request, generator's `summary`, `estimated_drawing_type` (or `"unspecified"`), `assumptions` (JSON), command count, then the **full generator output JSON** (`json.dumps(generator_output, indent=2, sort_keys=True)`).

**Call into `ask_ai`:** `ask_ai(prompt=full_prompt, schema=VERIFICATION_SCHEMA, system_prompt=COMMAND_VERIFIER_SYSTEM_PROMPT, max_retries=2)`.

**Expected JSON schema:** `VERIFICATION_SCHEMA` (`src/framework/commands/verification_schema.py`). Top-level `required`: `schema_version` (const `"1.0"`), `verdict` (enum `APPROVE|APPROVE_WITH_NOTES|REJECT`), `summary` (non-empty string), `issues` (array of `#/definitions/issue` — each issue has `severity` enum `BLOCKER|WARNING|INFO`, `description`, likely `command_index`/`suggested_fix` per test fixtures), `command_annotations` (array). `additionalProperties: False`.

**Validation:** `result.setdefault("schema_version", ...)` then `validate_verification_result(result)`; on failure raises `ValueError(f"Verifier result failed validation:\n{joined_errors}")`. No repair loop inside this module — verifier failures propagate to the caller (the orchestrator), which decides what to do (see §4).

**Returns:** the validated verifier-result dict.

**Callers:** `command_orchestrator.generate_verified_command_sequence` and `chunked_command_orchestrator.generate_chunked_verified_command_sequence` (both import `verify_commands` directly).

**Tests (`test_command_verifier.py`, 150 lines):** empty-request and non-dict/missing-field preconditions raise `ValueError`; exact `ask_ai` args (schema/system-prompt identity, `max_retries==2`, prompt contains request text and serialized commands); happy path passthrough; missing-`schema_version` auto-fill; invalid `verdict` value (`"INVALID"`, not in enum) raises `ValueError` matching `"Verifier result failed validation"`; round-trip `is_valid_verification_result`. One live test gated by `RUN_LIVE_AI_TESTS`.

---

### 3.3 `command_repairer.py` (161 lines) — fixes bad/rejected command sequences

**Purpose:** Given *any combination* of (a) bad/partial prior output, (b) schema validation errors, (c) verifier feedback, and/or (d) a previous good sequence to preserve intent from, produce **one** corrected, schema-valid command sequence via a single LLM call.

**Public function:** `repair_command_sequence(user_request: str, bad_output: str | dict | None = None, validation_errors: list[str] | None = None, verifier_result: dict | None = None, previous_command_sequence: dict | None = None) -> dict`. All four context arguments are optional and independently combinable — this is the single "repair" entry point used by every caller (`command_orchestrator`, `chunked_command_generator`, `chunked_command_orchestrator`) regardless of *why* repair was triggered.

**Prompt construction:** `COMMAND_REPAIR_SYSTEM_PROMPT` (fixed, f-string with `COMMAND_SCHEMA_VERSION`) tells the model it receives (original request, bad/partial output, schema errors, verifier feedback, optionally a previous sequence) and must return one corrected complete JSON object. Repeats the same command-type allow-list as the generator. Adds repair-specific guidance: "preserve the original user intent as much as possible"; "for complex drawings, simplify safely instead of failing"; "if verifier says a component is missing, add commands for it"; "if verifier says geometry overlaps or is disconnected, adjust coordinates or add connecting lines"; "if schema validation errors mention a field path, fix that field"; plus P&ID-specific guidance ("prefer a clean schematic layout... use simple linework, circles, text, and placeholder valve symbols... do not attempt fabrication-grade detail").

`_build_repair_prompt` assembles the user message as five labeled sections via `_format_context` (which renders `None` as `"None provided."`, passes strings through verbatim, and `json.dumps(value, indent=2, sort_keys=True)`s anything else, falling back to `str(value)` on serialization failure): "Original user drawing request", "Bad or partial command output", "Schema validation errors", "Verifier result and issues", "Previous command sequence, if any", followed by fixed repair instructions.

**Call into `ask_ai`:** `ask_ai(prompt=repair_prompt, schema=COMMAND_SCHEMA, system_prompt=COMMAND_REPAIR_SYSTEM_PROMPT, max_retries=2)` — same `COMMAND_SCHEMA` as the generator (repaired output must be a full valid command sequence, not a diff/patch).

**Validation:** result must be a `dict` (else `ValueError("Repaired command sequence must be a dict")`), `schema_version` defaulted, then `validate_command_sequence(result)`; failures raise `ValueError(f"Repaired command sequence failed validation:\n{joined_errors}")`. **No further retry inside this module** — if the single repair attempt is itself invalid, the caller (orchestrator) must decide whether to try repair again (bounded by its own `max_repair_attempts`).

**Returns:** validated repaired command-sequence dict.

**Callers:** `command_orchestrator._repair_for_schema_errors` / `_repair_for_verifier`; `chunked_command_generator.generate_commands_for_chunk` (per-chunk repair); `chunked_command_orchestrator._repair_for_schema_errors` / `_repair_for_verifier` (final-merge repair).

**Tests (`test_command_repairer.py`, 248 lines):** empty-request precondition; exact `ask_ai` args; prompt contains the original request; prompt contains `bad_output` whether passed as raw string or dict (serialized); prompt contains `validation_errors` strings; prompt contains verifier issue description and verdict string; prompt contains previous-sequence content; happy-path passthrough; missing-schema_version auto-fill; invalid repaired JSON raises `ValueError` matching `"Repaired command sequence failed validation"`; round-trip schema check. One live test (`RUN_LIVE_AI_TESTS`) feeds a truncated/broken JSON string as `bad_output` for a P&ID-style prompt and asserts the repaired result validates and contains at least one `LINE`.

---

### 3.4 `command_orchestrator.py` (241 lines) — generate → validate → verify → repair loop

**Purpose:** The single-shot (non-chunked) orchestration entry point that composes generator + verifier + repairer into one robust call with bounded retries. See §4 for the full generator→verifier→repairer→orchestrator composition semantics (shared in detail with `chunked_command_orchestrator.py`).

**Public function:** `generate_verified_command_sequence(user_request: str, max_repair_attempts: int = 2, repair_on_approve_with_notes: bool = False) -> dict`.

**Exception:** `CommandOrchestrationError`.

**Returns (dict):** `{"ok": True, "command_sequence": ..., "verifier_result": ..., "verifier_verdict": ..., "repair_attempts_used": int, "repair_history": [...]}`. Each `repair_history` entry (built by `_history_entry`) is `{"reason": str, "errors": list[str], "verdict": str|None}` where `reason` is one of `"schema_validation_failed"`, `"verifier_rejected"`, `"approve_with_notes_repair"`, `"verifier_failed_fallback"`.

**Callers:** `src/api/routes/sketch.py`, `generation_strategy == "normal"` path (`run_verifier=True` and prompt judged **not** complex by `_looks_complex_prompt`).

**Tests (`test_command_orchestrator.py`, 315 lines):** exhaustively covered — see §4 (shared with chunked variant) and §6.

---

### 3.5 `chunked_command_generator.py` (309 lines) — per-chunk generation + merge

**Purpose:** For drawings too large/complex to generate as one command sequence, generate commands **chunk by chunk** (each chunk being a small, independently-prompted sub-task from a `drawing_task_planner` plan), then deterministically merge the per-chunk sequences into one final command sequence. See §4 for why chunking exists and how it differs from the non-chunked path.

**Public functions:**
- `generate_commands_for_chunk(original_user_request: str, task_plan: dict, chunk: dict, previous_chunks: list[dict] | None = None, max_repair_attempts: int = 1) -> dict` — generates+validates+repairs one chunk.
- `merge_chunk_command_sequences(original_user_request: str, task_plan: dict, chunk_results: list[dict]) -> dict` — deterministic merge (no AI call).
- `generate_chunked_command_sequence(user_request: str, task_plan: dict, max_repair_attempts_per_chunk: int = 1) -> dict` — drives the whole per-chunk loop then merges.

**Exception:** `ChunkedCommandGenerationError`.

**Per-chunk prompt construction:** `_build_chunk_prompt` includes: original request; `task_plan["summary"]`; `task_plan["drawing_type"]` (falls back to `"generic CAD sketch"`); `task_plan["layout_strategy"]` (falls back to `"No explicit layout strategy provided."`); the **current chunk** serialized as JSON (`chunk_id`, `title`, `goal`, `expected_elements`, `layout_hint`); a JSON summary of **previous chunks already generated** (`_previous_chunks_summary` — for each prior chunk result, just `chunk_id`, `title`, `summary`, `command_count`, *not* the full command list, to keep the prompt compact); and fixed chunk-generation instructions ("Generate only this chunk", "Keep coordinates consistent with previous chunks", "Use existing layers if appropriate", "Do not redraw previous chunks unless necessary...", "Keep command count reasonable").

Note: this prompt is then passed as the `user_request` argument straight into `generate_commands(chunk_prompt)` — i.e. **the chunk generator reuses `command_generator.generate_commands` verbatim**, with the chunk-context text playing the role of the "user request." It does **not** call `ask_ai` directly and does **not** define its own system prompt — it inherits `COMMAND_GENERATOR_SYSTEM_PROMPT` from `command_generator.py`.

**Repair-per-chunk:** on `validate_command_sequence` failure, calls `repair_command_sequence(chunk_prompt, bad_output=command_sequence, validation_errors=validation_errors, previous_command_sequence=command_sequence)` in a loop bounded by `max_repair_attempts` (default 1 here, vs 2 in the non-chunked orchestrator); exhausting attempts raises `ChunkedCommandGenerationError`.

**Per-chunk return:** `{"chunk_id", "title", "command_sequence", "repair_attempts_used", "errors": []}`.

**Merge logic (`merge_chunk_command_sequences`, purely deterministic, no LLM call):**
- Requires non-empty `chunk_results` list, each with a valid `command_sequence` (re-validates every chunk's sequence again at merge time — defensive re-check).
- Concatenates `assumptions` from `task_plan["assumptions"]` plus every chunk's `assumptions`, then appends a fixed final assumption `"Layout was generated as a draft-quality schematic from chunked generation."`, then dedupes via `_dedupe_assumptions` (preserves first-seen order, `str`-only entries).
- Concatenates all `commands` from all chunks **in order**, with one dedup rule: consecutive/any `LAYER` commands are dropped if their `layer_name` was already seen in an earlier chunk (`seen_layers` set) — i.e. re-declaring a layer in a later chunk is silently dropped, everything else is kept verbatim.
- Builds final `{"schema_version": COMMAND_SCHEMA_VERSION, "summary": f"Merged command sequence from chunked generation for: {task_plan.get('summary', original_user_request)}", "estimated_drawing_type": task_plan.get("drawing_type"), "assumptions": deduped, "commands": merged}`, validates it, raises `ChunkedCommandGenerationError` on failure.

**Top-level `generate_chunked_command_sequence`:** validates `task_plan["chunks"]` is a non-empty list; **sorts chunks by `chunk.get("priority", 999999)`** (so planner-declared priority ordering is enforced even if the planner or a test passes chunks out of order); iterates, calling `generate_commands_for_chunk` with `previous_chunks=chunk_results` (accumulating prior results so each new chunk's prompt can see earlier chunks' summaries); merges; returns `{"ok": True, "command_sequence": merged, "chunk_results": [...], "chunk_count": int, "total_repair_attempts_used": sum of all chunks' repair_attempts_used}`.

**Callers:** `chunked_command_orchestrator.generate_chunked_verified_command_sequence` (only caller in production code).

**Tests (`test_chunked_command_generator.py`, 362 lines):** empty-request and missing-chunk-field preconditions; prompt-content assertions (original request, task-plan summary, chunk JSON fields all present); happy-path chunk result shape; repair-triggered-on-invalid-chunk (asserts repair called with right `bad_output`/`validation_errors`/`previous_command_sequence`); no-repair-attempts-raises; merge ordering (`LAYER`→`CIRCLE`→`TEXT` from chunk 1 then `LAYER`(dup, dropped)→`LINE` from chunk 2 — commands list literally checked index by index); duplicate-`LAYER`-removal check; merged-sequence-validates check; merged-assumptions-include-all-sources check; priority-sort check (chunks passed in reverse order, asserts generation order is `["equipment", "piping"]` matching `priority` field not list order); counts (`chunk_count`, `total_repair_attempts_used` summed correctly); invalid-merge-raises; empty-chunk-results-raises. One `RUN_LIVE_AI_TESTS` live test.

---

### 3.6 `chunked_command_orchestrator.py` (241 lines) — plan → chunked-generate → validate → verify → repair

**Purpose:** The full pipeline for complex drawings: plan chunks (via `drawing_task_planner`), generate+merge them (via `chunked_command_generator`), then run the **same** final validate/verify/repair loop shape as `command_orchestrator.py` on the merged result. This is almost a structural clone of `command_orchestrator.py` with one extra upstream stage; see §4 for the detailed comparison.

**Public function:** `generate_chunked_verified_command_sequence(user_request: str, max_chunks: int = 6, max_repair_attempts_per_chunk: int = 1, final_repair_attempts: int = 1, repair_on_approve_with_notes: bool = False) -> dict`.

**Exception:** `ChunkedCommandOrchestrationError`.

**Flow:**
1. Validates `max_chunks` in `[1, 12]`, `max_repair_attempts_per_chunk >= 0`, `final_repair_attempts >= 0`.
2. Calls `plan_drawing_tasks(clean_request, max_chunks=max_chunks)` then `generate_chunked_command_sequence(clean_request, task_plan, max_repair_attempts_per_chunk=...)`. **Any exception from either of these two calls** (planning or chunked generation, including their own internal repair exhaustion) is caught and re-raised as `ChunkedCommandOrchestrationError(f"Chunked generation failed: {type(exc).__name__}: {exc}")` — i.e. this stage has **no retry of its own**; all chunk-level repair already happened inside `generate_chunked_command_sequence`.
3. Takes the merged `command_sequence` from that result and runs the identical final loop as `command_orchestrator.generate_verified_command_sequence`: schema-validate → repair-on-failure (bounded by `final_repair_attempts`) → `verify_commands` → repair-on-`REJECT`/`APPROVE_WITH_NOTES` (if `repair_on_approve_with_notes`) → break on `APPROVE`. Verifier exceptions are caught and replaced with the same `_fallback_verifier_result` pattern as the non-chunked orchestrator.

**Returns (dict):** `{"ok": True, "task_plan": ..., "command_sequence": ..., "verifier_result": ..., "verifier_verdict": ..., "chunk_count": ..., "chunk_results": ..., "chunk_repair_attempts_used": ..., "final_repair_attempts_used": ..., "repair_history": [...]}`. Note `repair_history` here only records **final-stage** events (`"final_schema_validation_failed"`, `"final_verifier_rejected"`, `"approve_with_notes_repair"`, `"verifier_failed_fallback"`) — per-chunk repair attempts/history are *not* individually itemized in this list, only their **count** surfaces via `chunk_repair_attempts_used`.

**Callers:** `src/api/routes/sketch.py`, `generation_strategy == "chunked"` path (when `run_verifier=True` and `_looks_complex_prompt(prompt)` is true).

**Tests (`test_chunked_command_orchestrator.py`, 430 lines):** structurally mirrors `test_command_orchestrator.py` but patches four functions (`plan_drawing_tasks`, `generate_chunked_command_sequence`, `verify_commands`, `repair_command_sequence`) instead of three. Covers all the same validation/verifier/repair-history/fallback scenarios, plus chunk-specific ones: `max_chunks` passed through to `plan_drawing_tasks`; `max_repair_attempts_per_chunk` passed through to `generate_chunked_command_sequence`; `chunk_repair_attempts_used` surfaces the chunk generator's `total_repair_attempts_used` unchanged; a guard test (`test_orchestrator_does_not_call_executor_or_autocad`) asserting no executor/AutoCAD symbols leak into this module's namespace.

---

### 3.7 `drawing_task_planner.py` (114 lines) — decomposes a request into chunks

**Purpose:** The upstream planning step for the chunked pipeline. Converts one drawing request into an ordered list of small "chunks" (each a `{chunk_id, title, goal, priority, expected_elements, layout_hint?}` object) — **not** AutoCAD commands.

**Public function:** `plan_drawing_tasks(user_request: str, max_chunks: int = 6) -> dict`.

**Preconditions:** non-empty request; `max_chunks` in `[1, 12]` else `ValueError("max_chunks must be between 1 and 12")`.

**Prompt construction:** `DRAWING_TASK_PLANNER_SYSTEM_PROMPT` (fixed, f-string with `PLANNING_SCHEMA_VERSION`) instructs: decompose into small coherent chunks; no AutoCAD command objects/raw script; JSON only; order by priority; 4–8 chunks for complex drawings, 1–3 for simple; keep chunk vocabulary generic enough for P&ID sketches, plot plans, equipment layouts, single-line diagrams, generic sketches; include assumptions when unspecified. Gives **domain-specific suggested chunk breakdowns** as prose guidance for three drawing families: P&ID (`equipment / main piping-header / branches / valves / instruments / labels-annotations`), layout/plot-plan (`boundary-grid / major equipment / connecting paths / labels-annotations`), SLD/single-line-diagram (`source-transformer / busbar / feeders / loads / labels-protection`).

`_build_planner_prompt(user_request, max_chunks)` is a short user message: original request, then `f"Break this drawing into at most {max_chunks} logical chunks."`, then "Output one JSON object matching the provided planning schema."

**Call into `ask_ai`:** `ask_ai(prompt=planner_prompt, schema=DRAWING_TASK_PLAN_SCHEMA, system_prompt=DRAWING_TASK_PLANNER_SYSTEM_PROMPT, max_retries=2)`.

**Expected JSON schema:** `DRAWING_TASK_PLAN_SCHEMA` (`src/framework/commands/planning_schema.py`). Top-level `required`: `schema_version` (const), `drawing_type`, `summary`, `assumptions`, `chunks` (array, `minItems: 1`, `maxItems: 12`; each chunk object `additionalProperties: False` requiring `chunk_id` (pattern `^[A-Za-z0-9_-]+$`), `title`, `goal`, `priority`, `expected_elements`). `layout_strategy` is optional at top level.

**Validation:** result must be a `dict`; `schema_version` defaulted; `validate_drawing_task_plan(result)`, raising `ValueError(f"Drawing task plan failed validation:\n...")` on failure; **additionally**, after schema validation, an extra manual check: `if len(result.get("chunks", [])) > max_chunks: raise ValueError(...)` — this is a belt-and-suspenders check beyond what `maxItems: 12` in the schema enforces, since the caller's `max_chunks` can be lower than the schema's fixed ceiling of 12.

**Callers:** `chunked_command_orchestrator.generate_chunked_verified_command_sequence` (only caller in production code).

**Tests (`test_drawing_task_planner.py`, 174 lines):** empty-request/invalid-max_chunks preconditions; exact `ask_ai` args; prompt contains original request and the "at most N logical chunks" phrase; happy-path passthrough; missing-schema_version auto-fill; empty-`chunks` list fails validation (`ValueError` matching `"Drawing task plan failed validation"`); round-trip `is_valid_drawing_task_plan`. One live test.

---

### 3.8 `edit_generator.py` (193 lines) — live drawing edit planner

**Purpose:** Given a user's edit request **and** a read-only inspection snapshot of the currently-open AutoCAD drawing (entity list with handles), produce a validated "edit plan": which existing entity handles to delete, and which new commands to add. This is the only Mode-2-style module aimed at editing an *already open* drawing rather than generating a fresh one from scratch.

**Public function:** `generate_edit_plan(user_request: str, drawing_inspection: dict) -> dict`.

**Constant:** `MAX_PROMPT_ENTITIES = 100` — hard cap on how many entities get serialized into the prompt (protects against oversized prompts on large drawings).

**Preconditions:** non-empty request; `drawing_inspection` must be a `dict` with required keys `document_name`, `entities`, and `entities` must be a `list` (`_require_inspection_fields`), else `ValueError("drawing_inspection missing required fields: ...")` / `ValueError("drawing_inspection entities must be a list")`.

**Prompt construction:** `EDIT_GENERATOR_SYSTEM_PROMPT` (fixed, f-string with `EDIT_SCHEMA_VERSION`) instructs: identify entities to delete via `delete_handles`; add new geometry via `commands`; represent "move" or "replace" as delete-old + add-new; never invent handles not in the provided list; if ambiguous, pick the most likely target and document the assumption rather than guessing a broad destructive edit — explicitly states "A plan with no deletes and no commands is invalid, so only produce a safe minimal plan when the target is genuinely clear." Gives per-intent rules: delete/remove → `delete_handles`; move → delete old + add replacement with adjusted coords; change text → delete old TEXT + add new TEXT; add X → empty `delete_handles` + new commands; "make circle larger" → delete old circle + add larger CIRCLE; keep edits small/local; don't delete multiple entities unless clearly requested or the target is inherently multi-part; reuse the existing entity's layer unless told otherwise. Includes one **fully worked example** (a circle entity + "Delete the center circle" → full expected JSON output) directly embedded in the system prompt.

`_ENTITY_PROMPT_FIELDS` is a fixed allow-list of fields copied per entity into the prompt: `handle, object_name, entity_type, layer, center, radius, start_point, end_point, position, text, bbox`. `_compact_entities` truncates to `drawing_inspection["entities"][:MAX_PROMPT_ENTITIES]` and, per entity, keeps only keys present in both the entity dict and `_ENTITY_PROMPT_FIELDS` (drops everything else, e.g. `index`). `_build_edit_prompt` assembles: user edit request; `document_name`; entity count returned (from inspection, or `len(entities)` fallback); a header line `f"Current drawing entities (first {len(compact_entities)} of {len(entities)} returned):"`; then the compacted entity list as pretty JSON.

**Call into `ask_ai`:** `ask_ai(prompt=full_prompt, schema=EDIT_PLAN_SCHEMA, system_prompt=EDIT_GENERATOR_SYSTEM_PROMPT, max_retries=2)`.

**Expected JSON schema:** `EDIT_PLAN_SCHEMA` (`src/framework/commands/edit_schema.py`) — reuses `COMMAND_SCHEMA`'s `commands` sub-schema (same allowed command types) but with `minItems: 0` (an edit can be pure deletion, no new commands) and adds top-level `required`: `schema_version` (const, same version string as `COMMAND_SCHEMA_VERSION`), `edit_intent`, `summary`, `assumptions`, `delete_handles` (array of non-empty strings), `commands`. `target_description` is optional. `additionalProperties: False`.

**Validation:** result must be `dict`; `schema_version` defaulted; `validate_edit_plan(result)`; failure raises `ValueError(f"Generated edit plan failed validation:\n...")`. Note: the schema itself cannot express "must have at least one delete OR one command" (both arrays independently allow zero length) — that invariant is enforced by `validate_edit_plan`'s own logic (not visible in this file, but exercised by the test where an all-empty plan fails validation) rather than by JSON Schema structure, matching the system prompt's stated rule.

**No repair loop in this module** — `generate_edit_plan` does one `ask_ai` call (with its own internal `max_retries=2` retry inside `client.py`) and either returns or raises; there is no `command_repairer`-style second-stage repair for edit plans anywhere in the codebase.

**Callers:** `src/api/routes/autocad_edit.py` (`edit_autocad_drawing` route) — the only caller. That route first calls `inspect_active_drawing`/`summarize_drawing_state` (framework layer, live COM inspection) to build `drawing_inspection`, then `generate_edit_plan(prompt, inspection)`, then (if `auto_execute`) `execute_edit_plan` (framework layer).

**Tests (`test_edit_generator.py`, 225 lines):** preconditions (empty request, non-dict inspection, missing `entities`); exact `ask_ai` args and that the prompt contains the request, document name, and every entity handle; happy-path passthrough of a delete-only plan; missing-schema_version auto-fill; an all-empty (`delete_handles=[]`, `commands=[]`) plan raises `ValueError` matching `"Generated edit plan failed validation"` (confirms the "no deletes and no commands is invalid" rule is enforced downstream); round-trip `is_valid_edit_plan`; a dedicated 105-entity test proving truncation to exactly the first 100 (`"first 100 of 105 returned"` string, `H000`..`H099` present, `H100`/`H104` absent). One live test.

---

### 3.9 `symbol_planner.py` (127 lines) — single-symbol placement planner

**Purpose:** The simplest/oldest-feeling module in the layer: converts a single natural-language instruction like "Place a 6 inch gate valve at 100, 200 on layer P-VALVES with tag V-2045" into one flat JSON object describing a single block/symbol insertion (no `commands` array, no `assumptions`, no `schema_version` field at all — structurally unlike every other module).

**Public function:** `plan_symbol_placement(user_request: str) -> Dict[str, Any]`.

**Schema (defined inline in this file, not imported from `src/framework`):** `SYMBOL_PLACEMENT_SCHEMA` — `required: [task_type, block_name, insertion_point, rotation_degrees, scale, layer, attributes]`, `additionalProperties: False`. `task_type` is `const`-like via `enum: ["place_symbol"]`. `block_name` enum: `GATE_VALVE, CHECK_VALVE, CONTROL_VALVE, PUMP, VESSEL, INSTRUMENT_BUBBLE`. `insertion_point` is `{x, y, z}` all required numbers. `attributes` requires `TAG, SIZE, SERVICE` (all non-empty strings, `additionalProperties: False`).

**Prompt construction:** `SYMBOL_PLANNER_SYSTEM_PROMPT` maps natural-language valve/equipment names to the exact `block_name` enum values; fixes `z=0`/`rotation_degrees=0`/`scale=1` unless the user specifies otherwise; "preserve layer names exactly as written by the user"; defaults `SIZE`/`SERVICE` to `"UNKNOWN"` if unmentioned; never empty strings; never extra fields; do not invent coordinates unless the user "clearly asks for a default location" (in which case `x=0, y=0`).

**Call into `ask_ai`:** `ask_ai(prompt=clean_request, schema=SYMBOL_PLACEMENT_SCHEMA, system_prompt=SYMBOL_PLANNER_SYSTEM_PROMPT)` — **note: no `max_retries` override** (uses `client.py`'s default of 1, unlike every other module in this layer which explicitly passes `max_retries=2`). No `max_tokens` override either.

**Validation:** **None beyond what `ask_ai`/`client.py` already does internally** (schema-validates via `Draft7Validator` inside `_ask_deepseek`). `plan_symbol_placement` does no `setdefault`, no post-hoc `validate_*` call, and returns `ask_ai(...)`'s result directly — this is the only planner in the layer with **zero module-level post-validation or schema-version defaulting**.

**Callers:** `src/api/routes/place_symbol.py` (`place_symbol` route, lazily imports `plan_symbol_placement` inside the handler) — passes the planned spec straight to `src/use_cases/place_symbol.insert_symbol` (framework/use-case layer) for actual COM insertion.

**Tests:** **No dedicated test file exists** for `symbol_planner.py` under `tests/framework/` (confirmed: `tests/framework/test_symbol_planner.py` does not exist in the required test list, and no other file in `tests/framework/` imports `src.ai.symbol_planner`). The only references to symbol-planner behavior are ad hoc scripts under `src/scratch/` (`test_symbol_planner.py`, `test_ai_symbol_batch.py`, `test_ai_symbols.py`, `execute_ai_symbol_batch_small.py`, `execute_ai_symbol_batch_full.py`) which are developer scratch scripts, not part of the `pytest` suite. **This is the single biggest test-coverage gap in the whole AI layer** (see §6/§7).

---

### 3.10 `vessel_planner.py` (619 lines) — the largest, most deterministic-heavy module

**Purpose:** Extract structured parameters for a **horizontal pressure vessel** (shell diameter, tangent-to-tangent length, head type, nozzles, saddles) from natural language, then convert that into a `VesselParameters` dataclass instance consumed by the deterministic parametric vessel generator (`src/parametric/vessel/*`). Unusually, this module does substantial **deterministic post-processing** of the AI output before returning it — more than any other planner.

**Public functions:**
- `plan_vessel(user_request: str) -> dict[str, Any]` — the main entry point (AI call + post-processing).
- `extracted_to_vessel_parameters(extracted: dict) -> VesselParameters` — pure dataclass conversion (imports `HeadType`, `Nozzle`, `NozzlePosition`, `Orientation`, `Saddle`, `VesselParameters` from `src/parametric/vessel/parameters.py`).
- `format_for_review(extracted: dict) -> str` — human-readable multi-line text rendering of the extracted parameters, for showing the user before they confirm (used by the `/generate-vessel/extract` route's `formatted_review` response field).

**Schema:** `VESSEL_PARAMETER_SCHEMA` (defined inline, not shared with `src/framework`) — `required: [tag, internal_diameter_mm, tangent_to_tangent_mm, head_type, orientation, wall_thickness_mm, nozzles, saddles, assumptions]`. `internal_diameter_mm` bounded `[100, 10000]`; `tangent_to_tangent_mm` bounded `[200, 30000]`; `wall_thickness_mm` bounded `[1, 200]`; `head_type` enum currently **only** `["ELLIPSOIDAL_2_1"]` (schema comment: "Only 2:1 ellipsoidal heads are supported in this phase"); `orientation` enum currently **only** `["HORIZONTAL"]` ("Only horizontal vessels are supported in this phase") — i.e. the schema is intentionally narrower than the full `VesselParameters`/`HeadType`/`Orientation` enum space (vertical vessels and other head types are not yet AI-extractable even if the dataclass layer supports more). Nozzle items require `tag, nominal_size_inches (enum of standard NPS sizes: 1,1.5,2,3,4,6,8,10,12), position (enum TOP/BOTTOM/LEFT_END/RIGHT_END/SIDE_FRONT/SIDE_BACK), axial_position_mm`; `radial_angle_degrees` optional (0-360). Saddles only require `axial_position_mm` (width/height optional, "geometry layer fills defaults").

**Prompt construction:** `VESSEL_EXTRACTION_SYSTEM_PROMPT` is the most detailed domain-specific prompt in the layer: explicit unit-conversion rules (meters/inches/feet → mm for vessel dims; nozzle sizes stay in inches); default values to use only if unspecified (`head_type=ELLIPSOIDAL_2_1`, `orientation=HORIZONTAL`, `wall_thickness_mm=10`, `saddles=[]`, `radial_angle_degrees=0` for side nozzles); natural-language → enum mapping for nozzle position and axial position phrases ("top center", "near left end", "relief valve/PSV/safety valve/vent on TOP with no axial position → TOP at 500mm from left tangent", etc.); auto-numbering nozzle tags `N1, N2, N3...` if unspecified; and an extensive "ASSUMPTIONS" section requiring every default/inference to be recorded in the `assumptions` array. **No worked JSON example is embedded** (unlike `edit_generator`/`pid_component_planner`/`cad3d_scene_planner`).

**Call into `ask_ai`:** `ask_ai(prompt=user_request, schema=VESSEL_PARAMETER_SCHEMA, system_prompt=VESSEL_EXTRACTION_SYSTEM_PROMPT, max_retries=2)` — the raw `user_request` is passed **unstripped/untemplated** directly as the prompt (no `_build_*_prompt` wrapper function exists in this module, unlike every other planner).

**Deterministic post-processing (unique to this module) — `_postprocess_extracted`:**
1. `_normalize_extracted_defaults`: fills in `head_type`/`orientation`/`wall_thickness_mm`/`saddles`/`assumptions` defaults **again in Python** if the AI omitted them (belt-and-suspenders beyond the system-prompt instruction), appending matching assumption strings via `_append_assumption` (dedupes by exact string match); also defaults each nozzle's `radial_angle_degrees` to `0.0` if missing, and if that nozzle is `SIDE_FRONT`/`SIDE_BACK`, appends an assumption noting the default.
2. `_repair_duplicate_nozzle_locations`: a **deterministic conflict-resolution pass** that detects nozzles the AI placed at the exact same `(position, axial_position_mm, radial_angle_degrees)` (rounded to 3 decimals) and relocates later duplicates to a "clear" position using `_find_clear_axial_position` (tries a fixed candidate list: 500mm from each end, quarter/three-quarter points, ±500mm from the original position; falls back to scanning every 250mm from 0 to `tangent_to_tangent_mm`). Special-cases relief/PSV/safety-valve/vent terms in the request text (`relief_terms_present`) to prefer relocating a duplicate TOP nozzle to 500mm from the left tangent specifically. Every relocation appends an assumption string documenting the move. This function explicitly states in its docstring: "The validator still remains the final authority. This function only repairs obvious extraction mistakes."

**No JSON-Schema-based `validate_*` call at the end of `plan_vessel`** — unlike every other planner in the layer, this module does **not** call any `validate_command_sequence`-equivalent before returning. The docstring is explicit: "This does not validate engineering... Final engineering validation still happens outside this function through `validate_parameters()`" (a function in `src/parametric/vessel/parameters.py`, outside this layer's scope, called later by the route). So `plan_vessel`'s output is schema-shaped by construction/AI-schema-enforcement inside `ask_ai`, but the *engineering* validation is deliberately deferred to the parametric/framework layer.

**`_enum_from_name_or_value`:** a defensive helper used by `extracted_to_vessel_parameters` to convert an AI-returned string into a Python enum member tolerant of case and separator differences (tries direct value construction, then name lookup, then case-insensitive name/value/hyphen-normalized matching) — guards against the AI returning `"top"` vs `"TOP"` vs some other casing.

**Callers:** `src/api/routes/vessel.py` — `/generate-vessel/extract` calls `plan_vessel` + `format_for_review`; `/generate-vessel/confirm` (not fully read, but by naming convention) subsequently calls `extracted_to_vessel_parameters` and the deterministic vessel-drawing generator.

**Tests:** **No `test_vessel_planner.py` exists** in the required test list, and none was found elsewhere under `tests/framework/`. This is the **second major test-coverage gap** — a 619-line module with the most complex deterministic logic in the entire AI layer (duplicate-nozzle repair, unit normalization, enum coercion) has zero automated test coverage in the reviewed test suite.

---

### 3.11 `pid_component_planner.py` (306 lines) — component-level P&ID planner with template fallback

**Purpose:** Instead of asking the AI to emit raw AutoCAD LINE/CIRCLE commands for a P&ID, this module asks the AI to emit a **higher-level "component scene"** (named component types like `horizontal_vessel`, `gate_valve`, `instrument_bubble`, `pipe_run`) which a separate deterministic renderer (`src/framework/pid/component_builder.render_pid_component_scene_data`) expands into the actual low-level command sequence. This is the module the task description's "deterministic template fallback" note refers to most directly.

**Public functions:**
- `plan_pid_component_scene(user_request, drawing_style="clean schematic P&ID") -> dict` — strict AI-only planning, raises on any failure.
- `plan_and_render_pid_component_scene(user_request, drawing_style=...) -> dict` — plans then renders to a command sequence (still strict/AI-only, no fallback).
- `plan_pid_component_scene_resilient(user_request, drawing_style=..., allow_template_fallback=True, template_first=False) -> dict` — **the resilient wrapper with template fallback** (see below).
- `plan_and_render_pid_component_scene_resilient(user_request, drawing_style=..., allow_template_fallback=True, template_first=False) -> dict` — resilient plan + render, used by the actual API route.

**Supported component types** (`_SUPPORTED_COMPONENT_TYPES`): `horizontal_vessel, vertical_vessel, pipe_run, signal_line, gate_valve, control_valve, instrument_bubble, controller_loop, label, flow_arrow, leader_line`.

**`PID_COMPONENT_PLANNER_MAX_TOKENS = 5000`** — explicitly overrides the 800-token default because component scenes are large structured JSON with many components.

**Prompt construction:** `PID_COMPONENT_PLANNER_SYSTEM_PROMPT` lists the component types, instructs millimeters, "keep layout clean and orthogonal," reasonable fixed coordinates, major equipment centered, labels away from lines/equipment, use component abstractions instead of drawing raw valve/instrument geometry, prefer 8–35 components, no extra/unsupported fields. Gives **layout guidance per equipment family** (horizontal vessel separator: vessel at origin, inlet left, vapor outlet upper-right, oil outlet lower-right, water outlet lower-left; vertical vessel: feed inlet left, top vapor outlet, bottom liquid outlet; pump/tank: tank left, pump center-right, discharge right) and **ID-naming conventions** per equipment class (`V201/V301/T101` for equipment, `P_IN/P_OUT/P_VAPOR/...` for pipes, `XV_IN/CV_OIL/LV_OUT` for valves, `PI201/PT201/LT201/LC201` for instruments, `LBL_TITLE/LBL_INLET/...` for labels).

`_build_planner_prompt(user_request, drawing_style)` includes the supported-type list, layout rules, and a **full worked example component scene JSON** (`_EXAMPLE_COMPONENT_SCENE` — a horizontal vessel with inlet pipe, gate valve, and instrument bubble) embedded verbatim.

**Call into `ask_ai`:** `ask_ai(prompt=planner_prompt, schema=PID_COMPONENT_SCENE_SCHEMA, system_prompt=PID_COMPONENT_PLANNER_SYSTEM_PROMPT, max_retries=2, max_tokens=PID_COMPONENT_PLANNER_MAX_TOKENS)`.

**Expected JSON schema:** `PID_COMPONENT_SCENE_SCHEMA` (`src/framework/pid/component_schema.py`). Each component's schema is type-specific (`_component_schema(component_type, required, properties)` factory per type), all sharing base properties `component_type` (`const`), `id`, `tag`, `center` (2-number point), `metadata`. Points are `[x, y]` 2-tuples (P&ID is 2D, unlike CAD3D below).

**Validation:** `result.setdefault("schema_version", PID_COMPONENT_SCHEMA_VERSION)`, then `validate_pid_component_scene_data(result)`, raising `ValueError` on failure. `plan_and_render_pid_component_scene` additionally renders via `render_pid_component_scene_data(scene_data)` and re-validates the **rendered command sequence** with `validate_command_sequence` — i.e. two independent validation passes (component-scene schema, then rendered-command schema).

**The resilient/fallback pattern (`plan_pid_component_scene_resilient`) — this is the "deterministic template fallback" the task description asks about:**
- If `template_first=True`: **skips the AI entirely**, calls `choose_pid_component_template(clean_request)` (from `src/framework/pid/component_templates.py` — a deterministic keyword-based template selector, e.g. request text containing "3 phase"/"separator" → `horizontal_separator` template, "tank"+"pump" → `pump_tank` template) and returns that scene directly, tagging `metadata = {"planner_strategy": "template_selected", "fallback_used": False, "template_name": ..., "ai_planner_attempted": False, "ai_planner_error_type": None, "ai_planner_error": None}`.
- Otherwise, tries `plan_pid_component_scene(...)` first. **On any exception** (AI call failure, JSON/schema validation failure — anything `plan_pid_component_scene` can raise), if `allow_template_fallback` is true, catches it and falls back to `choose_pid_component_template(clean_request)`, appends an assumption string `"AI component planner failed, so a deterministic template fallback was used. Review and edit the result as needed."`, and tags metadata `{"planner_strategy": "template_fallback", "fallback_used": True, "fallback_reason": f"{type(exc).__name__}: {exc}", "template_name": ..., "ai_planner_attempted": True, "ai_planner_error_type": type(exc).__name__, "ai_planner_error": str(exc)}`. If `allow_template_fallback=False`, the original exception is **re-raised** unchanged (no fallback).
- On AI success (no exception), tags metadata `{"planner_strategy": "ai_component_planner", "fallback_used": False, "ai_planner_attempted": True, "ai_planner_error_type": None, "ai_planner_error": None}`.
- `plan_and_render_pid_component_scene_resilient` wraps the above and additionally renders+validates the command sequence, surfacing `planner_strategy`, `fallback_used`, `fallback_reason`, `template_name` as **top-level** result keys (not nested under `metadata`) for the API route to consume directly.

This means the system **always** produces a usable P&ID (either AI-planned or template-based) unless the caller explicitly disables fallback — the deterministic templates (`horizontal_separator`, `pump_tank`, etc., defined in `src/framework/pid/component_templates.py`, outside this layer's scope) act as a hard safety net against DeepSeek being down or returning malformed JSON.

**Callers:** `src/api/routes/pid.py` (`pid_generate` route) calls `plan_and_render_pid_component_scene_resilient(prompt, drawing_style=request.drawing_style, allow_template_fallback=True, template_first=False)` — production usage always allows fallback and never forces template-first.

**Tests (`test_pid_component_planner.py`, 256 lines):** empty-request precondition; exact `ask_ai` args (schema, system prompt, `max_retries==2`, `max_tokens==PID_COMPONENT_PLANNER_MAX_TOKENS`, prompt contains request/style/component-type names); happy-path passthrough; missing-schema_version auto-fill; invalid scene (missing required `length` on a vessel) raises `ValueError` matching `"P&ID component scene failed validation"`; round-trip schema validation; `plan_and_render_...` returns `{ok, component_scene, command_sequence, component_count}` and the rendered command sequence validates; resilient-success path asserts `planner_strategy=="ai_component_planner"` and all fallback flags false/None; resilient-failure path (mocked `plan_pid_component_scene` raising `RuntimeError("invalid JSON")`) asserts fallback metadata exactly as described above, that `template_name=="horizontal_separator"` for a "3 phase separator" prompt, and that an assumption mentioning "deterministic template fallback" was added; `allow_template_fallback=False` re-raises the original `RuntimeError`; the full resilient-render wrapper surfaces `planner_strategy`/`fallback_used`/`template_name` as top-level keys and picks `template_name=="pump_tank"` for a "tank pump suction discharge" prompt; `template_first=True` returns `planner_strategy=="template_selected"` with `ai_planner_attempted is False` **without any AI mock at all** (proving the AI path is genuinely skipped, not just mocked to fail). One live test (`RUN_LIVE_AI_TESTS`).

---

### 3.12 `cad3d_scene_planner.py` (386 lines) — 3D equipment scene planner with template fallback

**Purpose:** The 3D analogue of `pid_component_planner.py`. Plans a structured 3D equipment scene (tanks, vessels, pumps, pipe runs, skids, supports, flanges, etc., all in millimeters, 3D coordinates) for later expansion/execution by `src/framework/cad3d/*`. Also implements the identical AI-then-deterministic-template-fallback pattern.

**Public functions:**
- `build_cad3d_planner_prompt(user_request, drawing_style="simple clean 3D equipment layout") -> str` — exposed as a standalone function (tested directly, unlike most other planners' prompt builders which are private `_build_*` functions).
- `plan_cad3d_scene(user_request, drawing_style=...) -> dict` — strict AI-only.
- `plan_cad3d_scene_resilient(user_request, drawing_style=..., allow_example_fallback=True) -> dict` — resilient wrapper.

**`CAD3D_SCENE_PLANNER_MAX_TOKENS = 4000`** — another explicit override of the 800 default.

**Supported component types** (`_SUPPORTED_COMPONENT_TYPES`, 15 total): `vertical_tank_3d, horizontal_vessel_3d, pump_placeholder_3d, pipe_run_3d, pipe_connection_3d, skid_base_3d, box_3d, label_3d, heat_exchanger_3d, valve_placeholder_3d, nozzle_3d, flange_3d, support_leg_3d, saddle_support_3d, pipe_support_3d`.

**Prompt construction — the most elaborate in the layer:** `CAD3D_SCENE_PLANNER_SYSTEM_PROMPT` covers component-type list, millimeter units, per-type modeling guidance (tanks as vertical cylinders, pumps as placeholder boxes, etc.), scene-size guidance (8–35 components), and a **detailed pipe-routing sub-system**:
- Two pipe representations: `pipe_connection_3d` (a *logical* port-to-port connection — `from_port`/`to_port` in `COMPONENT_ID.PORT_NAME` format — which Python code later expands into an actual `pipe_run_3d` centerline before AutoCAD execution) vs `pipe_run_3d` (an explicit free-form centerline `points` list) for headers/vents/drains/bypasses where no clean port-to-port mapping exists.
- A documented **port vocabulary per component type** (`vertical_tank_3d`: top/bottom/side_left/side_right/side_front/side_back/inlet/outlet/drain/vent; `horizontal_vessel_3d`: end_a/end_b/inlet/outlet/top/bottom/drain/vent; `heat_exchanger_3d`: inlet/outlet/end_a/end_b; `pump_placeholder_3d`: suction/discharge/inlet/outlet; `valve_placeholder_3d`: inlet/outlet; `nozzle_3d`: base/tip/inlet/outlet; `flange_3d`: face_a/face_b/inlet/outlet; `pipe_run_3d`: start/end).
- Naming convention: component IDs without dashes (`T101`), tags with dashes for labels (`T-101`).
- Two embedded worked `pipe_connection_3d` JSON examples.

`build_cad3d_planner_prompt` additionally embeds **"design family hints"** (prose, not enforced by schema) mapping request archetypes to expected component sets: "tank pump separator", "dual pump skid", "heat exchanger skid", "vertical scrubber package", "extended process unit" — and a **full worked example scene** (`_EXAMPLE_CAD3D_SCENE` — skid base + vertical tank + pump + heat exchanger + 2 `pipe_connection_3d` + 3 labels) embedded verbatim.

**Call into `ask_ai`:** `ask_ai(prompt=planner_prompt, schema=CAD3D_SCENE_SCHEMA, system_prompt=CAD3D_SCENE_PLANNER_SYSTEM_PROMPT, max_retries=2, max_tokens=CAD3D_SCENE_PLANNER_MAX_TOKENS)`.

**Expected JSON schema:** `CAD3D_SCENE_SCHEMA` (`src/framework/cad3d/scene_schema.py`) — 3D analogue of the P&ID component schema; `center`/points are 3-number `[x, y, z]` (`_POINT3_SCHEMA`), plus an `axis_order` concept (`_AXIS_ORDER_SCHEMA`, array of `X`/`Y`/`Z`, 1–3 items) not present in the 2D P&ID schema.

**Validation:** `_validate_scene_or_raise` wraps `validate_cad3d_scene` + `ValueError` on failure. On success, `plan_cad3d_scene` **always sets `metadata`** on the result: `{"planner_strategy": "ai_cad3d_scene_planner", "fallback_used": False}` (note: fewer keys than the resilient wrapper adds — see below).

**Resilient/fallback pattern (`plan_cad3d_scene_resilient`) — structurally identical to the P&ID one:**
- Tries `plan_cad3d_scene`. On success, re-sets/extends `metadata` to add `ai_planner_attempted: True, ai_planner_error_type: None, ai_planner_error: None` (in addition to what `plan_cad3d_scene` already set).
- On any exception, if `allow_example_fallback` (note: **differently named parameter** than the P&ID version's `allow_template_fallback` — see §7 inconsistency notes) is true, calls `choose_cad3d_template(clean_request)` (from `src/framework/cad3d/component_templates.py` — deterministic keyword template selector, e.g. "heat exchanger"+"bypass" → `heat_exchanger_skid` template, generic tank+pump request → `tank_pump_separator` template), appends assumption `"AI 3D planner failed, so a deterministic 3D design template was used."`, and sets metadata with **both** `fallback_template_name` **and** `fallback_example_name` set to the same value (redundant duplicate keys — see §7), plus `fallback_reason`, `ai_planner_attempted: True`, `ai_planner_error_type`, `ai_planner_error`. If `allow_example_fallback=False`, re-raises.

**Callers:** `src/api/routes/cad3d.py` (`cad3d_generate` route) calls `plan_cad3d_scene_resilient(prompt, drawing_style=drawing_style, allow_example_fallback=True)` when a `prompt` is supplied (vs. a deterministic `example_name` path when no prompt is given — that path bypasses this module entirely and pulls a canned example scene from `src/framework/cad3d/component_examples.py`). `cad3d_edit_planner.py` also imports `choose_cad3d_template`... actually no, `cad3d_edit_planner.py` does not import scene planner; confirmed only `cad3d_scene_planner.py` imports `choose_cad3d_template`.

**Tests (`test_cad3d_scene_planner.py`, 401 lines):** the most thorough prompt-content test coverage in the layer — separate tests assert the prompt/system-prompt contain: original request, drawing style, every one of the 15 supported component types, every expanded component type restated inside the *system* prompt specifically, `pipe_connection_3d` mentioned in the system prompt, specific pipe-routing-guidance phrases ("prefer pipe_connection_3d", "equipment-to-equipment", "port", "component_id.port_name" — all lower-cased comparison), all 5 design-family hint phrases, the 4 "expanded" component-type examples, the specific `T101.side_right`/`P101.suction`/`P101.discharge`/`E101.inlet` port examples, and the literal substring `'"component_type": "pipe_connection_3d"'` in the compact example. Functional tests: `ask_ai` arg-forwarding (including `max_tokens==CAD3D_SCENE_PLANNER_MAX_TOKENS`); valid scene returned+validated (`ai_cad3d_scene_planner` strategy tag); valid scene **containing** a `pipe_connection_3d` also validates and `count_pipe_connections(result) == 1` (imported from `src.framework.cad3d.routing`); missing-schema_version auto-fill; invalid scene (missing `diameter`) raises; invalid `pipe_connection_3d` (missing `to_port`) raises; resilient-success metadata shape; resilient-fallback metadata shape (asserts **both** `fallback_template_name` and `fallback_example_name` are set, and `count_pipe_connections(result) >= 1` — i.e. even the fallback template scene has real pipe connections, not just placeholder geometry); a test that explicitly monkeypatches `choose_cad3d_template` itself (not just `plan_cad3d_scene`) to prove the resilient wrapper calls it with the right `user_request` argument and surfaces its chosen template name; a semantic test that a "heat exchanger skid with pump bypass" prompt falls back specifically to the `heat_exchanger_skid` template (via the *real*, non-mocked `choose_cad3d_template`); fallback-disabled re-raise test. One live test (`RUN_LIVE_AI_TESTS`).

---

### 3.13 `cad3d_edit_planner.py` (363 lines) — 3D scene edit planner with regex-based deterministic fallback

**Purpose:** The 3D analogue of `edit_generator.py`, but for **CAD3D scene components** (not raw AutoCAD entities/handles) — and unlike every other fallback in this layer (which falls back to a fixed *template*), this module's fallback is a **regex/keyword-based deterministic parser** that directly interprets simple edit requests ("move X right 500mm", "delete X", "change X length to 4500mm") without any AI call at all.

**Public functions:**
- `summarize_scene_for_edit_prompt(scene: dict) -> list[dict]` — compacts a CAD3D scene's components into a prompt-friendly list (keeps `id`, `tag`, `component_type`, and whichever of `center`/`position`/`points` plus dimension fields `length/width/height/diameter/orientation/thickness/valve_type` are present per component — drops everything else).
- `build_cad3d_edit_planner_prompt(user_request, scene) -> str` — exposed and directly tested.
- `plan_cad3d_edit(user_request, scene) -> dict` — AI-only edit planning.
- `deterministic_edit_plan_from_request(user_request, scene) -> dict` — the **non-AI regex fallback** planner.
- `plan_cad3d_edit_resilient(user_request, scene, allow_fallback=True) -> dict` — AI-first, falls back to the deterministic regex planner on failure.
- `_validate_edit_plan_references_scene(plan, scene) -> None` — post-AI sanity check.

**Loose local schema:** `CAD3D_EDIT_PLAN_SCHEMA` defined in this file is intentionally **permissive** (`additionalProperties: True`, only requires `schema_version` (const `"1.0"`), `edit_intent`, `summary`, `operations` (array, `minItems: 1`)) — this is passed to `ask_ai` as the *shape* the LLM must produce, but the file then does **stricter, separate** validation afterward via `validate_cad3d_edit_plan` imported from `src/framework/cad3d/edit_schema.py` (which enforces the real operation-type-specific structure, e.g. `move_component` needs `component_id`+`delta`, and restricts `update_component`'s `updates` to `_ALLOWED_UPDATE_FIELDS` while forbidding `id`/`component_type` from being updated). This is a deliberate **two-tier validation**: loose JSON-mode schema for the LLM call itself (to keep the `ask_ai` schema-embedding prompt small/simple), strict semantic schema (`CAD3DEditValidationError`) applied after.

**Operation types:** `move_component`, `update_component`, `add_component`, `delete_component`.

**Prompt construction:** `CAD3D_EDIT_PLANNER_SYSTEM_PROMPT` instructs: JSON only; edit CAD3D components by ID, never raw AutoCAD entities/handles; map dash-tags like `P-101` to dashless component ids like `P101` when available; use 3D `[x, y, z]` deltas; explicit axis convention (`right=+X, left=-X, forward=+Y, backward=-Y, up=+Z, down=-Z`); millimeters; never modify `id`/`component_type`; prefer `pipe_connection_3d` when adding pipe connections "when clear"; note that deleting a component may cascade-delete connected pipes (handled by the scene editor, not this planner). `build_cad3d_edit_planner_prompt` embeds the compacted component summary (via `summarize_scene_for_edit_prompt`), the 4 operation types with their expected fields, the axis convention again, and **one worked example** (`move_component` on `P101` with `delta: [1000, 0, 0]`).

**Call into `ask_ai`:** `ask_ai(prompt=prompt, schema=CAD3D_EDIT_PLAN_SCHEMA, system_prompt=CAD3D_EDIT_PLANNER_SYSTEM_PROMPT, max_retries=2, max_tokens=2000)`.

**Post-AI validation (`plan_cad3d_edit`):** `validate_cad3d_edit_plan(result)` (strict, raises `CAD3DEditValidationError` on failure), then `_validate_edit_plan_references_scene(plan, scene)` — walks every operation, and for any non-`add_component` operation whose `component_id` is not one of the scene's actual component IDs, raises `CAD3DSceneEditError(f"Edit plan references missing CAD3D component: {component_id}")` — i.e. this module actively guards against the LLM hallucinating a component ID that doesn't exist in the current scene (a check none of the other planners perform for their equivalent handle/ID references, though `edit_generator.py`'s *system prompt* asks the LLM not to invent handles, it has no equivalent **code-level** enforcement).

**Deterministic fallback (`deterministic_edit_plan_from_request`) — pure regex, no AI, no template file:**
- `_find_component_for_request`: matches the request text against every component's `id`/`tag` (normalized both as lowercase-with-whitespace-collapsed and as alphanumeric-only-compacted strings) to find explicit matches; if exactly one match, use it; if multiple, narrow to exact-ID matches; otherwise falls back to `_generic_type_candidates` (keyword→component-type-set map: `pump→pump_placeholder_3d`, `tank→vertical_tank_3d`, `vessel→{horizontal_vessel_3d, vertical_tank_3d}`, `separator→horizontal_vessel_3d`, `exchanger→heat_exchanger_3d`, `valve→valve_placeholder_3d`) — if exactly one component of a matched generic type exists in the scene, use it. Raises `CAD3DSceneEditError("Could not determine which CAD3D component to edit")` if ambiguous/no match.
- `_parse_move_delta`: two regex patterns (`"<number> [mm] [to the] <direction>"` or `"<direction> <number> [mm]"`) mapping `right/left/forward/backward/up/down` to unit vectors, scaled by the parsed distance.
- `_parse_dimension_update`: two regex patterns matching `change/set/increase <field> [to] <value> [mm]` or bare `<field> [to] <value> [mm]` for `length|width|height|diameter`.
- Dispatch order in `deterministic_edit_plan_from_request`: **move/shift** keyword (`\b(move|shift)\b`) checked first → builds `move_component`; else **delete/remove** (`\b(delete|remove)\b`) → `delete_component`; else a dimension-update pattern match → `update_component`; else raises `CAD3DSceneEditError("No deterministic CAD3D edit fallback matched the request")`. Every fallback plan is run through `validate_cad3d_edit_plan(...)` before being returned and tags `metadata: {"planner_strategy": "deterministic_edit_fallback"}`.

**Resilient wrapper (`plan_cad3d_edit_resilient`):** tries `plan_cad3d_edit`; on any exception, if `allow_fallback`, calls `deterministic_edit_plan_from_request` and tags metadata `{"planner_strategy": "deterministic_edit_fallback", "fallback_used": True, "ai_planner_attempted": True, "ai_planner_error_type": type(exc).__name__, "ai_planner_error": str(exc)}`; on AI success tags `{"planner_strategy": "ai_cad3d_edit_planner", "fallback_used": False, "ai_planner_attempted": True, "ai_planner_error_type": None, "ai_planner_error": None}`. Both paths run the result through `validate_cad3d_edit_plan` once more before returning.

**Callers:** `src/api/routes/cad3d.py` (`cad3d_edit` route) imports both `deterministic_edit_plan_from_request` and `plan_cad3d_edit_resilient` directly (the route likely offers a way to force the deterministic path explicitly, in addition to the normal resilient AI-first path — consistent with `pid_component_planner`'s `template_first` flag pattern, though `cad3d_edit_planner` has no single flag toggle equivalent to `template_first`; the route composes the two functions itself).

**Tests (`test_cad3d_edit_planner.py`, 139 lines):** prompt-content checks (component IDs/tags present, all 4 operation types present, axis-direction mapping present in both the built prompt and the system-prompt constant); AI-mocked valid-plan success; AI-mocked invalid-plan (missing `delta`) raises `CAD3DEditValidationError`; resilient fallback on AI failure produces a correct `move_component` plan with numeric `delta`; direct fallback-function tests for tag→id mapping, delete, and dimension-update; a fallback-fails-cleanly test for an unsupported free-text edit ("Make the model more beautiful") raising `CAD3DSceneEditError`; resilient metadata correctness for both the fallback and AI-success cases. **No test exercises `_validate_edit_plan_references_scene`'s hallucinated-component-id guard directly** (a minor gap — see §6).

---

### 3.14 `consistency_explainer.py` (118 lines) — explains deterministic mismatches in plain English

**Purpose:** Distinct from every other module: this one does **not** produce anything the executor layer consumes. It takes a list of already-computed mismatch dictionaries (from a deterministic P&ID-vs-Excel line-list comparison, `src/use_cases/consistency_check.py`, outside this layer) and asks the AI to write a plain-English explanation for engineers/drafters/managers. Explicitly documented: "This does NOT compare data. This does NOT touch AutoCAD. The deterministic checker remains the source of truth. AI only explains the already-found mismatches."

**Public function:** `explain_consistency_mismatches(mismatches: List[Dict[str, Any]]) -> Dict[str, Any]`.

**Short-circuit:** if `mismatches` is empty/falsy, returns a **fixed canned dict** without calling the AI at all: `{"overall_status": "PASS", "summary": "No mismatches were found. The P&ID and Excel line list are consistent.", "issue_count": 0, "issues": [], "manager_message": "The consistency check passed. No action is required for the tested P&ID and line list."}`.

**Schema (defined inline, not shared with `src/framework`):** `CONSISTENCY_EXPLANATION_SCHEMA` — `required: [overall_status, summary, issue_count, issues, manager_message]`, `additionalProperties: False`. `overall_status` enum `PASS|FAIL`. Each issue requires `line_no, field, problem, likely_impact, recommended_action` (all non-empty strings), `additionalProperties: False`.

**Prompt construction:** `CONSISTENCY_EXPLAINER_SYSTEM_PROMPT` (short, fixed): the deterministic mismatch list is the source of truth; do not invent new mismatches; do not remove any mismatch; keep explanation professional/concise/plain-English; focus on what's wrong, why it matters, what to check manually; JSON only. The **user** prompt is simply: `"Explain these AutoCAD/P&ID consistency mismatches in plain English.\n\nMismatch data:\n{json.dumps(mismatches, indent=2)}"`.

**Call into `ask_ai`:** `ask_ai(prompt=prompt, schema=CONSISTENCY_EXPLANATION_SCHEMA, system_prompt=CONSISTENCY_EXPLAINER_SYSTEM_PROMPT)` — **no `max_retries` or `max_tokens` override** (both default: `max_retries=1`, `max_tokens=800`), same "minimal defaults" pattern as `symbol_planner.py`.

**Validation:** **None** — returns `ask_ai(...)`'s result directly with no `setdefault`/`validate_*` call, same as `symbol_planner.py`. Relies entirely on `ask_ai`'s internal schema enforcement.

**Callers:** `src/api/routes/consistency.py` (`consistency_check` route), only when `request.use_ai_explanation` is true; result is passed to `src/use_cases/consistency_check_ai.write_ai_outputs` to persist JSON/TXT report files.

**Tests:** **No dedicated test file** (`test_consistency_explainer.py` is not in the required test list and none exists under `tests/framework/`). A scratch script `src/scratch/test_consistency_explainer.py` exists but is not part of the `pytest` suite. **Third major test-coverage gap** in this layer (alongside `symbol_planner.py` and `vessel_planner.py`).

---

## 4. The generator → verifier → repairer → orchestrator pipeline

### 4.1 Non-chunked pipeline (`command_orchestrator.generate_verified_command_sequence`)

Exact control flow (from reading `src/ai/command_orchestrator.py` line by line):

1. **Preconditions:** empty `user_request` → `ValueError`; `max_repair_attempts < 0` → `ValueError`.
2. **Initial generation:** calls `generate_commands(clean_request)` (→ `command_generator.py`, itself one `ask_ai` call with `max_retries=2` baked in). If this raises for **any reason**, records a `repair_history` entry with `reason="schema_validation_failed"` and, if `repair_attempts_used < max_repair_attempts`, spends **one** repair attempt calling `repair_command_sequence(clean_request, bad_output=str(exc), validation_errors=[error_message])` — note `bad_output` here is the **exception message as a string**, not a partial JSON dict, since generation failed before any dict existed. If repair itself raises, wraps in `CommandOrchestrationError("Command repair failed: ...")`. If no repair attempts remain, raises `CommandOrchestrationError(error_message)` immediately without even trying repair.
3. **Main loop** (runs until `break` or an exception propagates):
   a. `validate_command_sequence(command_sequence)` (deterministic, `src/framework/commands/schema.py` — pure JSON Schema + custom checks, no AI). If errors: record history (`reason="schema_validation_failed"`), and if attempts remain, repair via `_repair_for_schema_errors` (which calls `repair_command_sequence(user_request, bad_output=command_sequence, validation_errors=validation_errors, previous_command_sequence=command_sequence)`) and `continue` the loop (re-validate the repaired output from the top — so schema-repair can loop multiple times up to `max_repair_attempts` total, shared with verifier-triggered repairs from the same counter). If no attempts remain, raises `CommandOrchestrationError` with the joined validation errors.
   b. Once schema-valid, calls `verify_commands(clean_request, command_sequence)`. **If this raises**, the orchestrator does **not** treat it as fatal — it builds a synthetic `_fallback_verifier_result(error_message)` (verdict forced to `APPROVE_WITH_NOTES`, one `WARNING`-severity issue documenting the verifier failure and recommending manual visual inspection in AutoCAD), records history (`reason="verifier_failed_fallback"`, `verdict="APPROVE_WITH_NOTES"`), and **breaks immediately** — no repair attempt is spent on a verifier crash; the schema-valid sequence is accepted as-is with a warning flag.
   c. If verification succeeds, branches on `verdict`: `APPROVE` → break (done); `APPROVE_WITH_NOTES` → break **unless** `repair_on_approve_with_notes=True` (default `False`), in which case it's treated the same as a rejection below; `REJECT` (or anything else unrecognized) → falls through to the repair branch. Records history (`reason` = `"verifier_rejected"` or `"approve_with_notes_repair"`). If no repair attempts remain, raises `CommandOrchestrationError("...not accepted by verifier...")`. Otherwise spends one attempt via `_repair_for_verifier` (`repair_command_sequence(user_request, verifier_result=verifier_result, previous_command_sequence=command_sequence)` — note: **no `bad_output`/`validation_errors` passed here**, since the sequence was already schema-valid; only verifier feedback + the previous sequence are given) and loops back to step (a) to re-validate the repaired sequence's schema before re-verifying.
4. **Return:** `{"ok": True, "command_sequence", "verifier_result", "verifier_verdict", "repair_attempts_used", "repair_history"}`.

**Retry/repair budget:** a **single shared counter** `repair_attempts_used`, bounded by one `max_repair_attempts` parameter (default 2), covers *both* schema-repair and verifier-repair attempts combined — i.e. one bad schema repair "spends" the same budget as one verifier-rejection repair, they are not separately budgeted. Each individual `repair_command_sequence` call internally has its **own** `ask_ai(max_retries=2)`, so the true worst-case LLM call count for a single `generate_verified_command_sequence` invocation is roughly `(1 generation × 3 tries) + (max_repair_attempts × 3 tries per repair) + (max_repair_attempts+1 verifications × 3 tries each)`.

**Failure modes (all become `CommandOrchestrationError`, imported/re-exported from this module):** generation failure with no repair budget; repair call itself raising; schema-invalid after exhausting repairs; verifier `REJECT`/`APPROVE_WITH_NOTES`(when `repair_on_approve_with_notes`) after exhausting repairs. **Verifier call failure itself is explicitly NOT a failure mode** — it degrades gracefully to `APPROVE_WITH_NOTES` with a warning, never raises.

### 4.2 Chunked pipeline (`chunked_command_orchestrator.generate_chunked_verified_command_sequence`)

Adds **one upstream stage** before an almost byte-for-byte identical final loop:

1. `plan_drawing_tasks(clean_request, max_chunks=max_chunks)` → chunk plan (its own `ask_ai` call, `max_retries=2`, no repair loop of its own — if this fails, the whole chunked orchestration fails immediately, wrapped as `ChunkedCommandOrchestrationError("Chunked generation failed: ...")`).
2. `generate_chunked_command_sequence(clean_request, task_plan, max_repair_attempts_per_chunk=...)` → for each chunk (sorted by `priority`), `generate_commands_for_chunk` (which itself has an internal repair loop bounded by `max_repair_attempts_per_chunk`, default 1, **separate budget per chunk**) then deterministic merge (`merge_chunk_command_sequences` — no AI, just concatenation + LAYER dedup + assumption dedup). Any exception anywhere in this stage also collapses into the same `ChunkedCommandOrchestrationError`.
3. The merged sequence then goes through **exactly the same** final-stage loop as `command_orchestrator` (schema-validate → repair-on-failure bounded by `final_repair_attempts`, default 1 → `verify_commands` → repair-on-reject/notes → break-on-approve), using the **same** `verify_commands`/`repair_command_sequence` functions, just aliased under `_repair_for_schema_errors`/`_repair_for_verifier` local helpers that are functionally identical to the non-chunked orchestrator's (duplicated code, not shared — see §7).

**Why chunking exists (inferred from prompts/comments, no explicit "token limit" comment found in code, but strongly implied):** `pid_component_planner`/`cad3d_scene_planner` explicitly raise `max_tokens` to 4000–5000 (vs the 800 default) precisely because component-scene JSON for realistically-sized P&ID/3D layouts is large; `command_generator`'s system prompt caps at "1000 commands" and drawings with many valves/instruments/branches (P&ID-style) generate far more raw LINE/CIRCLE/TEXT commands than a single ~800–1000-token completion can hold reliably. `src/api/routes/sketch.py`'s `_looks_complex_prompt` heuristic (word count > 35, "p&id"/"pid" mention, ≥3 distinct equipment-vocabulary terms, quantity+component phrases like "three valves", or phrases like "layout with"/"connect"/"branches") exists specifically to **route complex-sounding prompts to the chunked path** and simple ones to the direct single-shot generator — i.e. chunking is the system's answer to "the model can't reliably emit a large, internally-consistent command sequence in one completion," decomposing the problem into independently-generated (and independently-repairable) pieces that a deterministic merge step reassembles. Each chunk's prompt is deliberately kept small (only prior chunks' *summaries*, not full command lists, are included) to keep later-chunk prompts from growing unboundedly as more chunks accumulate.

**Key structural difference in outputs:** the chunked orchestrator's `repair_history` only records **final-merge-stage** events; per-chunk repairs are invisible in `repair_history` (only their total count surfaces via `chunk_repair_attempts_used`). The chunked result additionally carries `task_plan` and `chunk_results` (full per-chunk detail, including each chunk's own command sequence) that the non-chunked result has no equivalent for.

---

## 5. P&ID and CAD3D planners vs. the generic command generator

The generic `command_generator.py` asks the LLM to emit **flat, low-level AutoCAD primitives** (`LAYER`, `LINE`, `CIRCLE`, `TEXT`, ...) directly — the LLM is effectively doing manual CAD drafting in JSON. `pid_component_planner.py` and `cad3d_scene_planner.py` instead ask the LLM to emit **semantic component objects** (`horizontal_vessel`, `gate_valve`, `pump_placeholder_3d`, ...) with engineering-meaningful fields (diameter, length, ports), and a **separate deterministic renderer** (`render_pid_component_scene_data` in `src/framework/pid/component_builder.py`; the CAD3D equivalent under `src/framework/cad3d/`) expands each component into the actual low-level primitives/COM calls. This shifts responsibility for "how do I draw a valve symbol correctly" away from the LLM (unreliable at precise geometry) onto deterministic Python code, while leaving "what equipment/topology does the user want" to the LLM (where it's comparatively strong). `cad3d_edit_planner.py` follows the same component-ID-based abstraction for edits (never touches raw AutoCAD handles).

Both `pid_component_planner.py` and `cad3d_scene_planner.py` also raise `ask_ai`'s `max_tokens` well above the 800 default (5000 and 4000 respectively) because a component scene with 8–35 components, each with several numeric/string fields, plus assumptions, is a larger JSON payload than a handful of LAYER/LINE commands.

**The "deterministic template fallback" behavior (explicitly asked about in the task):**
- **P&ID (`pid_component_planner.plan_pid_component_scene_resilient`):** on any AI-path exception, falls back to `choose_pid_component_template(user_request)` — a keyword-matching function (outside this layer, in `src/framework/pid/component_templates.py`) that picks between fixed template scenes (e.g. `horizontal_separator` for "3 phase separator"-style requests, `pump_tank` for "tank"+"pump" requests) purely from string matching on the request text, with **no LLM call involved in the fallback itself**. An assumption string documenting the fallback is appended, and rich metadata (`planner_strategy`, `fallback_used`, `fallback_reason`, `template_name`, `ai_planner_attempted`, `ai_planner_error_type`, `ai_planner_error`) is attached so callers/UI can show the user *why* a template was used instead of an AI-tailored layout. A `template_first=True` mode exists to **skip the AI call preemptively** (used, per the tests, when the caller already knows they want the deterministic path, e.g. for guaranteed-fast/guaranteed-successful demo scenarios).
- **CAD3D scene (`cad3d_scene_planner.plan_cad3d_scene_resilient`):** identical pattern via `choose_cad3d_template` (from `src/framework/cad3d/component_templates.py`), templates keyed by names like `tank_pump_separator`, `heat_exchanger_skid`. No `template_first` equivalent exists for this planner (only P&ID has that toggle).
- **CAD3D edit (`cad3d_edit_planner.plan_cad3d_edit_resilient`):** the outlier — its fallback is **not** a pre-authored template scene but a **live regex/keyword parser** (`deterministic_edit_plan_from_request`) that directly interprets the *specific edit request text* (move/delete/dimension-change) against the *current* scene's actual component IDs/tags. This makes sense because an "edit" fallback must reference the scene as it currently exists (which a static template cannot do), whereas a "generate new scene" fallback can reasonably substitute a generic canned layout.

In all three cases the fallback is designed so the **user-visible behavior degrades to "something reasonable" rather than a hard error**, and the metadata always makes the degradation legible (`fallback_used: True` plus the underlying AI exception type/message) rather than silently swapping in a template.

---

## 6. Test coverage summary

| Module | Test file | Mocking strategy | Notes / gaps |
|---|---|---|---|
| `client.py` | `test_ai_client.py` (62 ln, 2 tests) | Monkeypatches `_load_env`, `_get_provider`, `_ask_deepseek` — never touches the real `openai.OpenAI` client or `_extract_json`/`_validate_response`/`_build_system_prompt`/`_ask_deepseek`'s retry loop directly | **Gap:** no test of retry-message construction, `AIConfigError` paths (missing env vars, unsupported provider), or actual DeepSeek HTTP call shape (model, `response_format`, `temperature`, `max_tokens` args) |
| `command_generator.py` | `test_command_generator.py` (134 ln) | Monkeypatches `command_generator.ask_ai` | Solid coverage of arg-forwarding, defaulting, validation-failure. 1 live test. |
| `command_verifier.py` | `test_command_verifier.py` (150 ln) | Monkeypatches `command_verifier.ask_ai` | Solid coverage incl. precondition errors. 1 live test. |
| `command_repairer.py` | `test_command_repairer.py` (248 ln) | Monkeypatches `command_repairer.ask_ai` | Most thorough per-field prompt-content coverage (bad_output as str/dict, validation_errors, verifier_result, previous_sequence all individually asserted present in prompt). 1 live test. |
| `command_orchestrator.py` | `test_command_orchestrator.py` (315 ln) | Monkeypatches `generate_commands`, `verify_commands`, `repair_command_sequence` at the orchestrator-module level (`_patch_stack` helper) | Very thorough: every verdict branch, repair-exhaustion, verifier-crash-fallback, repair-history-shape, plus an explicit "does not import executor/AutoCAD" guard test. No live test (this module has no `RUN_LIVE_AI_TESTS` test of its own — relies on the three mocked sub-tests' own live tests). |
| `chunked_command_generator.py` | `test_chunked_command_generator.py` (362 ln) | Monkeypatches `generate_commands`, `repair_command_sequence`, `generate_commands_for_chunk` at different points | Thorough: chunk prompt content, merge ordering/dedup, priority sorting, counts. 1 live test. |
| `chunked_command_orchestrator.py` | `test_chunked_command_orchestrator.py` (430 ln) | Monkeypatches `plan_drawing_tasks`, `generate_chunked_command_sequence`, `verify_commands`, `repair_command_sequence` | Mirrors `command_orchestrator` tests + chunk-specific pass-through checks + no-executor guard. 1 live test. |
| `drawing_task_planner.py` | `test_drawing_task_planner.py` (174 ln) | Monkeypatches `drawing_task_planner.ask_ai` | Standard coverage. 1 live test. |
| `edit_generator.py` | `test_edit_generator.py` (225 ln) | Monkeypatches `edit_generator.ask_ai` | Includes the specific 100-entity truncation boundary test. 1 live test. |
| `symbol_planner.py` | **none** | — | **No test file exists.** Only ad hoc scripts under `src/scratch/` (not part of `pytest`). Biggest coverage gap. |
| `vessel_planner.py` | **none** | — | **No test file exists**, despite being the largest (619 ln) and most logically complex module (duplicate-nozzle repair, unit conversion, enum coercion). Second-biggest coverage gap. |
| `pid_component_planner.py` | `test_pid_component_planner.py` (256 ln) | Monkeypatches `pid_component_planner.ask_ai` and, separately, `pid_component_planner.plan_pid_component_scene` (for resilient-wrapper tests) | Thorough, including the `template_first` no-AI-mock-needed test. 1 live test. |
| `cad3d_scene_planner.py` | `test_cad3d_scene_planner.py` (401 ln) | Monkeypatches `ask_ai`, `plan_cad3d_scene`, and `choose_cad3d_template` (for one test) | The most exhaustive prompt-content assertions of any module in the layer. 1 live test. |
| `cad3d_edit_planner.py` | `test_cad3d_edit_planner.py` (139 ln) | Monkeypatches `ask_ai` and `plan_cad3d_edit` | Good coverage of the regex fallback's three branches (move/delete/dimension) and one negative case. **Gap:** no test for `_validate_edit_plan_references_scene`'s hallucinated-component-id rejection path. |
| `consistency_explainer.py` | **none** | — | **No test file exists.** Third coverage gap. Also the only module with an untested short-circuit (empty-mismatches canned response) and untested schema. |

**Live-AI test gating:** every test file that has one gates it via `@pytest.mark.skipif(os.getenv("RUN_LIVE_AI_TESTS") != "1", reason=...)`. This env var is **not** read anywhere inside `src/ai/` itself — it's purely a test-suite convention (checked at collection/run time by `pytest`, in the test files). By default (`RUN_LIVE_AI_TESTS` unset), **zero real DeepSeek calls happen** during `pytest` runs; essentially the entire suite validates prompt-construction, schema-enforcement, and orchestration control-flow against hand-written fake `ask_ai` substitutes, not model behavior.

---

## 7. Cross-cutting observations

**Inconsistent post-AI validation rigor across modules.** Most planners follow the pattern `result.setdefault("schema_version", ...)` → `validate_*(result)` → raise `ValueError` on failure. Three modules skip this entirely and return `ask_ai(...)`'s output unvalidated by any module-level code: `symbol_planner.py`, `consistency_explainer.py`. `vessel_planner.py` skips the "call a `validate_*` function" step specifically (by design, deferring to `validate_parameters()` in a different layer) but *does* do the most extra deterministic post-processing of any module. This inconsistency means a caller cannot assume uniform guarantees ("if this function returns without raising, the result is schema-valid") across all `src/ai/` modules — it holds for 11 of 14 non-`client.py` modules but not for `symbol_planner`/`consistency_explainer`/`vessel_planner` in the same way.

**Inconsistent `max_retries` defaults.** Every "generate a command/plan" module explicitly passes `max_retries=2` to `ask_ai`. `symbol_planner.py` and `consistency_explainer.py` both omit it, silently falling back to `client.py`'s default of `1`. Given both of these modules also skip post-validation, they read as the least-hardened / possibly-oldest modules in the layer (consistent with `symbol_planner.py`'s comment "Phase 5 will pass this JSON into the AutoCAD executor" suggesting it predates later conventions).

**Duplicated orchestration scaffolding between `command_orchestrator.py` and `chunked_command_orchestrator.py`.** `_history_entry`, `_fallback_verifier_result`, `_verifier_issue_messages`, `_repair_for_schema_errors`, `_repair_for_verifier` are defined **twice**, nearly verbatim, once per file. A shared `src/ai/_orchestration_common.py`-style module could eliminate this duplication; as written, a bug fix or behavior change to (e.g.) the fallback verifier result's wording must be applied in two places, and nothing enforces they stay in sync (they currently are byte-for-byte identical except naming of local reason strings like `"verifier_rejected"` vs `"final_verifier_rejected"`).

**Duplicated "allowed command types" list.** The literal list `LAYER, LINE, CIRCLE, ARC, ELLIPSE, POLYLINE, TEXT, INSERT, DIM_LINEAR` is spelled out in prose inside both `COMMAND_GENERATOR_SYSTEM_PROMPT` (`command_generator.py`) and `COMMAND_REPAIR_SYSTEM_PROMPT` (`command_repairer.py`), independently of the actual authoritative `_COMMAND_TYPES` list in `src/framework/commands/schema.py`. If the framework schema ever adds/removes a command type, both prompt strings must be manually updated to match or the LLM will be told an inaccurate allow-list.

**Inconsistent fallback-flag naming between structurally identical planners.** `pid_component_planner.plan_pid_component_scene_resilient` takes `allow_template_fallback`; `cad3d_scene_planner.plan_cad3d_scene_resilient` takes `allow_example_fallback` for the conceptually identical "should I fall back to a canned deterministic scene" toggle. The CAD3D version's metadata additionally sets **both** `fallback_template_name` and `fallback_example_name` to the same value — apparently to satisfy two different naming conventions used by different callers/tests rather than because they mean different things (confirmed by reading `cad3d.py`'s route code, which reads `fallback_template_name or fallback_example_name` defensively on both fields). This looks like an artifact of the CAD3D module being renamed/refactored (from "example" to "template" terminology) without fully cleaning up the older name.

**`cad3d_edit_planner.py`'s two-tier schema validation is the strongest pattern in the layer and is not replicated elsewhere.** It (a) gives `ask_ai` a deliberately loose schema (`CAD3D_EDIT_PLAN_SCHEMA`, `additionalProperties: True`) so the JSON-mode system prompt doesn't need to enumerate every operation-type-specific field combination, then (b) re-validates strictly via the framework's `validate_cad3d_edit_plan`, and (c) additionally checks referenced component IDs actually exist in the live scene (`_validate_edit_plan_references_scene`). No other planner in the layer does step (c) — e.g. `edit_generator.py`'s system prompt tells the LLM "never invent handles that are not in the provided entity list" but there is no code-level check enforcing this for AutoCAD-handle edits the way `cad3d_edit_planner.py` enforces it for CAD3D component-ID edits. This is a real robustness gap: a hallucinated handle in `edit_generator.py`'s output would only be caught later, at COM-execution time in the framework/executor layer (outside this layer's scope, not verified by this review), rather than immediately after the AI call.

**Retry semantics inside `client.py` are message-list-accumulating but do not resend the model's own bad reply.** Each failed attempt appends only a new **user** corrective message, never the assistant's previous (bad) response as an `assistant` message. This means on retry, the model sees: system prompt, original user prompt, then a chain of "your previous response failed, try again" user messages — but never literally sees what it previously output. This is a reasonable token-saving choice (avoids re-sending potentially huge malformed JSON) but means the model cannot "see its own mistake" the way a typical multi-turn repair conversation would; it must re-derive the same output from scratch guided only by the error type/message string, which may make retries less effective at fixing subtle field-level errors than a "here's what you said, here's what's wrong with it" framing would be.

**No explicit request timeout anywhere in `src/ai/`.** `client.py` never passes a `timeout=` to `OpenAI(...)` or `.create(...)`; if DeepSeek hangs, the whole call chain (up through orchestrators with their multi-attempt retry loops) can block for however long the underlying `httpx`/`openai` SDK default timeout is, with no layer-specific override. Given orchestrators can trigger multiple sequential `ask_ai` calls (generate, verify, repair×N), a slow/hanging DeepSeek endpoint could make a single `/api/sketch/generate` HTTP request take a very long time with no layer-level circuit breaker.

**`plan_vessel`'s duplicate-nozzle repair logic (`_repair_duplicate_nozzle_locations`) is bespoke, non-trivial, and completely untested** (no `test_vessel_planner.py` exists). It contains real algorithmic logic — candidate-position search with an 8-candidate shortlist falling back to a 250mm linear scan, special-cased relief-valve terminology detection — that would benefit most in this entire layer from unit tests, since it's the single largest chunk of hand-written (non-LLM-delegated) decision logic in `src/ai/`.

**Inconsistent whitespace/`.strip()` handling of `drawing_style` defaults.** `pid_component_planner.plan_pid_component_scene` and `cad3d_scene_planner.plan_cad3d_scene`/`plan_cad3d_scene_resilient` both do `drawing_style.strip() if drawing_style else "<default>"` — but if `drawing_style` is passed as an all-whitespace string (e.g. `"   "`), `.strip()` never runs because the truthiness check `if drawing_style` is `True` for a non-empty-but-blank string, so the resulting stripped value would be `""`. This edge case (blank-but-non-empty `drawing_style`) is not covered by any test and would silently produce an empty-string `drawing_style` value threaded into the prompt rather than falling back to the documented default.

**Module-level "does not import AutoCAD/executor" guard tests exist only for the two orchestrators**, not for any other module (e.g., no equivalent guard test exists for `command_generator.py`, `pid_component_planner.py`, etc., even though the same "this layer never touches AutoCAD" invariant is claimed in every module's docstring). This means the invariant is only mechanically enforced for 2 of 14 modules; for the rest it's documentation-only.
