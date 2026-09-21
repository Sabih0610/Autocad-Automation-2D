# ChangeSet & KEEP / REVERT

## The problem this solves

Generate → Approve already exists, four separate times, with four different (and already
inconsistent) lifetimes:

- Sketch and vessel tokens: 10-minute TTL, purged lazily, and a **successful** approve pops the
  token (one-shot).
- P&ID and CAD3D tokens: **no TTL at all** — they live for the process's lifetime and are never
  popped even on success, so the same operation can be replayed into AutoCAD indefinitely.

(Documented in detail in [../docs_analysis/09_known_issues_and_recommendations.md](../docs_analysis/09_known_issues_and_recommendations.md),
item 7.) This is exactly the kind of drift that happens when every workflow builds its own
approval mechanism instead of sharing one. The fix is a single `ChangeSet` concept, backed by the
`change_sets`/`change_set_items` tables from [03_sqlite_schema.md](03_sqlite_schema.md).

## Version 1 — build this first: whole-file backup

```
Before mutating a file
        ↓
src/backup.py's backup_file() — this already exists and works, just isn't called
from execute_command_sequence()/execute_edit_plan() today (a real existing gap worth
fixing regardless of anything else in this roadmap)
        ↓
Execute the structured operation
        ↓
Validate
        ↓
Show the chatbot: "Changed 2 drawings, modified 1 pipe" + [ KEEP ] [ REVERT ]
        ↓
KEEP    → nothing further needed, the file is already saved
REVERT  → restore the backed-up file(s) wholesale
```

This is deliberately coarse (whole-file, not per-entity) and deliberately cheap: it reuses a
mechanism that already exists and is already tested, rather than inventing entity-level
diffing before there's any evidence it's needed.

## Version 2 — later: entity-level before/after summary

Once structured operations exist ([05_structured_operations_and_editing.md](05_structured_operations_and_editing.md)),
each operation already *knows* what it changed (e.g. `{"field": "length_mm", "before": 1000,
"after": 1050}`) — record that directly into `change_set_items` for a human-readable chat summary
like:

```
ChangeSet 932
  PIPE-104   length: 1000 → 1050
  VALVE-22   position.x: 2000 → 2050
  DIM-17     value: 1000 → 1050
```

This does **not** require reverse-engineering a diff from the DWG binary — the structured
operation already carries this information; just persist it.

## Worth prototyping as a lighter-weight alternative/complement

AutoCAD's COM surface already supports a native undo-mark mechanism:
```
doc.SendCommand("_UNDO _Mark ")
...apply the edit...
doc.SendCommand("_UNDO _Back ")   -- rolls back to the mark, live, in-document
```
This could give "apply then decide" semantics without a file swap at all, for the case where the
document stays open across the preview→decide step. Worth a small spike before assuming file
backup/restore is the only option — but not required to ship version 1.

## Keep the existing audit trail as-is

`jobs.db`'s `jobs` table (used by the API's `AuditJobMiddleware` and the CLI `@log_job` decorator)
continues to work exactly as it does today. `change_sets`/`change_set_items`/`validation_results`
are new tables alongside it, not a replacement.
