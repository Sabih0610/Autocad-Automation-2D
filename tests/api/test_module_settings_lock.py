"""`_temporary_module_settings` (src/api/routes/title_block.py and
src/api/routes/line_list.py) monkey-patches module-level constants on a
shared `use_case` module for the duration of one request, then restores the
originals — a workaround for those use_case modules being written with
hardcoded module-level constants instead of accepting parameters, adopted
deliberately to avoid editing the use_case modules themselves.

Without a lock around the whole monkey-patch -> call -> restore critical
section, two concurrent requests race on the same shared module attributes:
request A can observe request B's overrides mid-flight, and whichever
request's `finally` runs last "restores" its own originals over the other's
still-in-flight state — for title-block editing this can mean writing the
wrong values into a drawing. This proves the fix by showing the lock is
genuinely held for the whole monkey-patch -> call -> restore duration, not
just referenced somewhere — the same technique already used to prove
`CAD_LOCK` in `tests/framework/test_command_executor.py`.
"""
from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

from src.api.routes import line_list as line_list_routes
from src.api.routes import title_block as title_block_routes


@pytest.mark.parametrize(
    "routes_module, lock_name",
    [(title_block_routes, "_SETTINGS_LOCK"), (line_list_routes, "_SETTINGS_LOCK")],
)
def test_settings_lock_is_held_for_the_whole_override_duration(routes_module, lock_name):
    fake_use_case = SimpleNamespace(SETTING="original")
    lock = getattr(routes_module, lock_name)
    entered = threading.Event()
    release = threading.Event()

    def request_a():
        with routes_module._temporary_module_settings(fake_use_case, SETTING="A-value"):
            entered.set()
            assert release.wait(timeout=5), "test setup failed: never released"

    thread = threading.Thread(target=request_a)
    thread.start()
    try:
        assert entered.wait(timeout=5), "request_a never entered"
        # A second, concurrent user of the same lock (i.e. a second request)
        # must not be able to proceed while request_a's override is active —
        # otherwise it could observe request_a's SETTING="A-value" as if it
        # were the drawing's real configuration, or race to restore over it.
        assert lock.acquire(blocking=False) is False
    finally:
        release.set()
        thread.join(timeout=5)

    # Once request_a has fully exited (override applied, then restored),
    # the lock must be free again, and the module's real value restored —
    # not stuck on request_a's override.
    assert lock.acquire(blocking=False) is True
    lock.release()
    assert fake_use_case.SETTING == "original"


@pytest.mark.parametrize("routes_module", [title_block_routes, line_list_routes])
def test_settings_are_restored_even_when_the_wrapped_call_raises(routes_module):
    fake_use_case = SimpleNamespace(SETTING="original")

    with pytest.raises(RuntimeError, match="boom"):
        with routes_module._temporary_module_settings(fake_use_case, SETTING="A-value"):
            assert fake_use_case.SETTING == "A-value"
            raise RuntimeError("boom")

    assert fake_use_case.SETTING == "original"
