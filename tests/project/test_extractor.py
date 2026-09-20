from dataclasses import asdict
import json
from pathlib import Path
import shutil
import pytest
import ezdxf

from src.cad.extractor import DXFExtractor, DWGToDXFConverter, ODAConverter


def make_dxf(path):
    doc = ezdxf.new()
    doc.units = 4  # millimetres
    doc.header.custom_vars.append("PROJECT", "Demo Plant")
    doc.appids.new("AUTOCAD_AI")
    line = doc.modelspace().add_line((0, 0, 0), (1000, 0, 0))
    line.set_xdata("AUTOCAD_AI", [(1000, "TAG=P-101")])
    block = doc.blocks.new("VALVE")
    block.add_circle((0, 0), 5)
    ref = doc.modelspace().add_blockref("VALVE", (1000, 0, 0))
    ref.add_attrib("TAG", "V-101", (1000, 0))
    doc.layouts.new("Sheet").add_text("Header")
    doc.saveas(path)
    return line.dxf.handle


class FakeConverter:
    def __init__(self, dxf):
        self.dxf, self.calls, self.workdirs = dxf, 0, []

    def convert(self, source, workdir):
        self.calls += 1
        self.workdirs.append(workdir)
        target = workdir / "converted.dxf"
        shutil.copy2(self.dxf, target)
        return target


def test_extract_real_dxf_all_six_shapes(tmp_path):
    path = tmp_path / "plant.dxf"
    handle = make_dxf(path)
    reader = DXFExtractor()
    assert reader.extract_document(path).units == 4
    assert reader.extract_document(path).properties["PROJECT"] == "Demo Plant"
    assert [e.tag for e in reader.extract_entities(path) if e.handle == handle] == ["P-101"]
    assert len(reader.extract_entities(path)) == 3  # includes paperspace
    assert len(reader.extract_blocks(path)) == 2
    assert reader.extract_properties(path)[handle]["xdata"]
    geometry = next(b for b in reader.extract_spatial_data(path) if b.handle == handle)
    assert geometry.end == (1000, 0, 0)
    assert len(reader.extract_relationships(path)) == 2
    json.dumps(asdict(reader.extract(path)))


def test_dwg_conversion_is_injected_cached_and_temporary(tmp_path):
    source = tmp_path / "plant.dwg"
    source.write_bytes(b"fake DWG; converter supplies a real DXF")
    dxf = tmp_path / "source.dxf"
    make_dxf(dxf)
    converter = FakeConverter(dxf)
    assert isinstance(converter, DWGToDXFConverter)
    assert isinstance(ODAConverter("unused.exe"), DWGToDXFConverter)
    reader = DXFExtractor(converter)
    assert reader.extract_document(source).path == str(source)
    assert reader.extract_entities(source)
    assert converter.calls == 1
    assert all(not path.exists() for path in converter.workdirs)


def test_missing_converter_and_invalid_files_fail_clearly(tmp_path):
    path = tmp_path / "plant.dwg"
    path.touch()
    with pytest.raises(RuntimeError, match="injected ODA"):
        DXFExtractor().extract(path)
    path = tmp_path / "broken.dxf"
    path.write_text("invalid")
    with pytest.raises(OSError, match="not a DXF"):
        DXFExtractor().extract(path)


def test_oda_adapter_uses_isolated_input_and_checks_output(tmp_path, monkeypatch):
    source = tmp_path / "plant.dwg"
    source.touch()
    work = tmp_path / "work"
    work.mkdir()
    def run(args, **kwargs):
        assert list(Path(args[1]).iterdir()) == [Path(args[1]) / source.name]
        assert kwargs["check"] and kwargs["timeout"] == 120
        make_dxf(Path(args[2]) / "plant.dxf")
    monkeypatch.setattr("src.cad.extractor.oda.subprocess.run", run)
    assert ODAConverter("fake.exe").convert(source, work).exists()
