"""Offline DXF/DWG extraction. DWG conversion is an injected dependency."""
from pathlib import Path
from tempfile import TemporaryDirectory

import ezdxf
from ezdxf import bbox

from .base import (DrawingExtractor, DrawingSnapshot, DocumentMetadata,
                   EntityRecord, BlockRecord, BoundingBox)
from .converter import DWGToDXFConverter


def _json_value(value):
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    try:
        return [_json_value(v) for v in value]
    except TypeError:
        return str(value)


class DXFExtractor(DrawingExtractor):
    def __init__(self, converter: DWGToDXFConverter | None = None):
        self.converter = converter
        self._key = None
        self._snapshot = None

    def extract(self, source) -> DrawingSnapshot:
        path = Path(source).resolve(strict=True)
        stat = path.stat()
        key = (str(path), stat.st_size, stat.st_mtime_ns)
        if self._key == key:
            return self._snapshot
        if path.suffix.lower() == ".dxf":
            snapshot = self._parse(ezdxf.readfile(path), path)
        elif path.suffix.lower() == ".dwg":
            if self.converter is None:
                raise RuntimeError("DWG extraction requires an injected ODA converter; configure ODA_FILE_CONVERTER")
            with TemporaryDirectory(prefix="cad-extract-") as directory:
                dxf = self.converter.convert(path, Path(directory))
                snapshot = self._parse(ezdxf.readfile(dxf), path)
        else:
            raise ValueError("Expected a .dwg or .dxf file")
        self._key, self._snapshot = key, snapshot
        return snapshot

    def _parse(self, doc, path):
        metadata = DocumentMetadata(str(path), path.name, int(doc.units),
                                    dict(doc.header.custom_vars),
                                    ["DXF does not expose full dynamic-block or associative-constraint semantics."])
        entities, properties, spatial = [], {}, []
        blocks = [BlockRecord(block.name, block.block_record.dxf.handle, False)
                  for block in doc.blocks if not block.name.startswith("*")]
        for layout in doc.layouts:
            for entity in layout:
                handle, kind = entity.dxf.handle, entity.dxftype()
                attrs = {a.dxf.tag: a.dxf.text for a in getattr(entity, "attribs", [])}
                values = {k: _json_value(v) for k, v in entity.dxf.all_existing_dxf_attribs().items()}
                values.update(layout=layout.name, attributes=attrs,
                              color=entity.dxf.get("color", 256),
                              linetype=entity.dxf.get("linetype", "BYLAYER"))
                xdata = {}
                if entity.xdata:
                    xdata = {app: [[t.code, _json_value(t.value)] for t in tags]
                             for app, tags in entity.xdata.data.items()}
                values["xdata"] = xdata
                tag = next((v for k, v in attrs.items() if k.upper() in {"TAG", "COMPONENT_TAG", "P_TAG"}), None)
                for tags in xdata.values():
                    for code, value in tags:
                        if code == 1000 and isinstance(value, str) and value.upper().startswith("TAG="):
                            tag = tag or value[4:]
                entities.append(EntityRecord(handle, "BLOCK_REF" if kind == "INSERT" else kind,
                                             entity.dxf.get("layer", "0"), tag))
                properties[handle] = values
                if kind == "INSERT":
                    blocks.append(BlockRecord(entity.dxf.name, handle, True, attrs))
                if kind in {"ACAD_PROXY_ENTITY", "ACAD_PROXY_OBJECT"}:
                    metadata.warnings.append(f"Proxy {handle}: vertical SDK semantics are unavailable")
                start = tuple(entity.dxf.start) if kind == "LINE" else None
                end = tuple(entity.dxf.end) if kind == "LINE" else None
                points = [start, end] if start else []
                if kind == "INSERT":
                    points = [tuple(entity.dxf.insert)]
                try:
                    box = bbox.extents([entity])
                    if box.has_data:
                        spatial.append(BoundingBox(handle, tuple(box.extmin), tuple(box.extmax), start, end, points))
                    elif points:
                        spatial.append(BoundingBox(handle, points[0], points[-1], start, end, points))
                except Exception as exc:
                    metadata.warnings.append(f"No bounds for {handle}: {type(exc).__name__}")
        from src.cad.relationships import infer_connections
        from src.cad.units import from_mm
        tolerance = from_mm(0.01, metadata.units) if metadata.units else 1e-6
        relationships = infer_connections(spatial, properties, tolerance)
        return DrawingSnapshot(metadata, entities, blocks, properties, relationships, spatial)

    def extract_document(self, source):
        return self.extract(source).document

    def extract_entities(self, source):
        return self.extract(source).entities

    def extract_blocks(self, source):
        return self.extract(source).blocks

    def extract_properties(self, source):
        return self.extract(source).properties

    def extract_relationships(self, source):
        return self.extract(source).relationships

    def extract_spatial_data(self, source):
        return self.extract(source).spatial_data
