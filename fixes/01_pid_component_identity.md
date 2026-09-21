# Module 1: P&ID Component Identity

## The bug

`docs_analysis/10_project_extension_review.md`, Round 2, "The one thing Round 1 missed
entirely," found that P&ID components produced by this app's existing deterministic
generator (`src/framework/pid/`) carried **no recoverable identity once drawn**. A pipe
generated with `tag="P-101"` produced a plain `POLYLINE` command with no tag, XData, or
attribute anywhere the new extraction/indexing pass could read back — the only thing that
carried the string "P-101" onto the drawing at all was a separate, unlinked `TEXT` label,
and only if the caller happened to also set the distinct `label` parameter to the same
string. Round 2 called this "the highest-priority fix in the whole project," because it is
the gap between the roadmap's fixture-level "definition of done" and the feature actually
working for the real-world scenario that motivated it: generate a P&ID, then ask to resize
pipe P-101 later.

## The fix

**`src/framework/commands/schema.py`** — added a reusable `_TAG_PROPERTY = {"type":
"string", "minLength": 1}` constant (line 49) and added `"tag": _TAG_PROPERTY` to the six
geometry-creation command definitions that can act as a component's primary
identity-bearing entity: `line_command` (line 197), `circle_command` (213), `arc_command`
(237), `ellipse_command` (262), `polyline_command` (279), and `insert_command` (320).
Verified `text_command` (282-301), `dim_linear_command` (323-334+), and `layer_command`
(169-186) deliberately did **not** get a `tag` property, matching the intent that a text
label or a layer definition cannot be a component's identity-bearing entity.

(Note: this file's diff also contains a second, unrelated hunk — removal of the
`OPERATION_VARIANTS` splice into `COMMAND_SCHEMA`/`_COMMAND_TYPES` at the bottom of the
file. That is "Module 2: Schema Contamination," already documented separately in
`fixes/02_schema_contamination.md`, and is out of scope here.)

**`src/framework/commands/executor.py`** — this is where the tag actually becomes
persisted, recoverable XData:
- New module constant `TAG_XDATA_APPID = "AUTOCAD_AI_TAG"`.
- New `_ensure_tag_app_registered(doc)` — best-effort `doc.RegApps.Add(TAG_XDATA_APPID)`
  wrapped in `_com_retry` and a bare `try/except: pass`, because real AutoCAD requires an
  XData application name to be registered before `SetXData` accepts it, and re-registering
  an already-registered name should never fail the whole command.
- New `_apply_entity_tag(entity, doc, tag)` — no-ops if `entity is None` or `tag` is falsy;
  otherwise calls `entity.SetXData(...)` with group codes `(1001, 1000)` and values
  `(TAG_XDATA_APPID, f"TAG={tag}")` (built as real `win32com.client.VARIANT` arrays when
  `pythoncom`/`win32com` are importable, falling back to plain tuples otherwise).
- Every handler that creates geometry (`_execute_line`, `_execute_circle`, `_execute_arc`,
  `_execute_ellipse`, `_execute_polyline`, `_execute_insert`, plus `_execute_text` and
  `_execute_dim_linear` for signature consistency) now `return entity` instead of `None`.
  `_execute_layer` explicitly returns `None` (a layer is not a drawing entity and never
  carries tag XData).
- `_execute_one_command` gained a `doc: Any = None` parameter and now does
  `entity = handler(...); _apply_entity_tag(entity, doc, command.get("tag"))` after
  dispatch. `execute_commands`'s call site was updated to pass `doc=doc`.
- Confirmed the XData shape (`1001` app-name entry followed by a `1000` string entry
  `"TAG=<value>"`) is exactly what `src/cad/extractor/dxf_extractor.py` already recognizes
  on read: it iterates `entity.xdata.data.items()`, and for any tag with `code == 1000` and
  a string value starting with `"TAG="` (case-insensitive), takes the tag as
  `value[4:]` — see `dxf_extractor.py` lines 62-71.

**`src/framework/pid/symbols.py`** — wired the actual symbol-drawing functions to attach a
tag to their primary geometry command:
- `pipe_line_commands` gained a new optional `tag: str | None = None` parameter; when
  truthy, sets `command["tag"] = tag` on the emitted `POLYLINE` dict.
