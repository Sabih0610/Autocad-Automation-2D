"""A COM-shaped adapter that persists real DXF for integration tests, never DWG."""
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
    """Small COM-shaped facade over an ezdxf modelspace layout."""

    def __init__(self, layout):
        self.layout = layout

    @property
    def Count(self):
        return len(self.layout)

    def AddLine(self, start, end):
        return Entity(self.layout.add_line(_com_values(start), _com_values(end)))

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
        self.Layers = SimpleNamespace(Item=lambda name: Layer(self.data.layers.get(name)))
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
