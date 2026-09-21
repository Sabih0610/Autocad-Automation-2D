# Group B (527ec1e) — adversarial verification

## 1. Verdict per fix

- **B1 stuck-states — PARTIAL.** `keep`, `discard` and the `before_hash` acceptance hold; the NULL-`after_hash` path verifiably destroys a third party's later work, and `discard` removes the justification for doing so.
- **B2 file-level changesets — PARTIAL.** Migration and `apply_file_edit`/`revert` are sound, but wiring six routes to a conflict check with no client-reachable resolution re-creates the "drawing out of service" failure B1 set out to remove.
- **B3 explicit write targets — PARTIAL.** The guard is correctly placed on all four routes it covers, but `target_dwg_path: ""` walks through it into `ActiveDocument`, and `place-symbol` has no guard at all.

## 2. Migration safety (highest risk) — HOLDS

Tested against purpose-built old-shape databases in the system temp dir (`NOT NULL drawing_id`, `PRIMARY KEY(change_set_id,drawing_id)`, built from `527ec1e^:src/storage/schema.sql`), driven through the real `connection()`. SQLite 3.45.1.

- **Row fidelity**: 4 realistic rows — multi-file changeset, a rename row (`current_path != original_path`, `uses_cad=0`), a NULL `after_hash` row, the same drawing in two changesets. All 8 columns of all 4 rows byte-identical after migration; `integrity_check` ok, `foreign_key_check` empty.
- **New constraints**: `PRIMARY KEY(change_set_id,original_path)` enforced (duplicate rejected); NULL `drawing_id` insert accepted; `change_set_files_legacy` dropped.
- **Interrupted mid-copy** (raise inside `INSERT INTO change_set_files`): rolls back cleanly — table still named `change_set_files`, rows intact, no `_legacy` leftover — and the *next* `connection()` completes the migration with all rows preserved. A second run is a no-op.
- **Both migrations pending on one DB**: both succeed; `ensure_relationship_targets` commits before returning, so the second `BEGIN IMMEDIATE` does not collide.
- **Fresh DB**: `in_transaction` is False on handover and `BEGIN IMMEDIATE` succeeds. A caller exception inside `with connection()` still rolls that write back; the new commit flushes only `ensure_spatial`'s backfill.

Two inputs brick the database permanently — `connection()` then raises on *every* call, with no recovery path: duplicate `(change_set_id, original_path)` legacy rows (`UNIQUE constraint failed`), and an orphan `drawing_id` (`FOREIGN KEY constraint failed` on the `INSERT…SELECT`, because `database.py:23` sets `PRAGMA foreign_keys=ON` and the migration does not disable FKs around rename/copy/drop as SQLite's recipe requires). Neither is reachable from app code (`apply` keys `targets` by canonical path; nothing deletes `drawings`); both need an external writer, and `ensure_relationship_targets` carries the identical inherited flaw. **Acceptable, worth hardening.**

## 3. Findings

**F1 — HIGH. One write locks the drawing out of all six routes, with no client-side escape.** `src/cad/changes.py:189-192`. Reproduced end-to-end: sketch approve with an explicit target → 200 + `change_set_id`, status `pending`. Second sketch approve to the same file → **HTTP 500** `Resolve the existing pending changeset for this drawing first`; `/api/pid/approve` on that file → same 500. Only a hand-rolled `POST /api/change-sets/{id}/keep` unblocks it. `changesets.js` is reached only via `showChangeSet`, called solely from `project-chat.js:147`; no legacy page renders `change_set_id`. The commit concedes the sketch Revert control is unbuilt but not that the conflict check makes it *mandatory*. Repeat-sketching into one drawing is broken. Sub-issue: the `ValueError` surfaces as 500, not the 409 `changes.py:respond` maps it to.

**F2 — MEDIUM. `target_dwg_path: ""` bypasses the B3 guard into the active document.** `_revertible.py:35` uses `is not None`, so `""` passes; `run_revertible:70` uses `if not target_dwg_path`, so no changeset; `executor.py:558` uses `if target_dwg_path:`, so `""` falls to `_active_document(acad)`. Observed: `POST /api/pid/approve {"target_dwg_path":"","save":true}` → 200, executor received `''`, `change_set_id: None`. The comment at `_revertible.py:30-34` claims it is "rejected downstream with an error about the path itself" — it is not. The covering test passes vacuously (mocked executor; assertion guarded by `if status_code == 400`).

**F3 — MEDIUM. `place-symbol` has no `require_explicit_target`.** `place_symbol.py:43` takes its target from `connect_to_autocad()` → `doc.FullName`: the implicit active document B3 forbids. The one wired route with no guard, and no case for it in `test_explicit_write_target.py`.

**F4 — MEDIUM. NULL `after_hash` revert destroys later third-party work (reproduced; by design).** `changes.py:309` skips the freshness check entirely, so genuinely newer edits are overwritten from the backup. The rationale is "strictly better than refusing forever" — but `discard()`, added in the same commit, makes refusing neither forever nor destructive. The trade-off no longer holds on its own terms.

**F5 — LOW. `apply_file_edit` takes no `CAD_LOCK` and never goes through `WRITE_QUEUE`,** unlike `apply`. Reproduced: `discard()` during an in-flight `execute` sets `discarded`, then `apply_file_edit:221` puts it back to `pending` — the discard is lost, and the conflict lock was briefly released.

**F6 — LOW. `keep` accepts nonsense states.** With the backup *and* the drawing both deleted, `keep` returns `kept`. It also drops the `uses_cad=0` `.dwl` "close the renamed drawing" check. `keep` writes nothing, so neither is load-bearing — but "has nothing to verify" is not quite true.

**F7 — LOW (docs).** `_revertible.py:3-5` says it is shared by vessel and title-block; neither imports it. `autocad_edit.py`'s `auto_execute=False` early return omits both changeset keys, breaking the "exactly one is set" contract.

## 4. What I could not break

- The migration, on every axis in section 2.
- `revert` accepting `before_hash`: no ordering I tried loses data. If the file already hashes to `before_hash`, restoring the backup is byte-identical.
- `revert` for PROJECT changesets after re-keying to `original_path`: the new PK makes `(change_set_id, original_path)` unique, so the rewritten revert-loop `UPDATE` and `_record_file` match exactly the row the old `drawing_id` predicate did, rename case included.
- No changeset leak when `execute` raises: the error path records `after_hash`, writes a failed validation, sets `error`, and the changeset still reverts correctly.
- Backup integrity is verified before the write, twice (`backup.py:50`, `changes.py:198`).
- **Vessel claim accurate**: `vessel.py:188` writes a timestamped *new* file under `outputs/vessels`; `dwg_export` only opens the DXF it just produced — no existing drawing is modified. **Title-block claim accurate**: `update_title_block.py:139` still calls its own `backup_file`. Line-list writes only an xlsx.
- The ~60 mechanical `use_active_document: True` test edits: audited all. No site carries both `target_dwg_path` and `use_active_document`, so no test that named a target had its intent flipped; every addition preserves the pre-commit behaviour. ~12 are noise on tests that 404/400/422 before the guard.
- Guard placement: `require_explicit_target` precedes the first COM call on all four routes it covers.

## 5. Suite numbers observed

`venv\Scripts\python.exe -m pytest tests/ -q` → **1088 passed, 10 skipped, 0 failed**, 31 warnings, 82.37s. Matches the claim exactly. Repo tree and `jobs.db` untouched; all scratch DBs and scripts in the system temp dir.
