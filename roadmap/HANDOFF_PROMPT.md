You are joining an existing project called "AutoCAD AI Automation" — a local Windows FastAPI
app (Python) that uses an LLM (DeepSeek, via an OpenAI-compatible API) to help drive AutoCAD
through `pywin32` COM automation. It already generates 2D sketches, P&ID diagrams, and 3D
piping/equipment scenes from natural-language prompts. Your job is to extend it with: precise
in-place editing (not delete-and-redraw), metadata extraction across many files, multi-project
support, and a generalized preview/keep/revert mechanism — following a roadmap that was already
designed and agreed on in a long architecture discussion. You are not starting from a blank
slate and you are not being asked to design this from scratch — you're implementing an
already-settled plan.

## Read these first, in this exact order, before writing any code

1. `docs_analysis/00_overview.md` — how the existing app is built, and the one principle that
   explains almost everything about it: **AI only ever produces schema-validated JSON; a
   completely separate deterministic layer is the only code allowed to call AutoCAD via COM.**
   This principle is non-negotiable and every module you write must follow it.
2. The rest of `docs_analysis/` (files 01 through 09) as needed — it's a complete, verified,
   file-by-file reference to the current codebase. Don't re-derive what's already documented
   there; read the relevant file before touching a subsystem.
3. `roadmap/00_why_and_goals.md` through `roadmap/09_implementation_roadmap.md`, in numeric
   order. This is the plan you are implementing. `roadmap/09_implementation_roadmap.md` is the
   actual task list — start at Step 1.

## Non-negotiable constraints

- **Do not introduce `.NET`/C# or any other new language/runtime.** This was extensively
  debated and deliberately deferred — see `roadmap/08_com_vs_dotnet_decision.md`. Stay on Python
  + `pywin32` COM for every step in `roadmap/09_implementation_roadmap.md`. If you genuinely
  believe you've hit the specific, narrow condition that would justify revisiting this (full
  associative parametric constraint manipulation, or a *measured* — not guessed — COM
  performance bottleneck), stop and say so explicitly rather than silently introducing a second
  runtime.
- **Do not turn every module into an AI agent.** Only one thing in this whole system should ever
  call an LLM: the planning step (`Main Agent → Planner → Project Orchestrator`, per
  `roadmap/02_target_architecture.md`). The extractor, geometry engine, relationship resolver,
  executor, validator, and change manager are all plain, deterministic, testable Python — no
  exceptions. If you find yourself wanting to "just ask the AI" to decide something a
  deterministic function could decide instead, don't.
- **The AI never computes geometry and never calls AutoCAD directly.** It receives a small,
  specific piece of data (one entity record, not a drawing dump) and returns a small, structured
  operation object. Deterministic code computes any derived values and performs any AutoCAD call.
- **Extend existing, working, tested code — don't replace it.** `src/logging/db.py` (already
  WAL-mode SQLite, already tested), `src/backup.py`, `src/framework/commands/executor.py`'s
  `target_dwg_path` pattern, and the existing sketch/P&ID/CAD3D/vessel pipelines all continue to
  work exactly as they do today. New tables go in the same `jobs.db` database. New extraction
  logic sits behind the `DrawingExtractor` interface (`roadmap/04_drawing_extractor_design.md`)
  rather than modifying the existing single-document inspector in place — extend it, don't
  break its current callers.
- **Reads and writes are architecturally different.** Metadata extraction (reading many files)
  should never open AutoCAD and is safe to parallelize. Actual edits go through the one live
  AutoCAD COM session, explicitly targeted by file path, and are effectively single-threaded.
  Do not build a "worker pool" that opens multiple documents in AutoCAD expecting real
  concurrency — see `roadmap/06_multi_project_and_scanning.md` for why that doesn't work the way
  it looks like it should.
- **Every existing test must keep passing.** Run the full suite
  (`.\venv\Scripts\python.exe -m pytest tests/ -q`) before and after each step. It currently
  passes at 892 passed / 10 skipped / 0 failed — treat any regression as a stop-and-fix, not
  something to note and move past.
- **Work one step of `roadmap/09_implementation_roadmap.md` at a time.** Each step has an
  explicit "definition of done" — don't start step 3 before step 2's definition of done is real
  and demonstrated. Don't jump ahead to step 6 (structured edits) or step 9 (the COM/.NET
  decision) because it seems more interesting than step 1 (project registration).

## Your first concrete task

Implement **Step 1** of `roadmap/09_implementation_roadmap.md`: create the new SQLite tables
from `roadmap/03_sqlite_schema.md` inside the existing `jobs.db`, following the connection
pattern already used in `src/logging/db.py`, and build a minimal `project_repository.py` that
can register a project (name + root folder path) and list registered projects back out. Write
tests for it in the same style as the existing test suite under `tests/`. When that's done and
demonstrated, stop and report back before moving to Step 2 — don't self-chain through the whole
roadmap in one pass.

## If anything in the roadmap conflicts with what you find in the real code

The roadmap was written by reading the codebase carefully, but code may have changed since. If
you find a `roadmap/*.md` claim doesn't match what's actually in `src/`, trust the code, flag the
discrepancy explicitly, and proceed with what's actually there — don't silently follow a stale
instruction.
