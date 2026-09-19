# Roadmap implementation log

Baseline (Windows, Python 3.11.9, installed pywin32): **892 passed, 10 skipped**
in 81.52 seconds. No running AutoCAD or ODA converter discovered. Existing user
changes in `src/api/static/sketch.html` and untracked reference docs/launchers are
preserved. No Step 9 implementation is planned.

## Step 1 — Project registration + SQLite schema
Added src/storage/{database.py,project_repository.py,schema.sql} and tests/project storage coverage. Registration validates and canonicalizes folders without scanning; all roadmap tables live beside the unmodified jobs table through its existing connection function. WAL, foreign keys, repeat initialization, duplicate roots, invalid roots, registration and listing were verified. Full suite: 895 passed, 10 skipped. Reviewed: no CAD/LLM/deletion paths introduced. Definition of done fully met. No roadmap deviation; added lookup indexes and unique project/drawing paths for integrity.
