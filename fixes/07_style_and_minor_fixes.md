# Module 7: Style / Minor / Inert Fixes

Eight independent, low-severity findings ("Tier 3" in `docs_analysis/10_project_extension_review.md`,
items 13-20 of its combined fix-priority list) — dead code, a missed edge case, a misleading error
message, wasted work, a redundant index, and two audit/error-mapping gaps. None of these were live
safety bugs; each is fixed in isolation in `src/storage/schema.sql`, `src/storage/database.py`,
`src/storage/spatial.py`, `src/storage/entity_repository.py`, `src/api/main.py`,
`src/api/routes/projects.py`, and `src/api/routes/changes.py`, with new coverage in
`tests/project/test_database.py` (new file), `tests/project/test_entity_index.py`,
`tests/project/test_spatial.py`, and `tests/project/test_orchestrator.py`.

## Item 13 — Dead `AFTER UPDATE` triggers on `entity_geometry`

**Bug.** `entity_repository.store_snapshot` always writes `entity_geometry` via delete-then-insert
(`store_snapshot`, `src/storage/entity_repository.py:23,43` — a `DELETE ... WHERE entity_id=?`
followed later by a fresh `INSERT`). I grepped the whole repository for `UPDATE entity_geometry`
and got zero matches outside trigger bodies, confirming an `UPDATE` on this table never happens in
practice. Two `AFTER UPDATE ON entity_geometry` triggers therefore could never fire:
`geometry_version_update` (was in `src/storage/schema.sql`) and `spatial_update` (was in
`ensure_spatial`, `src/storage/spatial.py`).

**Fix.** Both triggers are gone from their `CREATE TRIGGER` statements — `schema.sql:140-145` now
defines only `geometry_version_insert`/`geometry_version_delete`, and `spatial.py`'s
`ensure_spatial` (lines 55-63) now creates only `spatial_insert`/`spatial_delete`. So a fresh
database never gets the dead triggers. `src/storage/database.py`'s `connection()` additionally runs
`conn.execute("DROP TRIGGER IF EXISTS geometry_version_update")` and
`conn.execute("DROP TRIGGER IF EXISTS spatial_update")` (lines 57-58) — **unconditionally, on every
call**, not gated behind the `_is_initialized` fast-path (see item 17) — so a database file created
by an older build of this code, which may still have the dead triggers physically on disk, gets
cleaned up too.

**Test.** `tests/project/test_database.py::test_dead_update_triggers_on_entity_geometry_are_not_created`
confirms a fresh DB has neither dead trigger but keeps both live insert/delete siblings.
`::test_dead_update_triggers_are_dropped_from_a_database_created_before_the_fix` manually
`CREATE TRIGGER`s both dead triggers back in (simulating a pre-fix database), then reopens
`connection()` and confirms they're gone again.

## Item 14 — Whitespace-only tags not filtered in cross-drawing tag-relationship derivation

**Bug.** `store_snapshot`'s "same tag in another drawing is a representation" loop used
`if not entity.tag: continue`, which correctly skips `None`/`""` but not a whitespace-only tag like
`"   "` — that string is truthy in Python, so it fell through into the cross-drawing match query and
could spuriously create `represented_in` relationships between entities that aren't meaningfully
tagged at all.

**Fix.** `src/storage/entity_repository.py:59`: `if not entity.tag or not entity.tag.strip(): continue`.

**Test.** `tests/project/test_entity_index.py::test_whitespace_only_tags_are_not_cross_linked_as_the_same_component`
builds two real DXF files via `ezdxf`, each with one entity whose XData tag is literally `"   "`,
scans both into the same project, and confirms zero `represented_in` rows exist — while also
confirming (via a direct `SELECT count(*) FROM entities WHERE tag=?`) that the whitespace tag really
was stored as-is rather than silently dropped somewhere else in extraction, so the test is exercising
the guard itself and not a side effect of the tag never reaching the database.

## Item 15 — Raw `KeyError` instead of descriptive `ValueError` for an unknown relationship handle

**Bug.** The relationships-insertion loop in `store_snapshot` did `ids[relation.source_handle]` /
`ids[relation.target_handle]` with no existence check. A `RelationshipRecord` naming a handle absent
from `snapshot.entities` raised a raw `KeyError`, inconsistent with every other malformed-snapshot
case in the same function (e.g. the pre-existing "Geometry references an unknown entity" check for
`spatial_data`, `entity_repository.py:37-38`), which all raise a descriptive `ValueError`.

