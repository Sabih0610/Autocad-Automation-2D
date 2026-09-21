# Target Architecture

## The end-state shape

```
                              Chatbot / API
                                    │
                                    ▼
                          AI Agent (planner only)
                                    │
                                    ▼
                          Project Orchestrator
                                    │
                                    ▼
                                 SQLite
             ┌──────────┬──────────┼──────────┬──────────────┐
             │          │          │          │              │
         projects   drawings   entities  relationships  spatial index
             │                                                │
             └──────────────────────┬─────────────────────────┘
                                     │
                       ┌─────────────┴─────────────┐
                       ▼                            ▼
              Offline Scanner (parallel)     CAD Execution Layer (serialized)
              DrawingExtractor: DXF path      DrawingExtractor: COM path
                       │                            │
                  (no AutoCAD needed)                ▼
                                                  AutoCAD
                                                     │
                                                     ▼
                                          ChangeSet → KEEP / REVERT
```

This is the architecture that emerged from cross-checking multiple independent proposals against
the actual codebase (see [08_com_vs_dotnet_decision.md](08_com_vs_dotnet_decision.md) for how the
execution-layer question specifically was resolved). It is additive to the existing app, not a
replacement of it.

## The five governing rules

### 1. AI only plans — this is already true today, and must stay true

Every module under `src/ai/` already documents that it never touches AutoCAD, never executes
anything, never renders previews (confirmed by reading every file in that directory). Every new
capability in this roadmap — metadata queries, structured edits, multi-file operations — extends
this same rule rather than bending it. The AI's output is always a small, schema-validated object
(a query result to act on, or an operation to perform); it is never raw geometry the AI computed
itself, and it never makes a live AutoCAD call itself.

### 2. Only the top of the stack is "agentic" — everything else stays plain code

```
AGENTIC (touches an LLM):        Main Agent → Planner → Project Orchestrator

DETERMINISTIC (plain code):      Extractor · Geometry Engine · Relationship Resolver
                                  Executor · Validator · Change Manager · File Manager
```

No per-file agents. No "extractor agent" / "validator agent" / "worker agent." One AI planning
call determines *what* needs to happen and *which* files are affected; everything after that is
ordinary, testable Python — exactly the pattern the sketch/P&ID/CAD3D pipelines already use today
for generation, just extended to cover metadata and editing too.

### 3. Reads and writes are architecturally different operations

- **Reads (metadata extraction)** never need to touch AutoCAD, and should not. Parallelizes
  freely across OS processes.
- **Writes (actual edits)** go through the one live AutoCAD COM session, explicitly targeted by
  file path. This is a single-consumer queue, not a worker pool, until there's a load-bearing
  reason (multiple licensed AutoCAD instances, or a `.NET` in-process engine) to make it
  otherwise.

Never open more files than an operation actually needs.

### 4. The execution backend sits behind one interface

Everything above the `DrawingExtractor` interface (SQLite schema, orchestrator, AI planner) never
knows or cares whether a given piece of data came from parsing a DXF file, from live COM, or
(later) from a `.NET`-in-process reader. This is what makes it safe to defer the COM-vs-.NET
decision without painting the rest of the system into a corner. See
[04_drawing_extractor_design.md](04_drawing_extractor_design.md).

### 5. Every mutation is a ChangeSet

Generate → Approve already exists as a pattern in this codebase (sketch, P&ID, CAD3D, vessel each
have their own version of it) — but the four implementations already disagree on token lifetime,
eviction, and what "revert" even means. This roadmap generalizes it into one shared mechanism:
preview → keep or revert, backed by the existing `src/backup.py` and `src/logging/jobs.py`
machinery rather than four bespoke per-workflow caches. See
[07_changeset_and_revert.md](07_changeset_and_revert.md).

## What stays exactly as it is

Nothing about `src/ai/`'s existing planners, `src/framework/cad3d/components/`, `routing.py`, the
JSON-schema validation pattern, the deterministic P&ID renderer, FastAPI, or the SQLite
audit trail needs to change to build any of this. This roadmap is additive: a new persistence
layer, a new extraction abstraction, new structured-operation command types, and a generalized
changeset mechanism, layered on top of what already works.
