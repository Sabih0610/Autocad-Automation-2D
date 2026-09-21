# The DrawingExtractor Abstraction

## Why this exists

This is the single most important piece of insurance in the whole roadmap: it's what lets the
COM-vs-.NET decision (see [08_com_vs_dotnet_decision.md](08_com_vs_dotnet_decision.md)) be made
*later*, with evidence, instead of *now*, as a guess — without having to redesign anything above
it when that decision is finally made. Everything downstream (the SQLite schema, the AI planner,
the orchestrator) talks to this interface, never to a concrete implementation directly.

## The interface

```python
class DrawingExtractor:
    def extract_document(self, source) -> DocumentMetadata:
        """Document-level info: name, path, units, custom properties (SummaryInfo)."""

    def extract_entities(self, source) -> list[EntityRecord]:
        """Every entity: handle/id, type, layer, tag if present."""

    def extract_blocks(self, source) -> list[BlockRecord]:
        """Block definitions and references, including dynamic block parameters where available."""

    def extract_properties(self, source) -> dict:
        """Arbitrary key/value properties per entity — color, linetype, XData, block attributes."""

    def extract_relationships(self, source) -> list[RelationshipRecord]:
        """Connectivity/dependency: what's connected to what, what appears in what."""

    def extract_spatial_data(self, source) -> list[BoundingBox]:
        """Coordinates and bounding boxes, for the spatial index."""
```

All six methods return the same plain data shapes regardless of implementation, and all of it
lands in the SQLite schema from [03_sqlite_schema.md](03_sqlite_schema.md) the same way no matter
which extractor produced it.

## Implementation 1 — `DXFExtractor` (build this first)

- Pipeline: DWG → **ODA File Converter** (free Autodesk-partner CLI tool, scriptable, batch
  DWG↔DXF) → DXF → **`ezdxf`** (already a pinned dependency in `requirements.txt`) parses the
  DXF directly.
- **Never touches AutoCAD or COM at all.** No running AutoCAD process required, no license
  contention, no single-automation-channel bottleneck.
- Genuinely parallelizable: run N of these across N OS processes
  (`concurrent.futures.ProcessPoolExecutor`) to scan many files at once.
- This is the default path for the offline scanner (step 3 of
  [09_implementation_roadmap.md](09_implementation_roadmap.md)) and for bulk metadata extraction
  generally. It's also the fastest option available for pure reads — faster than either COM or an
  in-process `.NET` reader would be, because it skips AutoCAD entirely rather than just skipping
  the marshaling overhead.
- Known limitation: dynamic block *parameter* semantics and full parametric constraint data are
  not richly represented in DXF — acceptable for a first version; see
  [08_com_vs_dotnet_decision.md](08_com_vs_dotnet_decision.md) for when that starts to matter.

## Implementation 2 — `COMExtractor` (extends existing code)

- Wraps and extends today's `src/framework/autocad/inspector.py`, which currently only supports
  `acad.ActiveDocument` with **no way to target a specific file** (`inspector.py:228`). The fix:
  accept an explicit path and call `acad.Documents.Open(path)`, the same pattern already used by
  `src/framework/commands/executor.py:391-399`'s `target_dwg_path` parameter.
- Use this when you need **live, unsaved** state (a document open in AutoCAD with edits not yet
  saved to disk) — the one thing the DXF path structurally cannot see.
- Inherently serial: one running AutoCAD process, one automation channel, one call at a time,
  regardless of how many documents happen to be open. Do not build a "worker pool" around this
  implementation — see [06_multi_project_and_scanning.md](06_multi_project_and_scanning.md).
- COM can already reach further than it first appears: entity properties, layers/colors,
  `GetXData`/`SetXData`, and even `GetDynamicBlockProperties()` (structured dynamic-block
  parameter data — name, value, allowed values, units, read-only flag) all work over COM today.
  Don't reach for `.NET` under the assumption COM can't see this data — it can.

## Implementation 3 — `DotNetExtractor` (placeholder only — do not build yet)

Not implemented in this phase. Revisit only if real usage against real project files surfaces a
concrete need for:
- The full associative parametric constraint graph (`Assoc2dConstraintGroup`,
  `GeometricalConstraint`, `ConstrainedGeometry`) — COM exposes constraint *values* but not the
  constraint *graph*, and this is the one capability gap that's real, not assumed.
- Bulk in-process transactional edits at a scale where COM's per-call marshaling cost is a
  measured bottleneck, not a guess.

See [08_com_vs_dotnet_decision.md](08_com_vs_dotnet_decision.md) for the full decision criteria —
this file only exists so the interface has a named third slot; there is no code here yet.

## What this buys you

Once all three sit behind the same six-method interface, "should we add a `.NET` engine" becomes
a question of *adding a new implementation of an interface that already has two working
implementations* — not a redesign of the SQLite schema, the AI planner, or the orchestrator. That
is the entire point of building this now, even though only implementation 1 (and a light
extension of what's already implementation 2) is needed to start.
