# Module 3: Save Verification & Rollback Safety

This covers the five bugs `docs_analysis/10_project_extension_review.md` flagged in the
code that actually mutates and reverts live AutoCAD drawings — Tier 1 items 3, 4, 5, and
the two Round 2 items ("Only RESIZE_COMPONENT re-verifies...", "Rename+revert can reach a
genuinely stuck state..."). All five are fixed in `src/framework/commands/modification_executor.py`
and `src/cad/changes.py`, with new coverage in `tests/project/test_modification.py` and
`tests/project/test_changes.py`.

## The bugs

1. **Save-verification only covered `RESIZE_COMPONENT`.** (Round 2, "Only
   RESIZE_COMPONENT re-verifies the saved value against fresh extraction...".) Every
   other structured operation (`SET_ENTITY_PROPERTY`, `SET_LAYER_COLOR`,
   `SET_DOCUMENT_PROPERTY`) only checked that a saved-file re-extraction *succeeded* —
   never that the intended value actually persisted. A COM `Save()` that silently no-ops
   would still have been reported `verified_by_extraction: True`.

2. **Rollback-during-rollback wasn't exception-safe.** (Tier 1 item 4.) If a second COM
   failure happened while undoing a partially-applied multi-assignment edit (e.g. rolling
   back a connected valve's moved position after the pipe's own resize+save failed), the
   reversal loop aborted at the first failure — leaving every earlier-applied change
   un-reverted in the live, unsaved document — and the rollback's own exception replaced
   the original one instead of surfacing both.

3. **A revert could reach a permanently stuck state.** (Round 2, "Rename+revert can reach
   a genuinely stuck state...".) If `ChangeManager.revert()` restored `original_path` from
   the backup but then hit a transient failure (e.g. a locked file) removing the
   now-superfluous renamed file, retrying was blocked forever: the retry's own conflict
   guard ("Original rename destination now exists") saw the already-successfully-restored
   `original_path` and refused to proceed unconditionally, mistaking its own prior partial
   success for a genuine conflict. (Related, but distinct: Tier 1 item 3 — a plain
   crash-on-retry from `current.unlink()` lacking any tolerance for the file already being
   gone — is also addressed by this same fix, see below.)

4. **Exact-equality false negative: floating-point Normal vectors.** (Tier 1 item 5.) A
   Normal vector like `(0.0, 0.0, 0.9999999999999998)` — a real COM floating-point
   representation, not hypothetical — could spuriously reject a legitimate XY-plane
   circle/arc radius resize.

5. **Exact-equality false negative: AutoCAD's case-preserving-but-case-insensitive
   names.** (Tier 1 item 5.) Assigning `Layer="PIPES"` onto a layer actually created as
   `"Pipes"` could spuriously trigger a full rollback of an otherwise-successful edit,
   because AutoCAD is free to echo back its own stored casing rather than the casing an
   assignment sent, and the post-assignment verification used exact string equality.

## The fix

### `src/framework/commands/modification_executor.py`

**Bugs 4 & 5 — tolerant comparisons.**
- `_resize()`, line 122: `if math.dist(tuple(entity.Normal), (0.0, 0.0, 1.0)) > 1e-6:`
  replaces the old exact `tuple(entity.Normal) != (0.0, 0.0, 1.0)`. This reuses the same
  `1e-6` tolerance already used elsewhere in the function for point/distance comparisons,
  so a Normal that's numerically `(0,0,1)` up to COM floating-point noise no longer trips
  the "must be in the XY plane" rejection.
- `execute_operation()`, lines 245-253, inside the post-assignment verification loop
  (lines 240-255): a new `elif change.property in {"Layer", "Linetype"}:` branch compares
  `str(actual).casefold() != str(change.after).casefold()` instead of falling through to
  the generic `elif actual != change.after:` exact check. `Color`, `TextString`, etc. keep
  exact equality (case *is* meaningful there — a text edit that silently changed case
  should still be flagged).

**Bug 2 — rollback-during-rollback.**
- Lines 258-286, the `except Exception as original_exc:` block. Previously the rollback
  loop was a bare `for change in reversed(applied): _assign(change, change.before)` with
  no inner exception handling, so the first failing `_assign` call propagated immediately,
  skipping every remaining (earlier-applied) change's rollback and replacing the original
  exception. Now each `_assign` call is wrapped in its own `try/except`, appending a
  description to a `rollback_errors` list on failure rather than raising; the custom
  `SummaryInfo` rollback path (`info.RemoveCustomByKey`/`SetCustomByKey`) got the identical
  treatment. After the loop, if `rollback_errors` is non-empty, a new `RuntimeError` is
  raised **`from original_exc`**, with a message containing both the original exception's
  type/message and every rollback failure. `__cause__` is therefore always the true root
  cause even though a different exception type is what the caller ultimately sees. If no
  rollback step failed, the code falls through to a bare `raise`, so a fully successful
  rollback still surfaces the original, unwrapped exception exactly as before — the fix
  changes nothing about the common case.

**Bug 1 — save-verification for non-resize operations.**
- Lines 295-315, a new `elif snapshot and operation["command"] == "SET_ENTITY_PROPERTY" and
  operation["property"] != "attribute":` branch alongside the pre-existing
  `RESIZE_COMPONENT` branch. It re-extracts the saved file (already done, into `snapshot`,
  for every operation when a `verify_extractor` is supplied) and looks up
  `snapshot.properties.get(operation["handle"])`, then compares the `color` / `layer` /
  `linetype` / `text` key (whichever `operation["property"]` touched) against
  `changes[0].after` — the value that was actually assigned — using the same
  case-insensitive comparison for `layer`/`linetype` as the in-memory check above. If the
  handle isn't in the snapshot at all, or the value doesn't match, it raises `ValueError`
  ("Saved-file re-extraction did not confirm the property change").
- The `"attribute"` variant of `SET_ENTITY_PROPERTY` is deliberately excluded from this
  new branch (`operation["property"] != "attribute"`). This is correct, not an oversight:
  I confirmed by reading `src/cad/extractor/dxf_extractor.py`'s `_parse()` (lines 54-74)
  that it builds `properties[handle] = values` only for entities it iterates directly out
  of `doc.layouts` — top-level INSERT/LINE/CIRCLE/etc. entities. A block's attached ATTRIB
  entities are read via `entity.attribs` and folded into the *parent* INSERT's own record
  as `values["attributes"] = {tag: text, ...}` (line 57, 59); they are never themselves
  yielded as a separate top-level entity, so a nested ATTRIB's own handle has no entry in
  `snapshot.properties`. Confirmed independently from `_prepare()` in
  `modification_executor.py` (line 154-160): for `property == "attribute"`, the
  `Assignment`'s handle is the *attribute's* handle (`obj.Handle` after reassigning `obj`
  to the matched attribute), not `operation["handle"]` (the parent block reference's
  handle) — so even attempting the naive lookup with `operation["handle"]` would check the
  wrong entity's properties, and that entity has no `"text"` key besides. Both reasons
  point the same way: this needs its own follow-up (matching by attribute tag inside the
  parent's `attributes` dict, or similar), not a guess bolted onto this branch.
- `SET_LAYER_COLOR` and `SET_DOCUMENT_PROPERTY` remain **not** covered by this fix — there
  is no `elif` branch for either (confirmed by grepping the file: `SET_LAYER_COLOR` and
  `SET_DOCUMENT_PROPERTY` appear only in `_prepare()`/dispatch code, never inside the
  post-save verification block). The in-code comment explains the general problem this fix
  addresses and why `"attribute"` specifically is excluded, but it does not call out
  `SET_LAYER_COLOR`/`SET_DOCUMENT_PROPERTY` as a remaining gap in so many words — see "What
  remains explicitly out of scope" below.

### `src/cad/changes.py`

**Bugs 3 (and the related Tier 1 item 3) — resumable revert.**
- `ChangeManager._check_files()`, lines 168-197:
  - Lines 172-182: a new `resuming_revert = change["status"] == "reverting" and not
    current.exists()` flag. When true, the "drawing changed after this changeset" check
    (which normally requires `current_path` to exist and hash-match `after_hash`) is
    skipped entirely. This is the precise, narrow condition the task asked me to verify:
    it fires only when the file is **gone** (a prior attempt's `current.unlink()` already
    succeeded) — not merely "changed" — combined with the changeset already being
    mid-revert. A file that's merely present-but-changed still hits the normal hash check
    and is correctly rejected as a real conflict.
  - Lines 185-195: the "Original rename destination now exists" conflict check
    (triggered when `current_path != original_path` and something now exists at
    `original_path`) now only raises when `file_hash(item["original_path"]) !=
    item["before_hash"]`. This is the core of the stuck-state fix, and it's correct for a
    concrete reason: `before_hash` is the hash of the pre-edit backup — the exact bytes any
    legitimate restore would produce at `original_path`. If a *different* file appears
    there (someone else created a new file with that name, or restored something else),
    its hash will not equal `before_hash`, and the conflict is correctly still rejected. If
    it's *our own* prior revert attempt that already ran `shutil.copy2(backup,
    temporary); os.replace(temporary, original)` successfully before failing on the next
    step, the restored file is byte-identical to the backup, so its hash equals
    `before_hash` exactly, and the check now recognizes this as a resumable retry rather
    than a conflict.
- `ChangeManager.revert()`, lines 232-250: `already_restored = original.exists() and
  original != current` (line 242) skips the redundant `shutil.copy2`/`os.replace` step
  when a prior attempt already restored `original` (safe per the `_check_files` guarantee
  above — by the time this code runs, `_check_files` has already confirmed `original`'s
  hash matches `before_hash` whenever it exists). The removal of `current` is now guarded
  by `current.exists()` (line 247: `if current != original and current.exists():
  current.unlink()`) rather than calling `current.unlink()` unconditionally. I checked
  specifically whether this instead uses `missing_ok=True` on the `unlink()` call itself,
  per the task's request: **it does not** — it relies solely on the preceding
  `current.exists()` existence check, not on `Path.unlink(missing_ok=True)`. Both
  mechanisms are functionally equivalent here (either would avoid `FileNotFoundError` on
  an already-removed file), and this explicit check is what directly resolves Tier 1 item
  3 (crash-on-retry after a successful replace-but-unfinished-cleanup) in addition to
  contributing to the Round 2 stuck-state fix above. The temporary restore file's own
  cleanup (`temporary.unlink(missing_ok=True)` in the `finally`, unchanged by this diff)
  does still use `missing_ok=True`, but that's a different file (the transient `.restore`
  scratch copy), not `current`.

## How each is proven

- **Bug 4 (Normal-vector noise):**
  `test_radius_resize_tolerates_com_normal_floating_point_noise` monkeypatches
  `fake_cad.Entity.__getattr__` so `Normal` always returns `(0.0, 0.0,
  0.9999999999999998)`, then performs a radius resize and asserts it succeeds with
  `changes[0]["after"] == 15`. Without the fix, `tuple(entity.Normal) != (0.0, 0.0,
  1.0)` is `True` for this input (the tuples are not bit-identical), so `_resize` would
  raise `ValueError("Radius edits currently require a circle/arc in the XY plane")`
  before any assignment — the test's success assertion would never be reached. I agree
  this genuinely distinguishes fixed from buggy behavior: it exercises the exact failure
  mode described (COM floating-point noise on an otherwise-planar entity) rather than a
  synthetic tolerance value.

- **Bug 5 (case normalization):**
  `test_layer_property_verification_tolerates_autocad_case_normalization` monkeypatches
  `fake_cad.Entity.__getattr__` so reading `Layer` back always returns `"Pipes"`
  regardless of what was assigned, then assigns `Layer="PIPES"` and asserts the call
  succeeds with `after == "PIPES"`. Without the fix, the generic `elif actual !=
  change.after:` branch would compare `"Pipes" != "PIPES"` (`True`) and raise
  `ValueError("AutoCAD did not retain the assigned property")`, triggering a full
  rollback and propagating an exception instead of returning a result — so the test's
  success assertion would fail. Genuine.

- **Bug 1 (save-lie for non-resize operations):** two paired tests.
  `test_set_entity_property_save_lie_is_caught_by_reextraction` replaces `doc.Save` with
  a no-op that never calls `self.data.saveas(...)`, so the on-disk file never actually
  changes, then asserts a color edit raises `ValueError` matching "did not confirm the
  property change". Without the fix, there is no branch that re-checks `SET_ENTITY_PROPERTY`
  values against the snapshot — the function would return normally with
  `verified_by_extraction=True` even though the color was never actually written, exactly
  the silent-lie scenario the bug describes. `test_set_entity_property_verified_when_save_genuinely_persists`
  is the paired happy-path check (real save, asserts `verified_by_extraction is True` and
  the file's color is genuinely `3`) — it doesn't by itself distinguish fixed from buggy
  code (both would pass it), but it confirms the new check doesn't introduce a false
  positive on a save that actually works. Together they're a solid pair.

- **Bug 2 (rollback-during-rollback), the trickiest one:**
  `test_rollback_failure_does_not_mask_original_error_or_abort_remaining_rollback` builds
  a multi-assignment resize (pipe `EndPoint` plus a connected valve's `InsertionPoint`),
  makes `doc.Save` fail, and makes exactly one `InsertionPoint` assignment fail *during
  rollback* (gated on `state["save_failed"]` already being `True`, so the forward pass is
  untouched). `applied` is `[pipe EndPoint change, valve InsertionPoint change, ...]` in
  application order, so `reversed(applied)` restores the valve's `InsertionPoint` (or its
  attribute's) *before* the pipe's own `EndPoint`. The injected fault hits that first,
  earlier InsertionPoint restore; the assertions then check that (a) the raised
  `RuntimeError`'s message contains both `"save failed"` and `"rollback also failed"`, (b)
  `__cause__` is the original `RuntimeError("save failed")`, and (c) the pipe's `EndPoint`
  really was restored to `(1000, 0, 0)` — meaning rollback continued past the earlier
  failure to the pipe's own restore, which comes *after* it in the reversed loop. I traced
  through this by hand: without the fix, the bare rollback loop would raise
  `RuntimeError("rollback also failed")` the moment the injected fault fires and abort
  immediately — the pipe's `EndPoint` would never be restored (assertion (c) fails,
  it would still read the resized value), the message would contain only "rollback also
  failed" not "save failed" (assertion (a) fails), and `__cause__` would be `None` (an
  exception raised fresh inside an `except` block only gets an implicit `__context__`, not
  `__cause__`, absent an explicit `raise ... from`) (assertion (b) fails). All three
  assertions are load-bearing and each independently catches the bug — this is a genuine
  regression test, not a "no exception raised" tautology. (The task noted the implementing
  agent already hand-verified this one by reverting the fix and rerunning; my independent
  trace above reaches the same conclusion via static reasoning about the old code, so both
  methods agree.)

- **Bug 3 (stuck revert), the other trickiest one:**
  `test_rename_revert_resumes_after_transient_failure_removing_renamed_file` renames a file
  via a changeset, then monkeypatches `Path.unlink` to raise `PermissionError` specifically
  for the renamed file, and calls `revert()`. I traced the actual control flow: on the
  first `revert()` call, `original` (pre-rename path) doesn't exist yet, so the code
  performs the real `shutil.copy2`/`os.replace` restore (not the `already_restored` skip
  path), successfully recreating `original` from the backup — then the injected fault
  fires on `current.unlink()` (the renamed file), raising `PermissionError`, which
  propagates uncaught out of `revert()` (matching `pytest.raises(PermissionError)`); the
  changeset's status was already flipped to `"reverting"` *before* the per-file loop
  began, so it stays `"reverting"` rather than reverting back to `"pending"` or advancing
  to `"reverted"`. The test asserts exactly this intermediate state (`original` restored,
  renamed file still present, status `"reverting"`). On the *second* `revert()` call (real
  `unlink` restored), the first `_check_files()` call now hits the "Original rename
  destination now exists" branch — `original_path` exists (it was restored) and differs
  from `current_path` — and the fix's `file_hash(original_path) != before_hash` check
  passes (they're equal, since `original` was a byte-exact backup restore), so no
  exception is raised. **Without the fix**, this branch would raise unconditionally the
  instant `Path(original_path).exists()` is true, on *every* subsequent retry, forever —
  which is exactly the "permanently stuck, needs manual recovery" bug being described; I
  confirmed by inspecting the pre-fix code (`git diff`) that the old condition was a bare
  `if ... and Path(item["original_path"]).exists(): raise ValueError(...)` with no hash
  check at all. The retry then proceeds through `revert()`'s per-item loop, where
  `already_restored` is `True` (original exists and differs from current) so the redundant
  copy is skipped, `current.unlink()` now succeeds for real, and the changeset reaches
  `status == "reverted"` — matching the test's final assertions. One precise note for
  completeness: this specific test happens *not* to exercise the other new bypass in
  `_check_files` (the `resuming_revert` "current is gone" branch, first conflict check) —
  in this scenario `current` (the renamed file) is still present throughout both attempts,
  so that branch's condition (`not current.exists()`) never evaluates `True` here; it
  guards a related but distinct partial-failure ordering (a crash *after* a successful
  `current.unlink()` but before the changeset is marked `reverted`) that isn't the one this
  particular test drives. I verified this is a real, reachable code path by inspection, just
  not one this specific test happens to hit.

## What remains explicitly out of scope

- **`SET_LAYER_COLOR` and `SET_DOCUMENT_PROPERTY` save-verification remain unfixed.**
  Confirmed by grepping `modification_executor.py`: neither command string appears
  anywhere in the post-save verification block (only in `_prepare()`'s dispatch table and
  the `custom` `SET_DOCUMENT_PROPERTY` branch earlier in `execute_operation`). A `Save()`
  that silently no-ops on a layer-color or document-property change would still be
  reported `verified_by_extraction: True` today, exactly as before this fix — just no
  longer true for `SET_ENTITY_PROPERTY`. This is a real, currently-true gap, not something
  this diff silently claims to solve; the in-code comment on the new `elif` branch explains
  the *general* problem and the `"attribute"` exclusion specifically, but does not call out
  `SET_LAYER_COLOR`/`SET_DOCUMENT_PROPERTY` by name as remaining work.
- **The `"attribute"` variant of `SET_ENTITY_PROPERTY` save-verification remains
  unfixed**, for the structural reason explained above (nested ATTRIB entities aren't
  top-level records in `snapshot.properties`, and the assignment's own handle isn't
  `operation["handle"]` either). This exclusion is explicit and commented in the code
  (`operation["property"] != "attribute"` plus the accompanying comment), so it's a
  documented, intentional gap rather than a silent one.

## Discrepancies found

None of substance — every specific claim in the task description checked out against the
actual diffs, current file contents, and test runs. Two small precision notes worth
recording:

1. The task's bug #3 description is the Round 2 "permanently stuck state" bug specifically.
   The actual `revert()` fix (the `current.exists()` guard before `current.unlink()`) also
   happens to directly resolve the separate, narrower Round 1 Tier 1 item 3
   (`changes.py:222`, crash-on-retry from an unguarded `unlink()`), via an existence check
   rather than `Path.unlink(missing_ok=True)`. Both bugs are fixed by this diff; I called
   out the mechanism precisely above since the task asked me to check which one was used.
2. The `tests/project/test_modification.py` diff also renames/rewrites
   `test_command_schema_accepts_structured_operation_and_requires_target` into
   `test_legacy_command_schema_rejects_structured_operations` in the same patch. That test
   covers the schema-contamination bug (Tier 1 item 1, `src/framework/commands/schema.py`)
   — a different bug in a different module, already documented separately in
   `fixes/02_schema_contamination.md`. It's unrelated to save-verification/rollback safety
   and is correctly out of scope for this record; I mention it only so its presence in the
   same test-file diff isn't mistaken for part of this module's fix.

Test results (run directly, `.\venv\Scripts\python.exe`, from the repo root):

```
pytest tests/project/test_modification.py tests/project/test_changes.py -q
  → 41 passed, 7 warnings in 24.85s

pytest tests/ -q
  → 974 passed, 10 skipped, 0 failed, 29 warnings in 133.35s
```

(The review document's own baseline before this round of work was 956 passed/10 skipped;
974 reflects the new tests added across all modules being fixed in this pass, not just
this one.)
