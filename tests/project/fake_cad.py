"""A COM-shaped adapter that persists real DXF for integration tests, never DWG."""
from types import SimpleNamespace
import ezdxf


class Entity:
    names = {"LINE": "AcDbLine", "CIRCLE": "AcDbCircle", "ARC": "AcDbArc", "INSERT": "AcDbBlockReference", "TEXT": "AcDbText", "ATTRIB": "AcDbAttribute"}
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
        if name in self.fields:
            value = self.entity.dxf.get(self.fields[name])
            if name in {"StartPoint", "EndPoint", "InsertionPoint", "Center"}:
                return tuple(value)
            return value
        raise AttributeError(name)

    def __setattr__(self, name, value):
        setattr(self.entity.dxf, self.fields[name], value)

    def GetAttributes(self):
        return [Entity(e) for e in self.entity.attribs]


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
        return [Entity(e) for e in self.data.modelspace()]


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
