# Current-State Gap Analysis

Every goal in [00_why_and_goals.md](00_why_and_goals.md), mapped to the exact current-code reason
it doesn't work today. Everything in the "Root cause" column was confirmed by reading the actual
source (not assumed) — file:line references are given where useful. Full detail on each file is
in [../docs_analysis/](../docs_analysis/).

| Goal | Current capability | Root cause | Files involved |
|---|---|---|---|
| Precise edits / resize | Edits exist, but only as **delete the old entity, add a new one** | Design choice in the edit-planning/execution code, **not a COM limitation** — COM entities support in-place property assignment (`entity.EndPoint = newPoint`) today, nothing here requires a platform change | `src/ai/edit_generator.py`, `src/framework/commands/edit_executor.py` |
| Metadata extraction (one file) | Exists, but narrow and **hardcoded to whatever document is currently active** | `inspect_active_drawing()` calls `acad.ActiveDocument` directly with no way to target a specific file | `src/framework/autocad/inspector.py:228` |
| Metadata extraction (many files) | Doesn't exist | No offline scanner, no persistent index of drawing contents beyond the `jobs.db` audit trail (which logs *requests*, not drawing *contents*) | (net-new) |
| Document names / rename | Doesn't exist | No filesystem-level rename operation anywhere in the app | (net-new) |
| Header / layer colors | Doesn't exist | The command schema only defines geometry-*creation* types — `LAYER, LINE, CIRCLE, ARC, ELLIPSE, POLYLINE, TEXT, INSERT, DIM_LINEAR` — there is no "set a property on an existing thing" command type at all | `src/framework/commands/schema.py` |
| Multiple projects | Doesn't exist | The whole app assumes **one** active AutoCAD document and, for CAD3D, one "latest scene." Even within that single-project assumption, CAD3D already has two independent, inconsistent caches (`CAD3DSceneStore` and a separate `_CAD3D_CACHE` dict with no TTL) that would both need to migrate into any real project hierarchy | `src/api/routes/cad3d.py`, `src/framework/cad3d/scene_store.py` |

## Two things that already exist and are easy to miss

- **`execute_command_sequence`/`execute_commands` already accept an optional `target_dwg_path`**
  and will call `acad.Documents.Open(str(target_dwg_path))` to explicitly open/target a specific
  file (`src/framework/commands/executor.py:391-399`) — this is more capable than the inspector.
  The chat UI simply never passes it, so every current workflow falls through to
  `ActiveDocument` anyway. Extending the inspector to accept the same parameter, and having every
  caller pass an explicit path, is a small, high-value fix.
- **The token-cost problem is a data-modeling problem, not a COM problem.** `edit_generator.py`
  serializes up to `MAX_PROMPT_ENTITIES = 100` entities into every AI prompt so the model can
  "see" the drawing and pick a target. That cost is identical no matter which API produced the
  entity list — the fix is a SQLite index the AI can query for *one* relevant entity, not a
  platform change. See [05_structured_operations_and_editing.md](05_structured_operations_and_editing.md).

## The one thing to internalize about scale

There is exactly **one** running AutoCAD process and **one** COM automation channel to it — even
if 100 documents happen to be open simultaneously (AutoCAD's MDI does allow this), every COM call
is processed strictly one at a time, in the order issued. This is true whether the call targets
`ActiveDocument` or an explicitly opened path. So:

- **Reading/extracting metadata from many files should never go through AutoCAD/COM at all** —
  parsing DXF directly (via `ezdxf`, already a pinned dependency, converting DWG→DXF with the
  free ODA File Converter where needed) has no such serialization bottleneck and is safely
  parallelizable across OS processes.
- **Writing/editing is inherently serialized** on the one live AutoCAD session — the fix for
  scale here isn't "more workers," it's "only open the handful of files an operation actually
  needs, explicitly by path, never by relying on whatever's currently active."

Full detail on this specific point in [06_multi_project_and_scanning.md](06_multi_project_and_scanning.md).