**Fix.** `src/storage/entity_repository.py:48-49`:
`if relation.source_handle not in ids or relation.target_handle not in ids: raise ValueError("Relationship references an unknown entity")`,
inserted immediately before the `INSERT OR IGNORE INTO relationships` call.

**Test.** `tests/project/test_entity_index.py::test_relationship_with_unknown_target_handle_raises_descriptive_value_error`
appends a `RelationshipRecord("not-a-real-handle", "connected_to", "also-not-real")` to a real
extracted snapshot and confirms `store_snapshot` raises `ValueError` matching `"unknown entity"`
(not `KeyError`), then confirms the original `P-101` index entry is still present afterward —
proving the transaction rolled back cleanly rather than leaving partial state.

## Item 16 — Misleading "no geometry" error in `nearby()` when the real cause is a missing `layout` property

**Bug.** `SpatialIndex.nearby()`'s target lookup (`src/storage/spatial.py:100-104`, before the fix)
`INNER JOIN`ed `entity_properties` filtered to `key='layout'`. An entity with real geometry but no
indexed `'layout'` property got silently filtered out of the result entirely, so the code reported
`"No current indexed geometry for the selected entity"` — the same message used when the entity has
no geometry row at all — masking the real cause.

**Fix.** `spatial.py:103` changed that join to `LEFT JOIN entity_properties p ON p.entity_id=e.entity_id AND p.key='layout'`,
and `spatial.py:107-108` added a second, distinct check after the existing "row is `None`" check:
`if target["layout"] is None: raise ValueError("Selected entity has no indexed 'layout' property; rescan the drawing")`.

**Test.** `tests/project/test_spatial.py::test_nearby_missing_layout_property_gives_a_distinct_error_not_no_geometry`
scans a real drawing, deletes just the `'layout'` row from `entity_properties` for one entity, calls
`nearby()`, and asserts the new message (matching `"layout"`) is raised while `"No current indexed
geometry"` is specifically absent from the message.

**Verified as requested — does the `LEFT JOIN` change affect any other caller?** I read the rest of
`spatial.py` directly rather than assuming. `RTREE_QUERY` (lines 80-84) still `INNER JOIN`s
`entity_properties p ON p.entity_id=e.entity_id AND p.key='layout' ... AND p.value=?` — unchanged,
and correctly so: that query filters *candidate* rows to the same `layout` value as the already-
resolved target (passed in as a bound parameter), which is a genuinely different question ("is this
candidate in the same layout as the target") from "does the target itself have a `layout` property."
The cKDTree fallback path (`spatial.py:119-122`) has the identical shape and the identical
reasoning. Only the one `target`-row lookup query needed the `LEFT JOIN` + explicit check; the two
candidate-filtering queries were correctly left as `INNER JOIN` and still behave as before.

## Item 17 — Full schema/DDL re-execution on every single `connection()` call

**Bug.** `database.py`'s `connection()` re-ran the entire `schema.sql` script
(`conn.executescript(SCHEMA)`, ~30 `CREATE ... IF NOT EXISTS` / trigger statements) plus a second
`executescript` creating 4 more indexes, on every call — all idempotent, but wasteful once the
schema already exists.

**Fix.** `database.py:12-15` adds `_is_initialized(conn)`, checking `sqlite_master` for the
`drawings` table. `database.py:30-37` wraps only the two static `executescript` calls in
`if not _is_initialized(conn):`.

**Verified per the task's specific instruction — the mid-session near-miss.** I read the current
`connection()` (`database.py:18-62`) directly rather than trusting the description. Confirmed:
`ensure_relationship_targets(conn)` and `ensure_spatial(conn)` (lines 45-46) sit **outside and after**
the `if not _is_initialized(conn):` block, at the same indentation as the block itself — they run
unconditionally on every call, exactly as the description says the final (corrected) state should
be. Only `conn.executescript(SCHEMA)` and the trailing 4-index `executescript` are actually gated.
The in-code comment block (lines 38-44) explicitly documents *why*: `ensure_relationship_targets` is
a self-checking migration (detects and repairs a `relationships` table left in the legacy
pre-migration shape) and `ensure_spatial` re-derives `spatial_index` if missing — neither is plain
static DDL, and each already guards its own work behind a cheap existence check, so there was
never a real "expensive replay" to skip for them in the first place. Had they been left inside the
`_is_initialized` gate (the bug the description says was caught and fixed mid-session), they would
never run again once `drawings` existed, and the self-healing migration would stop self-healing.
This is exactly the shape of the pre-existing test below, which I ran and confirmed still passes.

**Tests.** `tests/project/test_database.py::test_connection_skips_redundant_schema_reexecution_once_initialized`
monkeypatches `SCHEMA` to append a `CREATE TABLE reexecution_marker (x)` with no `IF NOT EXISTS`
guard, and confirms two subsequent `connection()` calls don't raise (would raise
`sqlite3.OperationalError: table already exists` if `SCHEMA` replayed).
`::test_connection_still_self_heals_relationship_schema_on_every_call` manually drops and recreates
`relationships` in the legacy pre-migration shape (no `target_drawing_id` column) after `drawings`
already exists, then reopens `connection()` and confirms the column is back and the expected
`appears_in` row was rederived — a targeted regression test for exactly the bug the description
says was caught mid-session. I also re-ran the pre-existing
`tests/project/test_spatial.py::test_existing_entity_only_edges_migrate_to_drawing_membership`
(unchanged by this module) specifically because it's the test that would have caught the original
over-gating mistake; it passes.