- `horizontal_vessel_commands` / `vertical_vessel_commands` now set `"tag": tag` on the
  first shell `LINE` command (these functions already required a `tag` parameter for the
  visible `TEXT` label; now the same tag is also attached as identity-bearing XData on the
  geometry itself).
- `gate_valve_commands` gained a brand-new optional `tag: str | None = None` parameter
  (didn't exist at all before this fix) attached to the first body-wedge `POLYLINE`, for
  both the `"H"` and non-`"H"` orientation branches.
- `control_valve_commands` gained the same new optional `tag` parameter and forwards it
  into its internal `gate_valve_commands(...)` call.
- `instrument_bubble_commands` now also sets `"tag": tag` on the bubble `CIRCLE` (previously
  only the `TEXT` label carried it; `tag` was already a required parameter here).

**`src/framework/pid/components/piping.py`** — `PipeRunComponent.render()` (line 76) now
calls `pipe_line_commands(self.points, tag=self.tag)` instead of
`pipe_line_commands(self.points)`.

**`src/framework/pid/components/valves.py`** — `GateValveComponent.render()` (line 57) and
`ControlValveComponent.render()` (line 80) now pass `tag=self.tag` into their respective
symbol-function calls.

Verified via `git status`/`grep` that these are the *only* two component files touched:
`src/framework/pid/components/equipment.py` (`HorizontalVesselComponent`,
`VerticalVesselComponent`) and `src/framework/pid/components/instruments.py`
(`InstrumentBubbleComponent`, `ControllerLoopComponent`) already passed `tag=self.tag`
(or `tag=self.tag or self.id`) into their symbol calls before this fix — confirmed by
`git log`/`git status` showing no modifications to those two files, and by reading their
current `tag=` call sites. Only the symbol functions themselves needed to start using the
tag they were already being given.

**`tests/project/fake_cad.py`** — extended the richer `Entity` fake used by
`test_pid_component_identity.py` and `test_modification.py`:
- `names` lookup table gained `"LWPOLYLINE": "AcDbPolyline"`.
- `__getattr__` gained a special case for `"Closed"`, returning `bool(self.entity.closed)`
  — ezdxf exposes `closed` as a real Python property on `LWPolyline`/`Polyline` (backed by
  a flag bit), not through the generic `dxf.get(...)` path every other property here uses,
  and raises `DXFAttributeError` if you try that generic path.
- `__setattr__` mirrors this with a `"Closed"` special case that sets `self.entity.closed`.
- New `SetXData(data_types, data_values)` method: unwraps `win32com.client.VARIANT`
  arguments via `.value` when present, validates the first type code is `1001`, and calls
  ezdxf's real `entity.set_xdata(appid, tags)` — so a save+reload round trip produces
  genuine XData the real `DXFExtractor` can read back, not a mocked shortcut.
- `Document.__init__` gained `self.RegApps = SimpleNamespace(Add=lambda name:
  self.data.appids.add(name))`.

**`tests/framework/test_command_executor.py`** — extended the simpler fakes used by the
executor's own unit tests:
- New module-level `_unwrap_com_array(value)` helper: returns `tuple(value.value if
  hasattr(value, "value") else value)`. Verified the underlying claim myself: pywin32's
  `win32com.client.VARIANT` is genuinely not iterable — `list(some_variant)` raises
  `TypeError: 'VARIANT' object is not iterable` — so the fake has to unwrap `.value`
  explicitly, the same way real COM marshaling would on the native side.
- `FakeEntity` gained `xdata_calls: list` and a `SetXData` method that appends
  `(_unwrap_com_array(data_types), _unwrap_com_array(data_values))`.
- New `FakeRegApps` class (`added: list`, `Add(name)` appends to it) and `FakeDocument`
  now exposes `self.RegApps = FakeRegApps()`.
- Two new tests: `test_line_with_tag_writes_recoverable_xdata` (asserts the exact XData
  call shape `((1001, 1000), (executor.TAG_XDATA_APPID, "TAG=P-101"))` and that
  `RegApps.added` contains the appid) and `test_command_without_tag_writes_no_xdata`
  (asserts `xdata_calls == []` when no `tag` is given).

## How it's proven

Ran the exact command requested:
```
.\venv\Scripts\python.exe -m pytest tests/project/test_pid_component_identity.py tests/framework/test_command_executor.py -q
```
**Result: 23 passed, 0 failed** (7 unrelated `PyparsingDeprecationWarning`s from ezdxf's
own dependency, not from this code).

`tests/project/test_pid_component_identity.py` (3 tests, all passing) is the real
end-to-end proof:
- `test_generated_pid_pipe_carries_recoverable_tag` — builds a real `PipeRunComponent`
  (`tag="P-101"`) and `GateValveComponent` (`tag="V-201"`), renders them into command
  dicts, runs them through the actual legacy `execute_commands` (same path
  `/api/sketch/approve`/`/api/pid/approve` use), backed by a fake COM layer
  (`_CreatingDocument`/`_CreatingModelSpace`) that creates *real* `ezdxf` entities and
  saves a *real* DXF file. It then re-extracts that file with the real `DXFExtractor` and
  asserts both `"P-101"` and `"V-201"` appear in the recovered tag set.
- `test_generated_pid_pipe_is_findable_by_tag` — same generation step, then registers a
  real project (`register_project`), runs the real scanner (`scan_project`), and asserts
  `find_by_tag(project, "P-101")` returns exactly one match whose `path` is the generated
  file. This is the concrete "found again by engineering tag" scenario the review
  demanded.
- `test_generated_pid_pipe_resize_is_a_documented_follow_up_gap` — generates and indexes
  the same pipe, then calls `modification_executor.execute_operation` with a
  `RESIZE_COMPONENT` / `dimension="length"` operation targeting it by handle, and asserts
  it raises `ValueError` matching `"Length resizing currently supports LINE entities"`.

`tests/framework/test_command_executor.py`'s two new tests (`test_line_with_tag_writes_
recoverable_xdata`, `test_command_without_tag_writes_no_xdata`) pin down the executor's
XData-writing behavior in isolation, independent of any PID-specific code.

## What this does NOT fix yet

This fix makes generated components **findable** by tag. It does **not** make a generated
P&ID pipe **resizable** yet. Verified by reading `_resize` in
`src/framework/commands/modification_executor.py` directly (lines 57-117): the `"length"`
dimension branch (line 66) is gated by
```python
if entity.ObjectName != "AcDbLine" or record["entity_type"] != "LINE":
    raise ValueError("Length resizing currently supports LINE entities")
```
A generated P&ID pipe renders as a `POLYLINE` (`pipe_line_commands` in
`src/framework/pid/symbols.py`), which becomes an `AcDbLWPolyline`/`AcDbPolyline` entity —
not `AcDbLine` — so it is rejected by this check today, tag or no tag. This is a real,
separate, still-open follow-up (extending `_resize` to read/write a polyline's
`Coordinates` array instead of a line's `StartPoint`/`EndPoint`), not something this fix
claims to have done.

This gap is deliberately documented and tested, not silently left broken: the third new
test, `test_generated_pid_pipe_resize_is_a_documented_follow_up_gap`
(`tests/project/test_pid_component_identity.py`), generates and correctly indexes a real
tagged pipe, then asserts that `RESIZE_COMPONENT` against it raises exactly that
`ValueError`. The test's own docstring says explicitly: "If this test starts failing
because RESIZE_COMPONENT now accepts a POLYLINE, that's progress: update/replace this test
to assert success instead of documenting the gap."

## Discrepancies found

None. Every specific claim in the implementing agent's description — the schema property
additions and their exact command types/exclusions, the `TAG_XDATA_APPID` constant and
`_apply_entity_tag`/`_ensure_tag_app_registered` helpers and their exact XData shape
(`(1001, 1000)` / `(appid, "TAG=<tag>")`), the handler-return-value refactor, the specific
symbol functions and which entity within each gets tagged, which component files needed
changes versus which already passed `tag=` through, the `fake_cad.py`/
`test_command_executor.py` test-double additions (including the `Closed`-property special
case and the `VARIANT`-is-not-iterable subtlety), the new test file's three scenarios, and
the POLYLINE-resize scope boundary with its exact error string and line number — all
matched the actual code and actual test run exactly as described.
