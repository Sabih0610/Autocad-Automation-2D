from functools import partial
import os
import pytest
from src.cad import scanner
from src.cad.extractor import DXFExtractor
from src.storage.project_repository import register_project
from tests.project.test_extractor import make_dxf, FakeConverter


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