## Item 18 — Redundant case-sensitive tag index

**Bug.** `database.py` created `idx_entity_tag` (case-sensitive, on `entities(tag, drawing_id)`),
while `schema.sql` separately creates `idx_entity_tag_nocase` (`schema.sql:114`, on
`entities(tag COLLATE NOCASE, drawing_id)`). I grepped `src/` for `tag=?` / `tag = ?` and every real
tag lookup (`entity_repository.py`'s `TAG_QUERY`, and the cross-drawing relationship-derivation
query in `store_snapshot`) filters `WHERE e.tag=? COLLATE NOCASE`. A case-sensitive index can't
accelerate a `COLLATE NOCASE` comparison, so `idx_entity_tag` was pure dead weight — and confirmed
absent from the current index-creation script in `database.py` (lines 32-37 create only
`idx_project_root`, `idx_drawing_path`, `idx_entity_drawing`, `idx_relationship_target`).

**Fix.** `database.py:56`: `conn.execute("DROP INDEX IF EXISTS idx_entity_tag")`, run
unconditionally on every `connection()` call (same reasoning as item 13's trigger drops — must
clean up a pre-existing database, not just skip creating it on a fresh one).

**Test.** `tests/project/test_database.py::test_case_sensitive_tag_index_is_not_created_and_is_dropped_if_present`
confirms a fresh DB has `idx_entity_tag_nocase` but not `idx_entity_tag`, manually creates
`idx_entity_tag` to simulate a pre-fix database, and confirms the next `connection()` call drops it.
I also re-ran the pre-existing
`tests/project/test_entity_index.py::test_tag_lookup_is_one_indexed_query_scoped_to_project`, which
runs `EXPLAIN QUERY PLAN` over `TAG_QUERY` and asserts `idx_entity_tag_nocase` is the index the
planner actually picks; it still passes, confirming the real lookup index is untouched.

## Item 19 — New read-only routes missing from `AUDIT_ROUTE_MAP`

**Bug.** `src/api/main.py`'s `AUDIT_ROUTE_MAP` was missing 5 read-only `GET` routes defined in
`src/api/routes/projects.py`, inconsistent with the pre-existing convention that
`GET /api/autocad/inspect` is audited while the router's own mutating routes were already correctly
audited.

**Fix — verified by reading the map and the router directly, not just the description.**
`src/api/main.py:33-61` now contains, and I confirmed each string matches the router's actual path
exactly (`APIRouter(prefix="/api/projects", ...)` plus each route's own path suffix from
`src/api/routes/projects.py`):
- `"/api/projects/{project_id}/drawings": "project_drawings"` — matches `@router.get("/{project_id}/drawings")` (`projects.py:57`)
- `"/api/projects/{project_id}/entities": "project_entities"` — matches `@router.get("/{project_id}/entities")` (`projects.py:62`)
- `"/api/projects/{project_id}/nearby": "project_nearby"` — matches `@router.get("/{project_id}/nearby")` (`projects.py:67`)
- `"/api/projects/{project_id}/change-sets": "project_change_sets"` — matches `@router.get("/{project_id}/change-sets")` (`projects.py:73`)
- `"/api/projects/jobs/{job_id}": "project_job"` — matches `@router.get("/jobs/{job_id}")` (`projects.py:83`)

All 5 are present and correctly spelled.

