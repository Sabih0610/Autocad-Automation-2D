"""A COM-shaped adapter that persists real DXF for integration tests, never DWG."""
import math
from types import SimpleNamespace
import ezdxf


class Entity:
    names = {"LINE": "AcDbLine", "CIRCLE": "AcDbCircle", "ARC": "AcDbArc", "INSERT": "AcDbBlockReference",
             "TEXT": "AcDbText", "ATTRIB": "AcDbAttribute", "LWPOLYLINE": "AcDbPolyline"}
    fields = {"StartPoint": "start", "EndPoint": "end", "InsertionPoint": "insert", "Center": "center",
              "Radius": "radius", "Color": "color", "Layer": "layer", "Linetype": "linetype", "TextString": "text", "TagString": "tag"}

    def __init__(self, entity):
        object.__setattr__(self, "entity", entity)

    def __getattr__(self, name):
        if name == "ObjectName":
            return self.names[self.entity.dxftype()]
        if name == "Handle":
            return self.entity.dxf.handle
        if name == "Normal":
            return tuple(self.entity.dxf.get("extrusion", (0, 0, 1)))
        if name == "HasAttributes":
            return bool(self.entity.attribs)
        if name == "Closed":
            # `closed` is a real Python property on LWPolyline/Polyline
            # (backed by a bit in `dxf.flags`), not a `dxf.closed` attribute —
            # ezdxf raises `DXFAttributeError` if you try the generic
            # `fields`-mapped path below, so it needs its own case.
            return bool(self.entity.closed)
        if name in self.fields:
            value = self.entity.dxf.get(self.fields[name])
            if name in {"StartPoint", "EndPoint", "InsertionPoint", "Center"}:
                return tuple(value)
            return value
        raise AttributeError(name)

    def __setattr__(self, name, value):
        if name == "Closed":
            self.entity.closed = bool(value)
            return
        # Real AutoCAD requires a `win32com.client.VARIANT` for point-valued
        # properties and rejects a bare tuple, so `src/cad/session.py`'s
        # `point()` builds one. A VARIANT is not iterable and ezdxf cannot
        # consume it directly — unwrap via `.value`, exactly as real COM does
        # internally. Without this the whole test suite had to monkeypatch
        # `point` to `tuple`, which meant the real VARIANT path was never
        # exercised anywhere.
        if hasattr(value, "value"):
            value = tuple(value.value)
        setattr(self.entity.dxf, self.fields[name], value)

    def GetAttributes(self):
        return [Entity(e) for e in self.entity.attribs]

    def SetXData(self, data_types, data_values):
        """Mirror real AutoCAD's `SetXData(DataType, DataValue)` contract.

        The first entry must be group code 1001 (the registered application
        name); the rest are the actual XData tags. Persisted through ezdxf's own
        `set_xdata` on the wrapped real entity so a save+reload round trip (as
        every integration test in this suite does) produces exactly the XData
        shape `src/cad/extractor/dxf_extractor.py` reads back.

        `data_types`/`data_values` may be real `win32com.client.VARIANT`
        instances (pywin32 is genuinely installed here, so
        `executor.py`'s `_apply_entity_tag` constructs real ones) rather than
        plain lists — `VARIANT` is not itself iterable, so unwrap via `.value`.
        """
        types = list(data_types.value if hasattr(data_types, "value") else data_types)
        values = list(data_values.value if hasattr(data_values, "value") else data_values)
        if not types or types[0] != 1001:
            raise ValueError("XData must start with a 1001 application-name entry")
        appid = values[0]
        tags = list(zip(types[1:], values[1:]))
        self.entity.set_xdata(appid, tags)

    def Delete(self):
        layout = self.entity.get_layout()
        if layout is None:
            raise RuntimeError("Entity is not attached to a layout")
        layout.delete_entity(self.entity)


def _com_values(value):
    return tuple(value.value if hasattr(value, "value") else value)


