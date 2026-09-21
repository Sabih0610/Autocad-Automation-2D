from concurrent.futures import Future
from concurrent.futures.process import BrokenProcessPool
from functools import partial
import os
import pytest
from src.cad import scanner
from src.cad.extractor import DXFExtractor
from src.storage.project_repository import register_project
from tests.project.test_extractor import make_dxf, FakeConverter


class _CrashesOnceThenSucceedsPool:
    """Simulates a real ProcessPoolExecutor whose first instance's worker
    crashes outright (every submitted task's future raises
    BrokenProcessPool, exactly as the real thing does once the pool is
    broken) — a fresh pool created on retry works normally. Uses genuine
    `concurrent.futures.Future` objects (not a duck-typed stand-in) because
    `as_completed` requires them."""

    _crash_next_instance = True

    def __init__(self, max_workers=None):
        self.should_crash = _CrashesOnceThenSucceedsPool._crash_next_instance
        _CrashesOnceThenSucceedsPool._crash_next_instance = False

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def submit(self, fn, *args):
        future = Future()
        if self.should_crash:
            future.set_exception(BrokenProcessPool("simulated worker crash"))
        else:
            try:
                future.set_result(fn(*args))
            except Exception as exc:  # pragma: no cover - defensive
                future.set_exception(exc)
        return future


def test_parallel_scan_and_unchanged_rescan_do_no_extraction(tmp_path, monkeypatch):
    root = tmp_path / "plant"
    root.mkdir()
    for index in range(3):
        make_dxf(root / f"{index}.dxf")
    project = register_project("Plant", str(root))
    first = scanner.scan_project(project, max_workers=2)
    assert first == dict(discovered=3, extracted=3, skipped=0, errors=[])
    assert len(scanner.list_drawings(project)) == 3
    def forbidden(*args):
        pytest.fail("Unchanged scans must not hash or extract")
    monkeypatch.setattr(scanner, "file_hash", forbidden)
    assert scanner.scan_project(project, extractor_factory=forbidden)["skipped"] == 3


def test_any_backups_subfolder_within_the_project_is_excluded(tmp_path):
    """Previously only the app's own root-level `backups/` folder
    (`src.backup.BACKUP_ROOT`) was excluded — a project scanned at this
    repo's own root would still index the separate, older `src/backups/`
    folder's stale `.dwg` files as if they were live project drawings. Any
    directory literally named "backups" anywhere under the scanned root
    must be skipped, regardless of its exact location."""
    root = tmp_path / "plant"
    root.mkdir()
    make_dxf(root / "live.dxf")
    (root / "backups" / "2026-01-01").mkdir(parents=True)
    make_dxf(root / "backups" / "2026-01-01" / "stale.dxf")
    (root / "nested" / "backups").mkdir(parents=True)
    make_dxf(root / "nested" / "backups" / "also_stale.dxf")

    project = register_project("Plant", str(root))
    report = scanner.scan_project(project, max_workers=1)
    assert report == dict(discovered=1, extracted=1, skipped=0, errors=[])
    assert [d["filename"] for d in scanner.list_drawings(project)] == ["live.dxf"]


def test_a_project_root_named_backups_is_not_wrongly_excluded(tmp_path):
    """The exclusion must only apply to "backups" directories *within* the
    scanned tree — a project whose own root happens to live under a
    "backups"-named ancestor (outside what's being scanned) must still be
    scanned normally."""
    root = tmp_path / "backups" / "plant"
    root.mkdir(parents=True)
    make_dxf(root / "live.dxf")

    project = register_project("Plant", str(root))
    report = scanner.scan_project(project, max_workers=1)
    assert report == dict(discovered=1, extracted=1, skipped=0, errors=[])


