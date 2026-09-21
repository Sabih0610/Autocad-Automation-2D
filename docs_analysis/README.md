# docs_analysis — Full Codebase Reference

Generated 2026-09-19 by reading every source file in this project in full (not sampling), running
the project's test suite, and rebuilding its Python environment from scratch. Intended so another
AI (or a new human contributor) can work in this codebase without re-reading the source.

**Start at [00_overview.md](00_overview.md).** It orients you in the architecture and links to every
other file here in reading order. If you only have time for one more file after that, read
[09_known_issues_and_recommendations.md](09_known_issues_and_recommendations.md) — the ranked
cross-cutting findings from all 8 subsystem deep-dives.

| File | Covers |
|---|---|
| [00_overview.md](00_overview.md) | Big picture, architecture map, reading order |
| [01_environment_and_setup.md](01_environment_and_setup.md) | Verified setup/run steps, what was broken and how it was fixed |
| [02_api_layer.md](02_api_layer.md) | FastAPI app, routes, static chat UI |
| [03_ai_layer.md](03_ai_layer.md) | `src/ai/*` — LLM planners/generators |
| [04_command_and_autocad_framework.md](04_command_and_autocad_framework.md) | Generic command schema/executor, AutoCAD inspector |
| [05_cad3d_framework.md](05_cad3d_framework.md) | 3D scene components, editor, store, executor |
| [06_pid_framework.md](06_pid_framework.md) | 2D P&ID symbols, components, builder |
| [07_parametric_vessel.md](07_parametric_vessel.md) | Deterministic vessel geometry + drawing generation |
| [08_use_cases_logging_scratch.md](08_use_cases_logging_scratch.md) | CLI-era use cases, SQLite audit trail, dev scratch scripts |
| [09_known_issues_and_recommendations.md](09_known_issues_and_recommendations.md) | Ranked cross-cutting issues and fixes |
| [10_project_extension_review.md](10_project_extension_review.md) | Bug-hunt of the `roadmap/` Steps 1-8 implementation (multi-project, metadata index, structured edits, changesets) — added 2026-09-20 |
