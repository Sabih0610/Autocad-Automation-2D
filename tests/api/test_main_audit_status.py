"""`_status_from_result` decides how the audit middleware (`AuditJobMiddleware`
in `src/api/main.py`) classifies a route's response in the `jobs` table.

Most routes signal failure via `{"ok": False, ...}`. The newer project/
changeset routes (`src/api/routes/projects.py`, `src/api/routes/changes.py`)
return the underlying `jobs_multi_file`/`change_sets` database row directly,
which has no `"ok"` key at all — failure is a `{"status": "error", ...}`
field instead. Before this fix, a genuinely failed multi-file job or
changeset execution was silently audit-logged as `status="ok"`, because
`_status_from_result` only ever checked for `ok is False`.
"""
from src.api.main import _status_from_result


def test_ok_false_is_still_recognized_as_error():
    assert _status_from_result({"ok": False}) == "error"


def test_ok_true_is_recognized_as_ok():
    assert _status_from_result({"ok": True}) == "ok"


def test_status_error_is_recognized_as_error():
    assert _status_from_result({"job_id": "x", "status": "error", "error": "boom"}) == "error"


def test_non_error_status_values_are_not_misread_as_failures():
    for status in ("pending", "running", "done", "applying", "kept", "reverted", "active", "scanned"):
        assert _status_from_result({"status": status}) == "ok"


def test_non_dict_payload_defaults_to_ok():
    assert _status_from_result("not a dict") == "ok"
    assert _status_from_result(None) == "ok"
