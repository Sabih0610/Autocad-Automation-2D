# Structured Operations & In-Place Editing

## Kill delete-and-recreate

Today's edit path (`src/ai/edit_generator.py` + `src/framework/commands/edit_executor.py`)
represents every edit — including a resize — as "delete the old entity, add a brand-new one."
This is a **design choice**, not something COM forces on the project. COM entities support
direct, in-place property assignment on an existing object, reached via `HandleToObject(handle)`:

```text
handle = HandleToObject("2A3")
handle.EndPoint = newPoint          -- resize/move
handle.Color = newColor             -- recolor
handle.Layer = newLayerName         -- re-layer
handle.TextString = "New Name"      -- rename a text/mtext entity
blockAttribute.TextString = "..."   -- edit a block attribute (e.g. a title block field)
```

No delete, no redraw, no platform change required. This is the single highest-value, lowest-risk
fix in this entire roadmap and does not depend on anything else here being built first.

## New structured operation types

The current command schema (`src/framework/commands/schema.py`) only defines
geometry-*creation* types: `LAYER, LINE, CIRCLE, ARC, ELLIPSE, POLYLINE, TEXT, INSERT, DIM_LINEAR`.
None of them express "change a property of something that already exists." Add:

| Operation | Purpose | Executes via |
|---|---|---|
| `RESIZE_COMPONENT` | Change a dimension (length, radius, etc.) by a delta or to an absolute value | `HandleToObject` + property assignment |
| `SET_ENTITY_PROPERTY` | Change color / layer / linetype of an existing entity | same |
| `SET_DOCUMENT_PROPERTY` | Change document `SummaryInfo` fields (title, author, custom properties) | `doc.SummaryInfo` over COM |
| `SET_LAYER_COLOR` | Change a layer's color (this is very likely what "change header colors" means — confirm with the user whether they mean layer colors or a title-block header block's text/fill color specifically, since the fix differs) | `doc.Layers.Item(name).Color = ...` |
| `RENAME_FILE` | Rename the underlying `.dwg` file | pure filesystem `os.rename`/`Path.rename` — **no AutoCAD involved at all**, but the target file must not be currently open in AutoCAD or the rename will fail/corrupt state; check via the project index before attempting |

## The new AI planning contract

**Before:** `edit_generator.py` serializes up to `MAX_PROMPT_ENTITIES = 100` entities into every
prompt so the AI can "see" the drawing and guess a target. This is the actual driver of high
token cost — not which API extracted the entities.

**After:**
```
User: "Increase P-101 by 50mm"
        │
        ▼
SQLite query: "which entity has tag = 'P-101'?"
        │
        ▼
AI receives ONE entity record (handle, drawing, start/end points, connections) — not a
drawing dump.
        │
        ▼
AI emits a small structured operation:
{ "operation": "resize_pipe", "component": "P-101", "delta_length_mm": 50 }
        │
        ▼
Geometry Engine (deterministic code) computes the actual new endpoint from the delta.
The AI never computes coordinates itself — same rule the vessel subsystem already follows.
        │
        ▼
Relationship Resolver (queries the `relationships` table): does the connected valve/support/
dimension need to move too?
        │
        ▼
Validator: does the result pass basic sanity checks (no negative lengths, no new overlaps)?
        │
        ▼
Executor: HandleToObject + in-place property assignment, on the specific file(s) the SQLite
query identified — never "whatever's currently active."
```

This fixes the token-cost complaint and the resize complaint with one data-modeling change, and
it requires no platform change — it's built entirely on the existing COM path, just used
correctly (targeted by path, not by active-document guesswork; in-place, not delete/recreate).
