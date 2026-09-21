# Codex Handoff — Group A/B Follow-Up

Groups A and B are implemented and committed (`02eaf45`, `527ec1e`, `0c495c7`).
Suite: **1089 passed, 10 skipped, 0 failed**.

Two independent adversarial agents then reviewed both groups. Their reports are in
`remediation/verification/`. They found seven real defects the groups introduced or left
behind, plus one piece of unfinished work that makes the whole of Group B unusable in
practice.

**Item 1 is a data-loss regression introduced by Group A. Do it first.**

Hand Codex the prompt below. It is self-contained.

---

```
You are working on F:\RC-Projects\autocad-ai\autocad-ai, a Windows-only Python/FastAPI app that
drives AutoCAD through COM (pywin32). Architectural rules you must not violate: the AI layer
(src/ai/) only produces schema-validated JSON plans and never touches AutoCAD; the framework layer
(src/framework/) never calls an LLM; entity edits are in-place COM property assignments, never
.Delete() and re-add.

Baseline: 1089 passed, 10 skipped, 0 failed via `venv\Scripts\python.exe -m pytest tests/ -q`.
Seven fixes plus one build task. Commit after each numbered item. Full context for any of them is in
remediation/verification/GROUP_A_adversarial.md and GROUP_B_adversarial.md.

=== 1. CRITICAL — the executor can close the user's drawing and discard their work ===
src/cad/session.py:48-53 `open_document` decides whether IT opened a document by whether
`find_open_document` matched:

    existing = find_open_document(acad, path)
    doc = acad.Documents.Open(path) if existing is None else existing
    ...
    return doc, existing is None

Real `AcadDocuments.Open` returns the ALREADY-OPEN document when that drawing is already open. So
any path spelling `find_open_document` cannot unify — a mapped drive vs its UNC form, a directory
junction, an 8.3 short name — produces `existing = None`, `Open()` hands back the user's own
document, `opened_here` is wrongly True, and the `finally` in executor.py / edit_executor.py /
autocad_3d_executor.py calls `doc.Close(False)` on it. The user's unsaved work is discarded.

`tests/project/fake_cad.py` hides this: its `Documents.Open` always constructs a second Document
object, so the fake can never reproduce the real aliasing.

FIX: do not infer ownership. Determine it from the document itself — capture the set of open
documents (or their identities) before opening and compare after, or check whether the returned
object is one you already held. Whatever you choose must be correct when `Open()` returns a
pre-existing document.
ALSO: make the fake faithful — `fake_cad.Documents.Open` must return the existing Document when one
with that path is already open, exactly as AutoCAD does.
TEST: a drawing already open under a path spelling that `find_open_document` does NOT match, opened
via `open_document`, must report `opened_here=False` and must NOT be closed. This test must fail
before your fix.

=== 2. Group B is unusable without this: no UI surfaces change_set_id ===
Six routes now return `change_set_id` (sketch approve, P&ID approve, CAD3D approve, CAD3D edit,
place-symbol, autocad/edit), and `POST /api/change-sets/{id}/revert` works. But only
src/api/static/project-chat.js renders a Revert control, so a user who sketches into a drawing still
has no way to undo it. The plumbing exists with no tap.

FIX: in src/api/static/sketch.html, every result bubble for a write that returned a `change_set_id`
must show it and offer Revert (and Keep). When the response carries `change_set_skipped_reason`
instead, show that reason — it explains why this particular write is not revertible, which is
information the user needs, not an error.
Use the existing `escapeText` helper for every interpolated value; that file already does this in
~60 places and jobs.html's failure to do so was a stored-XSS bug.
TEST: assert against the rendered HTML that a response with a change_set_id produces a Revert
control wired to the right id, and that one with a skipped reason renders the reason instead.

=== 3. HIGH — a retried open leaks the document it opened ===
The three executors wrap `open_document` in `_com_retry`. If attempt 1 opens the drawing and then
hits a transient busy error, attempt 2 finds it already open and returns `opened_here=False` — so
the document attempt 1 opened is never closed, while the caller still gets `ok=True`.
FIX: make the open/ownership determination survive a retry. Either move the retry inside
`open_document` around only the COM call, or track ownership across attempts.
TEST: an `open_document` whose first attempt opens the document and then raises a retryable busy
error must still report ownership correctly, and the document must be closed.

=== 4. MEDIUM — a database failure now aborts a drawing write ===
`open_document` and `close_document` call `mark_open()`, which writes SQLite. The three executors hit
the database on paths that never touched it before, and `mark_open` is unguarded in `open_document`.
A locked or unavailable database now fails `execute_commands` outright, and on the close path it can
leak the document too.
FIX: `mark_open` is bookkeeping for `rename_file`'s open-file guard, not part of the write itself. A
failure to record it must not fail the drawing write. Guard it, and make sure a failure cannot skip
the close. Do NOT simply swallow it silently — surface it in the result the way
`backup_skipped_reason` is surfaced, so a stale open-flag is diagnosable.

=== 5. MEDIUM — a read-only scene fetch still hijacks get_latest() ===
src/framework/cad3d/scene_store.py:230-233 — `get(token)` sets `self._latest_token` on a cold disk
load. After a server restart, opening `GET /api/cad3d/state/{OLD}` to look at an old scene makes a
later `POST /api/cad3d/edit` with no token (which falls back to `get_latest()`) edit — and with
execute=true, write — the OLD scene. Group A fixed the store's ORDERING but not this; `list_records()[0]`
is now correct while `get_latest()` can still be wrong, so the two disagree.
FIX: a read must not change what "latest" means. Derive `get_latest()` from the records themselves
(it can now rely on the ordering Group A made deterministic) rather than from a token mutated by
reads.
TEST: persist A then B, restart the store, `get(A)`, and assert `get_latest()` is still B and agrees
with `list_records()[0]`.

=== 6. MEDIUM — the COM fake rejects schema-valid commands ===
`tests/project/fake_cad.py` raises KeyError for three combinations the command schema accepts:
TEXT with `rotation_degrees`, ELLIPSE with start/end angles, DIM_LINEAR with `text_override`. So
those executor branches still cannot be tested.
FIX: support them in the fake, faithfully to real COM semantics (check the angle units — COM and DXF
disagree, which is why `AddArc` needs a radians→degrees conversion). Then extend
tests/project/test_executor_creation_surface.py to cover each.

=== 7. MEDIUM — title-block still has its own backup mechanism ===
src/use_cases/update_title_block.py:139 calls `backup_file` directly instead of going through the
file-level changeset every other write route now uses, so its writes are backed up but not
revertible.
FIX: migrate it onto `src/api/routes/_revertible.py`'s `run_revertible`, like the other six routes.
Note it has a `_temporary_module_settings` global-mutation pattern guarded by `_SETTINGS_LOCK` —
leave that alone.
TEST: a title-block update against a temp DXF returns a change_set_id, and revert restores the file
byte-for-byte.

=== 8. A design decision to make, not a bug ===
`src/cad/changes.py` permits reverting a changeset whose apply was interrupted (`after_hash` NULL)
even when the file on disk may contain a third party's later edit. That was chosen over refusing
forever. `discard()` now exists, which weakens the rationale: a user who cannot revert is no longer
stuck.
Decide which behaviour you want, implement it, and say which you chose and why. If you keep the
current one, make the response say plainly that an indeterminate revert occurred.

=== VESSEL — explicitly out of scope, do not "fix" ===
`/api/generate-vessel/confirm` writes a NEW output file rather than editing an existing drawing, so
a changeset has nothing to restore. Both reviewers confirmed this independently. Leave it.

HARD RULES
- Never weaken or delete a test to make it pass. If a pre-existing test conflicts, STOP and explain.
- Every fix needs a test that fails before it and passes after. State how you verified that.
- Items 1 and 3 concern data loss. Their tests must exercise the real ownership logic, not the fake's
  convenient shortcut — item 1 exists precisely because the fake could not reproduce reality.
- After each item: `venv\Scripts\python.exe -m pytest tests/ -q`, report exact pass/skip/fail, commit.
```

---

## Methodology note

Both adversarial agents ran concurrently against the same working tree, and each observed the other's
edits. One reported a test failure it then correctly invalidated after noticing eight files had
changed mid-run. Future verification passes should run against a clean export (`git archive <sha>`)
or sequentially, not in parallel on a live tree.
