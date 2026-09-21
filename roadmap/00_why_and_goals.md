# Why This Roadmap Exists

## The original problem statement

The project can already generate 2D sketches, P&ID diagrams, and 3D piping/equipment scenes from
natural-language prompts (see [../docs_analysis/00_overview.md](../docs_analysis/00_overview.md)
for how). What it cannot do well:

1. **Make precise edits** — resize an existing component, not just delete-and-redraw it.
2. **Get metadata** — out of the currently open drawing, and out of many drawings at once.
3. **Change document-level things** — file/document names, header colors, layer colors.
4. **Work on multiple projects** — the whole app currently assumes one active AutoCAD document /
   one "latest" scene.
5. **Extract metadata across multiple files** — there is no persistent, queryable index of what's
   in a folder of drawings; each inspection is a live, one-off, single-file operation.

## What we explicitly decided *not* to do

**Do not solve this by making every module its own AI agent.** The instinct when facing "100
files, multiple projects, complex operations" is to reach for a multi-agent framework — one agent
per file, one agent per task type. We rejected this, for two reasons discussed at length:

- It's slower and more expensive: one AI planning call per file (100 files → 100 LLM
  conversations) versus one AI planning call that determines *which* files are affected, then
  deterministic code executes across just those.
- It doesn't match what already works here. This project's existing AI-assisted features
  (sketch, P&ID, CAD3D, vessel) already succeed specifically because the AI only ever produces a
  small, schema-validated plan, and ordinary deterministic Python code does everything else
  (validation, execution, rendering). That split is the reason the app is testable, predictable,
  and (mostly) safe to run against a live drawing. Extending the app means extending that split
  further down into metadata/edits/multi-file work — not replacing it with agents.

## The principle every decision in this roadmap answers to

> **AI plans. Deterministic code executes.** The AI is given only the data it needs (one entity,
> not the whole drawing) and returns only a small, structured decision (a command or operation
> object) — never raw geometry it computed itself, never a live AutoCAD call it made itself.

This is not a new idea for this codebase — it's already how `src/ai/` and `src/framework/`
are split today (verified during the full-codebase read that produced `docs_analysis/`). This
roadmap is what it looks like to apply that same split to metadata, multi-file operations, and
edits, which today only partially follow it.

## What "done" looks like

- A user can point the app at a folder of DWGs (a "project") and ask "what's in these drawings" —
  or "increase pipe P-101 by 50mm everywhere it appears" — without the app opening every file or
  re-deriving everything from scratch on every request.
- Edits modify existing entities in place (resize, recolor, rename) rather than deleting and
  redrawing.
- Every mutating operation can be previewed, kept, or reverted, consistently, across every
  workflow (sketch, P&ID, CAD3D, vessel, and the new multi-file operations) — not via four
  slightly different token-cache implementations as exists today.
- Multiple projects can be registered and switched between; nothing is hardcoded to "whatever
  AutoCAD happens to have open right now."
