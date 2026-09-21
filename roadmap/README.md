# Roadmap — What To Build Next, And Why

This folder documents a multi-round architecture discussion about evolving this project from
"generates 2D/3D drawings" into "manages metadata, edits, and changes across many drawings and
many projects." It is a **plan**, not a description of existing code — for that, see
[../docs_analysis/](../docs_analysis/), which documents the current codebase file-by-file and is
assumed as prior knowledge by every file here.

**If you are an AI picking this up cold, read [HANDOFF_PROMPT.md](HANDOFF_PROMPT.md) first** — it
tells you what to read, in what order, and the non-negotiable constraints this plan operates under.

## Reading order

| File | Contents |
|---|---|
| [00_why_and_goals.md](00_why_and_goals.md) | The original problem statement and the guiding principles that constrain every decision below |
| [01_current_state_gap_analysis.md](01_current_state_gap_analysis.md) | Each goal mapped to its exact current-code root cause |
| [02_target_architecture.md](02_target_architecture.md) | The settled end-state architecture and its five governing rules |
| [03_sqlite_schema.md](03_sqlite_schema.md) | Concrete database schema (projects, entities, relationships, spatial index, changesets) |
| [04_drawing_extractor_design.md](04_drawing_extractor_design.md) | The extraction abstraction and its three implementations |
| [05_structured_operations_and_editing.md](05_structured_operations_and_editing.md) | Replacing delete-and-recreate edits with in-place property modification |
| [06_multi_project_and_scanning.md](06_multi_project_and_scanning.md) | Project registration, offline scanning, and the read/write parallelism split |
| [07_changeset_and_revert.md](07_changeset_and_revert.md) | Generalizing generate→approve into ChangeSet + KEEP/REVERT |
| [08_com_vs_dotnet_decision.md](08_com_vs_dotnet_decision.md) | The full COM-vs-.NET decision framework, resolved |
| [09_implementation_roadmap.md](09_implementation_roadmap.md) | The numbered build order, mapped to concrete files |
| [HANDOFF_PROMPT.md](HANDOFF_PROMPT.md) | Ready-to-paste prompt for the AI that will implement this |

## The one-sentence summary

Keep everything about this project that already works (Python, FastAPI, `pywin32` COM, the
AI-plans/deterministic-code-executes split, SQLite audit logging); add a persistent multi-file
metadata index, a real project concept, structured in-place edits instead of delete-and-recreate,
and a generalized changeset/revert mechanism — and defer any platform change (.NET, Plant 3D SDK)
until steps 1-8 are built and real evidence says it's needed.