**Test.** `tests/project/test_orchestrator.py::test_new_readonly_project_routes_are_audit_logged`
uses the real `app` from `src.api.main` (not a scoped-down test app — `AUDIT_ROUTE_MAP` and its
middleware live in `main.py`), hits `GET /api/projects/{project_id}/drawings`, and confirms a `jobs`
row was written with `use_case="project_drawings"` and `status="ok"` via
`src.logging.jobs.list_recent_jobs`.

**The "was `GET /api/change-sets/{change_id}` in scope" question — answered explicitly, as asked.**
`src/api/routes/changes.py:36-38` defines `@router.get("/{change_id}")` (`detail`), a similarly-shaped
read-only detail route on the `/api/change-sets` router. I checked `AUDIT_ROUTE_MAP` for it directly:
the map has `"/api/change-sets": "project_apply"` (the `POST`), `"/api/change-sets/{change_id}/keep"`,
and `"/api/change-sets/{change_id}/revert"`, but **no entry for plain
`"/api/change-sets/{change_id}"`** — the `GET` detail route is still unaudited. This matches the
original review wording, which named exactly 5 routes (drawings/entities/nearby/change-sets-list/
job-lookup) and did not include the change-set detail route, so this module's fix is internally
consistent with its own stated scope — but the gap itself is real and unresolved. Flagging it here
rather than silently assuming it was covered: `GET /api/change-sets/{change_id}` calls are still
invisible to the audit trail after this module.

## Item 20 — Two near-identical `respond()` error-mapping helpers disagreed on caught exception types

**Bug.** `src/api/routes/projects.py`'s `respond()` caught
`(ValueError, OSError, sqlite3.IntegrityError, ValidationError)` → 409, while
`src/api/routes/changes.py`'s `respond()` caught only `(ValueError, OSError, ValidationError)` →
409 — missing `sqlite3.IntegrityError`. Neither caught `sqlite3.OperationalError` (e.g. a lock
timeout), which would have surfaced as a raw unmapped 500 in both files.

**Fix.** Both `respond()` helpers (`projects.py:20-26`, `changes.py:22-28`) now catch identically:
`(ValueError, OSError, sqlite3.IntegrityError, sqlite3.OperationalError, ValidationError)` → 409.
`changes.py:1` gained a new `import sqlite3` (it previously imported neither `sqlite3` nor used it).

**Tests.** `tests/project/test_orchestrator.py::test_projects_respond_maps_operational_error_to_409_not_500`
monkeypatches `list_drawings` to raise `sqlite3.OperationalError("database is locked")` and confirms
`GET /api/projects/{project_id}/drawings` now returns 409, not 500.
`::test_changes_respond_maps_operational_and_integrity_errors_to_409` loops over both
`sqlite3.OperationalError` and `sqlite3.IntegrityError`, monkeypatching `get_change_set` to raise
each in turn, and confirms `GET /api/change-sets/some-id` returns 409 for both — the meaningful half
of this test, since `changes.py` previously caught neither.

## Verification run

Targeted:
```
venv\Scripts\python.exe -m pytest tests/project/test_database.py tests/project/test_spatial.py \
       tests/project/test_entity_index.py tests/project/test_orchestrator.py -q
  → 27 passed, 7 warnings in 9.20s
```

Full suite:
```
venv\Scripts\python.exe -m pytest tests/ -q
  → 1003 passed, 10 skipped, 29 warnings in 117.85s
```
This matches the expected baseline exactly (1003 passed / 10 skipped), confirming no regressions
from this module's changes.

## Discrepancies found

None in the 8 fixes themselves — every bug, fix location, and test matched the description on direct
reading of the current code and tests, including the two points the task flagged as needing careful
independent verification:

1. **Item 17's mid-session near-miss is correctly resolved in the final code.** I read
   `database.py`'s `connection()` directly: `ensure_relationship_targets(conn)` and
   `ensure_spatial(conn)` are outside the `if not _is_initialized(conn):` block and run
   unconditionally on every call; only the static `SCHEMA` script and the trailing index-creation
   script are gated. The pre-existing regression test this would have broken
   (`test_existing_entity_only_edges_migrate_to_drawing_membership`) still passes, as does the new
   targeted regression test for the same failure mode.
2. **Item 19's "was `GET /api/change-sets/{change_id}` in scope" question resolves to "no, and it's
   still a real gap."** The original review named exactly 5 routes; this module added exactly those
   5 and no more. `GET /api/change-sets/{change_id}` was not one of them, is not in
   `AUDIT_ROUTE_MAP` today, and remains unaudited. This is not a defect in this module's own scope,
   but it is a loose end worth tracking separately if complete audit coverage of all read routes is
   ever a goal.