def test_broken_process_pool_only_retries_files_never_attempted(tmp_path):
    """A worker process crashing outright while extracting ONE file
    previously marked every other still-pending file in that batch as
    errored too, when they were never even attempted — collateral damage
    from `BrokenProcessPool` propagating out of `future.result()` for
    every unfinished future in the same broken pool. This proves the
    retry-in-a-fresh-pool behavior: with a pool whose *first* instance
    crashes for every task and whose *second* instance succeeds normally,
    every file should still end up extracted, none reported as an error."""
    _CrashesOnceThenSucceedsPool._crash_next_instance = True
    root = tmp_path / "plant"
    root.mkdir()
    for index in range(3):
        make_dxf(root / f"{index}.dxf")
    project = register_project("Plant", str(root))

    report = scanner.scan_project(project, max_workers=2, pool_factory=_CrashesOnceThenSucceedsPool)

    assert report["errors"] == []
    assert report["extracted"] == 3
    assert report["skipped"] == 0
    assert len(scanner.list_drawings(project)) == 3


def test_extractor_call_count_stays_zero_on_unchanged_rescan(tmp_path, monkeypatch):
    for index in range(4):
        make_dxf(tmp_path / f"{index}.dxf")
    project = register_project("Plant", str(tmp_path))
    original_extract = DXFExtractor.extract
    extracted_paths = []

    def counted_extract(self, source):
        extracted_paths.append(str(source))
        return original_extract(self, source)

    monkeypatch.setattr(DXFExtractor, "extract", counted_extract)
    first = scanner.scan_project(project, max_workers=1)
    assert first["extracted"] == 4
    assert len(extracted_paths) == 4
    assert len(scanner.list_drawings(project)) == 4

    second = scanner.scan_project(project, max_workers=1)
    assert second["skipped"] == 4
    assert second["extracted"] == 0
    assert len(extracted_paths) == 4  # no extractor call on the second scan


def test_dwg_folder_uses_fake_converter_and_reextracts_zero(tmp_path):
    root = tmp_path / "plant"
    root.mkdir()
    dxf = tmp_path / "fixture.dxf"
    make_dxf(dxf)
    for name in ("a.dwg", "b.DWG"):
        (root / name).write_bytes(b"DWG test seam")
    project = register_project("Plant", str(root))
    converter = FakeConverter(dxf)
    factory = partial(DXFExtractor, converter)
    assert scanner.scan_project(project, extractor_factory=factory, max_workers=1)["extracted"] == 2
    assert scanner.scan_project(project, extractor_factory=factory, max_workers=1)["extracted"] == 0
    assert converter.calls == 2


def test_mtime_only_hash_match_skips_and_changed_content_extracts(tmp_path):
    path = tmp_path / "a.dxf"
    make_dxf(path)
    project = register_project("Plant", str(tmp_path))
    scanner.scan_project(project, max_workers=1)
    old = path.stat()
    os.utime(path, ns=(old.st_atime_ns, old.st_mtime_ns + 1_000_000_000))
    assert scanner.scan_project(project, max_workers=1)["skipped"] == 1
    import ezdxf
    doc = ezdxf.readfile(path)
    doc.modelspace().add_circle((20, 20), 8)
    doc.saveas(path)
    assert scanner.scan_project(project, max_workers=1)["extracted"] == 1


def test_scan_errors_retry_and_missing_files_are_marked(tmp_path):
    path = tmp_path / "a.dxf"
    path.write_text("broken")
    project = register_project("Plant", str(tmp_path))
    assert len(scanner.scan_project(project, max_workers=1)["errors"]) == 1
    make_dxf(path)
    assert scanner.scan_project(project, max_workers=1)["extracted"] == 1
    path.unlink()
    assert len(scanner.scan_project(project, max_workers=1)["errors"]) == 1
    assert scanner.list_drawings(project)[0]["scan_status"] == "error"


def test_file_changed_during_extraction_is_not_published(tmp_path):
    path = tmp_path / "a.dxf"
    make_dxf(path)
    project = register_project("Plant", str(tmp_path))
    class ChangingExtractor(DXFExtractor):
        def extract(self, source):
            snapshot = super().extract(source)
            with open(source, "a") as stream:
                stream.write("changed")
            return snapshot
    report = scanner.scan_project(project, extractor_factory=ChangingExtractor, max_workers=1)
    assert report["extracted"] == 0
    assert "changed during extraction" in report["errors"][0]["error"]