class ModelSpace:
    """A COM-shaped facade over an ezdxf modelspace layout.

    This deliberately mirrors `AcadModelSpace`'s creation surface rather than
    being a plain list, because `src/framework/commands/executor.py` reaches
    every one of these methods. When this was a list, the executor's entire
    creation path (its LINE/CIRCLE/ARC/ELLIPSE/POLYLINE/TEXT/DIM branches)
    could never run under test, and the `hasattr(msp, "AddLightWeightPolyline")`
    fallback at executor.py:288 was unreachable.

    Unit conventions are AutoCAD's, not ezdxf's, and the difference matters:
    COM `AddArc` takes angles in RADIANS while `ezdxf.add_arc` takes DEGREES,
    so a fake that forwarded them unchanged would silently store wrong arcs and
    any test asserting on them would lock in the wrong behaviour.
    """

    def __init__(self, layout):
        self.layout = layout

    @property
    def Count(self):
        return len(self.layout)

    def Item(self, index):
        return Entity(self.layout[index])

    def AddLine(self, start, end):
        return Entity(self.layout.add_line(_com_values(start), _com_values(end)))

    def AddCircle(self, center, radius):
        return Entity(self.layout.add_circle(_com_values(center), float(radius)))

    def AddArc(self, center, radius, start_angle, end_angle):
        # COM supplies radians; ezdxf stores degrees.
        return Entity(
            self.layout.add_arc(
                _com_values(center),
                float(radius),
                math.degrees(float(start_angle)),
                math.degrees(float(end_angle)),
            )
        )

    def AddEllipse(self, center, major_axis, ratio):
        # `major_axis` is a vector relative to `center`, which is what real
        # AutoCAD expects and what ezdxf's `major_axis` also means.
        return Entity(
            self.layout.add_ellipse(
                _com_values(center),
                major_axis=_com_values(major_axis),
                ratio=float(ratio),
            )
        )

    def AddLightWeightPolyline(self, flat_points):
        values = [float(value) for value in _com_values(flat_points)]
        points = list(zip(values[0::2], values[1::2]))
        return Entity(self.layout.add_lwpolyline(points))

    def AddPolyline(self, flat_points):
        values = [float(value) for value in _com_values(flat_points)]
        points = list(zip(values[0::3], values[1::3], values[2::3]))
        return Entity(self.layout.add_polyline3d(points))

    def AddText(self, text, position, height):
        entity = self.layout.add_text(str(text), height=float(height))
        entity.dxf.insert = _com_values(position)
        return Entity(entity)

    def AddMText(self, text):
        return Entity(self.layout.add_mtext(str(text)))

    def AddDimAligned(self, start, end, dim_line_position):
        p1 = _com_values(start)
        p2 = _com_values(end)
        via = _com_values(dim_line_position)
        # COM positions the dimension line by a point; ezdxf by a perpendicular
        # offset. Project the point onto the measurement line's normal so the
        # rendered dimension lands where AutoCAD would put it.
        dx, dy = p2[0] - p1[0], p2[1] - p1[1]
        length = math.hypot(dx, dy)
        if length == 0:
            distance = 0.0
        else:
            distance = ((via[0] - p1[0]) * -dy + (via[1] - p1[1]) * dx) / length
        dim = self.layout.add_aligned_dim(p1=p1[:2], p2=p2[:2], distance=distance)
        dim.render()
        return Entity(dim.dimension)

    def __iter__(self):
        return (Entity(entity) for entity in self.layout)

    def __len__(self):
        return len(self.layout)

    def __getitem__(self, index):
        return Entity(self.layout[index])


class Document:
    def __init__(self, path):
        self.FullName = str(path)
        self.Name = path.name
        self.data = ezdxf.readfile(path)
        self.Saved = True
        self.closed = False
        self.SummaryInfo = SimpleNamespace(Title="", Author="", Subject="", Keywords="", Comments="", RevisionNumber="")
        self.Layers = Layers(self.data)
        self.Linetypes = SimpleNamespace(Item=lambda name: self.data.linetypes.get(name))
        self.RegApps = SimpleNamespace(Add=lambda name: self.data.appids.add(name))
        self.lookups = []
        self.save_calls = 0

    def HandleToObject(self, handle):
        self.lookups.append(handle)
        return Entity(self.data.entitydb[handle])

    def GetVariable(self, name):
        assert name == "INSUNITS"
        return self.data.units

    def Save(self):
        self.save_calls += 1
        self.data.saveas(self.FullName)
        self.Saved = True

    def Close(self, save=False):
        assert not save
        self.closed = True

    @property
    def ModelSpace(self):
        return ModelSpace(self.data.modelspace())


class Layer:
    def __init__(self, layer):
        self.layer = layer

    @property
    def Color(self):
        return self.layer.dxf.color

    @Color.setter
    def Color(self, color):
        self.layer.dxf.color = color


class Layers:
    """COM-shaped `AcadLayers`: `Item` raises for a missing layer, `Add` creates.

    `executor.ensure_layer` depends on exactly that pairing — it calls `Item`
    first and only falls back to `Add` when `Item` raises. A fake exposing only
    `Item` made every layer-bearing command fail, which is what kept the
    executor's creation branches untested.
    """

    def __init__(self, doc):
        self.doc = doc

    def Item(self, name):
        table = self.doc.layers
        if not table.has_entry(name):
            raise KeyError(f"layer not found: {name}")
        return Layer(table.get(name))

    def Add(self, name):
        return Layer(self.doc.layers.add(name))


class Documents:
    def __init__(self, documents=()):
        self.documents = list(documents)
        self.opened = []

    @property
    def Count(self):
        return len([d for d in self.documents if not d.closed])

    def Item(self, index):
        return [d for d in self.documents if not d.closed][index]

    def Open(self, path):
        from pathlib import Path
        self.opened.append(path)
        doc = Document(Path(path))
        self.documents.append(doc)
        return doc


class Acad:
    def __init__(self, documents=()):
        self.Documents = Documents(documents)

    @property
    def ActiveDocument(self):
        raise AssertionError("Implicit active-document targeting is forbidden")
