# Module 2: Schema Contamination

## The bug

`docs_analysis/10_project_extension_review.md`, Tier 1 item 1, flagged that
`src/framework/commands/schema.py` mutated *shared, module-level* objects — the
`COMMAND_SCHEMA` dict and the `_COMMAND_TYPES` list — at **import time**, splicing in the
5 new structured-operation command types (`RESIZE_COMPONENT`, `SET_ENTITY_PROPERTY`,
`SET_DOCUMENT_PROPERTY`, `SET_LAYER_COLOR`, `RENAME_FILE`) that are defined
independently in `src/framework/commands/operation_schema.py`. The review's "Round 2"
section notes this exact root cause was found three separate times by three independent
investigations (two Round‑1 review agents using different methods, plus Codex's own
separate self-audit reasoning from the executor's runtime error message) — "about as
high-confidence as a finding gets without a live production incident."

What made it insidious rather than merely wrong is the *chain of shared references* it
poisoned, none of which was obvious from reading any single file in isolation:

1. `_COMMAND_TYPES` isn't just a local list — it's embedded **by reference** inside
   `COMMAND_SCHEMA["properties"]["commands"]["items"]["properties"]["command"]["enum"]`
   (`schema.py:92`). Appending to it in place therefore silently widened the
   already-built `COMMAND_SCHEMA` object too, without re-assigning anything.
2. `src/framework/commands/edit_schema.py:14,24,73` imports `COMMAND_SCHEMA` and takes
   a `deepcopy` of it (and of its `definitions`) at import time to build its own
   `EDIT_PLAN_SCHEMA`. Because the deepcopy happens *after* `schema.py`'s module body
   has already run the splice, the copy captured the contaminated schema — the leak
   propagated into a second, seemingly-unrelated file with no explicit coupling in its
   own code.
3. `src/ai/client.py` serializes the full JSON schema verbatim into every LLM system
   prompt. So the **pre-existing, legacy** sketch/edit-generation AI flows
   (`/api/sketch/generate`, `command_repairer.py`, `/api/autocad/edit`) ended up being
   told by their own prompt that all 5 new operation types were valid outputs for a
   plain creation/edit command sequence — even though the legacy executor
   (`src/framework/commands/executor.py`) has no dispatch entry for any of them and
   would reject them at runtime with `CommandExecutionError: Unsupported command type:
   ...`. No unsafe execution resulted, but it silently weakened "schema validation is a
   hard gate" for code nobody had touched, and a test in the suite
   (`test_command_schema_accepts_structured_operation_and_requires_target`) had
   actually been asserting this contaminated behavior as if it were correct, so the
   test suite itself provided no signal that anything was wrong.

## The fix

**`src/framework/commands/schema.py`** (diffed against the pre-fix version): removed
the module-level splice loop that used to sit immediately above
`_VALIDATOR = Draft7Validator(COMMAND_SCHEMA)` (now around line 355 after the added
comment). The removed code was:

```python
from .operation_schema import OPERATION_SCHEMA, OPERATION_VARIANTS, validate_operation

for _variant in OPERATION_VARIANTS:
    _name = _variant["properties"]["command"]["const"]
    _COMMAND_TYPES.append(_name)
    COMMAND_SCHEMA["properties"]["commands"]["items"]["allOf"].append({
        "if": {"properties": {"command": {"const": _name}}, "required": ["command"]},
        "then": _variant,
    })
```

It was replaced with a comment (lines ~341-353) explaining exactly why this must never
be reintroduced: mutating either shared object leaks the operation types into every
downstream consumer of `COMMAND_SCHEMA`/`_COMMAND_TYPES`, including the AI prompts. The
`from .operation_schema import ...` line was removed along with it, since nothing else
in `schema.py` uses `OPERATION_SCHEMA`, `OPERATION_VARIANTS`, or `validate_operation`.

Removing it is safe because nothing legitimately depended on the splice:
- `src/framework/commands/operation_schema.py` is fully self-contained. It defines its
  own `OPERATION_VARIANTS`/`OPERATION_SCHEMA`/`OPERATION_TYPES`, builds its own
  `Draft7Validator(OPERATION_SCHEMA)` inline inside `validate_operation()`, and does not
  import anything from `schema.py`. Confirmed by reading the file in full — it has no
  reference to `COMMAND_SCHEMA` or `_COMMAND_TYPES` anywhere.
- `src/framework/commands/modification_executor.py:14` imports `validate_operation`
  directly from `.operation_schema`, never through `schema.py`. So the real dispatch
  path for the 5 structured-operation types (`modification_executor.py`) was never
  relying on the splice either — it already used the separate, correct schema.
- `edit_schema.py` still legitimately derives from `COMMAND_SCHEMA` for the *legacy*
  command types (`LAYER`, `LINE`, `CIRCLE`, `ARC`, `ELLIPSE`, `POLYLINE`, `TEXT`,
  `INSERT`, `DIM_LINEAR`) — that part of the sharing is intentional and untouched; only
  the operation-type splice into the shared objects was removed.

Note: the same diff to `schema.py` also adds an optional `"tag"` property
(`_TAG_PROPERTY`, defined at line 49) to several per-command-type definitions
(`line_command`, `circle_command`, `arc_command`, `ellipse_command`,
`polyline_command`, `insert_command`). That is a separate, unrelated change from a
different fix ("Module 1: P&ID Component Identity") landed in the same working
session and is not part of this record.

**`tests/project/test_modification.py`**: the test
`test_command_schema_accepts_structured_operation_and_requires_target` had been
asserting the buggy behavior as correct — it asserted `validate_command_sequence`
(the legacy schema validator) *accepted* a `RESIZE_COMPONENT` command inside a plain
command envelope. It was renamed to `test_legacy_command_schema_rejects_structured_operations`
and rewritten to assert the opposite: `validate_command_sequence(envelope) != []` (the
legacy path now rejects it), while separately confirming the *correct* path,
`validate_operation` from `operation_schema.py`, still validates the same
`RESIZE_COMPONENT` operation correctly — accepting it with `target_dwg_path` present
and raising `jsonschema.ValidationError` when it's removed. A docstring was added
explaining the regression and pointing at `schema.py`'s comment for the rationale.

## How it's proven

Reproduction, run against the actual current code (`.\venv\Scripts\python.exe`, from
the repo root):

```python
from src.framework.commands.schema import COMMAND_SCHEMA, _COMMAND_TYPES, validate_command_sequence
from src.framework.commands.edit_schema import validate_edit_plan
print('COMMAND_TYPES:', _COMMAND_TYPES)
seq = {'schema_version':'1.0','summary':'x','assumptions':[],'commands':[{'command':'RESIZE_COMPONENT','target_dwg_path':'x','handle':'A','dimension':'length','delta_mm':5}]}
print('seq errors:', validate_command_sequence(seq))
edit = {'schema_version':'1.0','edit_intent':'x','summary':'x','assumptions':[],'delete_handles':[],'commands':[{'command':'RESIZE_COMPONENT','target_dwg_path':'x','handle':'A','dimension':'length','delta_mm':5}]}
print('edit errors:', validate_edit_plan(edit))
```

Real output:

```
COMMAND_TYPES: ['LAYER', 'LINE', 'CIRCLE', 'ARC', 'ELLIPSE', 'POLYLINE', 'TEXT', 'INSERT', 'DIM_LINEAR']
seq errors: ["root.commands[0].command: unknown command type 'RESIZE_COMPONENT'. Allowed command types: LAYER, LINE, CIRCLE, ARC, ELLIPSE, POLYLINE, TEXT, INSERT, DIM_LINEAR."]
edit errors: ["root.commands[0].command: unknown command type 'RESIZE_COMPONENT'. Allowed command types: LAYER, LINE, CIRCLE, ARC, ELLIPSE, POLYLINE, TEXT, INSERT, DIM_LINEAR."]
```

`_COMMAND_TYPES` now contains only the original 9 legacy creation types, and both the
legacy command-sequence validator and the edit-plan validator correctly reject
`RESIZE_COMPONENT` with a non-empty error list (rejection), matching the expected
post-fix behavior exactly.

Test suite:

```
.\venv\Scripts\python.exe -m pytest tests/project/test_modification.py -q
```

Real result: **20 passed**, 7 warnings (all pre-existing `PyparsingDeprecationWarning`s
from `ezdxf`'s query parser, unrelated to this change), in 10.66s.

## Discrepancies found

None. Every claim in the implementing agent's description matched the actual code:
- The removed hunk in `schema.py` is exactly the splice loop described, located
  immediately above `_VALIDATOR = Draft7Validator(COMMAND_SCHEMA)`, replaced with an
  explanatory comment.
- The `"tag"` property additions in the same diff are confirmed to be the separate,
  unrelated Module 1 fix, correctly excluded from this record.
- `operation_schema.py` is confirmed fully self-contained (own variants, own schema,
  own validator instance, own `validate_operation`), with no dependency on `schema.py`.
- `modification_executor.py:14` confirmed to import `validate_operation` directly from
  `.operation_schema`, not from `schema.py`.
- `edit_schema.py:14,20,24,73` confirmed to derive `EDIT_PLAN_SCHEMA` from a `deepcopy`
  of `COMMAND_SCHEMA`'s `commands` sub-schema and `definitions` at import time, and to
  reference `_COMMAND_TYPES` transitively via `COMMAND_SCHEMA`'s embedded `enum` — this
  is the precise mechanism that let the contamination in `schema.py` reach the edit-plan
  schema too.
- The test rename/rewrite in `test_modification.py` matches the description exactly,
  including the new docstring and the `pytest.raises(ValidationError)` assertion for the
  missing-target case.
