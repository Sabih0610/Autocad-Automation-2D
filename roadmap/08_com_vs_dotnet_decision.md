# COM vs .NET — The Decision, Resolved

This question was debated at length, across multiple independent proposals and corrections. This
file is the final, settled answer — read it once and treat it as closed until steps 1-8 of
[09_implementation_roadmap.md](09_implementation_roadmap.md) are actually built and produce real
evidence otherwise.

## The verdict

**Stay on Python + `pywin32` COM. Do not introduce `.NET`/C# now.** The current project's main
missing capabilities are project indexing, multi-file scanning, structured edits, and change
management — **not** the AutoCAD API it talks through. Every gap identified in
[01_current_state_gap_analysis.md](01_current_state_gap_analysis.md) is fixable on COM.

## What COM already handles fine — verified against Autodesk's own documentation, not assumed

| Capability | Verdict |
|---|---|
| Entity properties (color, layer, linetype, endpoints, text) | COM handles this directly, in-place, today |
| XData (`GetXData`/`SetXData`) | COM reads and writes this natively — not a reason to reach for `.NET` |
| Dynamic block parameters | `GetDynamicBlockProperties()` returns structured name/value/allowed-values/units/read-only data over COM — not raw, uninterpreted junk. `.NET`'s `DynamicBlockReferencePropertyCollection` is a cleaner, strongly-typed equivalent, but not a *required* one |
| Document properties (`SummaryInfo`) | Reachable via COM |

## The one thing that's genuinely different

**Full associative parametric constraints** — the actual AutoCAD constraint *graph*
(`Assoc2dConstraintGroup`, `GeometricalConstraint`, `ExplicitConstraint`, `ConstrainedGeometry`,
`AssocVariable`, all in `Autodesk.AutoCAD.DatabaseServices`) is a managed-API-only concept. COM
exposes some dimensional-constraint *properties* (value, form, reference state) but not the full
associative graph. **This is the one legitimate, evidence-backed reason to eventually reach for
`.NET`** — and it is a narrow, checkable condition, not a vague "COM will become a bottleneck"
feeling.

Important distinction: this is **not** the same thing as this project's existing "parametric
vessel" subsystem (`src/parametric/vessel/`) — that's just numeric Python inputs driving
deterministic geometry math, with no AutoCAD-side constraint solver involved at all. Don't
conflate the two when deciding whether this condition actually applies.

## The Plant 3D / Civil 3D caveat

If this project's real-world drawings are (or become) actual **AutoCAD Plant 3D** intelligent
piping objects — not the plain `LINE`/`CIRCLE`/`TEXT` symbol primitives the P&ID subsystem
currently draws (confirmed in `src/framework/pid/symbols.py`) — then neither generic COM **nor**
generic `.NET` "AutoCAD Core" API is the right target. That would need Plant 3D's own SDK
specifically. **Settle this before finalizing anything beyond step 8** of the implementation
roadmap — but it does not block starting steps 1-8, which are identical either way.

## The decision table

| Situation | Verdict |
|---|---|
| Normal geometry/property editing (resize, recolor, rename, move) | COM is enough, starting now |
| Dynamic block parameter editing | COM is possible today; `.NET` is nicer but not required |
| Full associative parametric constraint manipulation | `.NET` becomes genuinely compelling |
| Real AutoCAD Plant 3D / Civil 3D intelligent objects | Neither COM nor generic `.NET` — needs the vertical's own SDK |

## When to actually revisit this (not before)

Only once you encounter, with real evidence rather than a guess:
- Hundreds/thousands of entity mutations needed in a single operation.
- A concrete need for scoped, all-or-nothing transactions tighter than file-level backup/restore
  provides.
- Associative/parametric constraint manipulation, confirmed present in real project files.
- Measured COM write-path latency that's actually a bottleneck, not a theoretical one.
- Confirmation that real drawings use Plant 3D/Civil 3D intelligent objects.

## If/when `.NET` is introduced

**Do not rewrite Python.** Add a thin C# AutoCAD `.NET` engine, reachable from the existing
Python/FastAPI app over a local IPC bridge (a named pipe or local socket), exposing only
`inspect`/`modify`/`transaction`/`validate`. Python keeps the AI planner, FastAPI, SQLite, and
project orchestration exactly as built in steps 1-8:

```
Python (AI + FastAPI + SQLite + Project Orchestrator)
        │
   local IPC bridge
        │
        ▼
C# AutoCAD .NET Engine (inspect / modify / transactions / validate)
        │
        ▼
     AutoCAD
```

This is implementation 3 of the `DrawingExtractor` interface
([04_drawing_extractor_design.md](04_drawing_extractor_design.md)) slotting in alongside the two
that already exist — not a redesign of anything above it.

## Why this is safe to defer

Steps 1-8 of the implementation roadmap are **identical** regardless of which of the four
outcomes above eventually applies. Deferring this decision costs nothing and avoids committing
engineering time to a second language/runtime before there's evidence it's needed.
