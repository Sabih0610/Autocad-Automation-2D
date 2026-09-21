"""A COM-shaped adapter that persists real DXF for integration tests, never DWG."""
import math
from types import SimpleNamespace
import ezdxf


class _TrueColor:
    def __init__(
        self,
        rgb=(
            0,
            0,
            0,
        ),
    ):
        (
            self.Red,
            self.Green,
            self.Blue,
        ) = (
            int(value)
            for value
            in rgb
        )

    def SetRGB(
        self,
        red,
        green,
        blue,
    ):
        self.Red = int(
            red
        )

        self.Green = int(
            green
        )

        self.Blue = int(
            blue
        )

class Entity:
    names = {
        "LINE":
            "AcDbLine",
        "CIRCLE":
            "AcDbCircle",
        "ARC":
            "AcDbArc",
        "ELLIPSE":
            "AcDbEllipse",
        "INSERT":
            "AcDbBlockReference",
        "TEXT":
            "AcDbText",
        "MTEXT":
            "AcDbMText",
        "ATTRIB":
            "AcDbAttribute",
        "LWPOLYLINE":
            "AcDbPolyline",
        "POLYLINE":
            "AcDb3dPolyline",
        "DIMENSION":
            "AcDbAlignedDimension",
    }

    fields = {
        "StartPoint":
            "start",
        "EndPoint":
            "end",
        "InsertionPoint":
            "insert",
        "Center":
            "center",
        "Radius":
            "radius",
        "Color":
            "color",
        "Layer":
            "layer",
        "Linetype":
            "linetype",
        "TextString":
            "text",
        "TagString":
            "tag",
        "XScaleFactor":
            "xscale",
        "YScaleFactor":
            "yscale",
        "ZScaleFactor":
            "zscale",
        "RadiusRatio":
            "ratio",
    }

    def __init__(
        self,
        entity,
    ):
        object.__setattr__(
            self,
            "entity",
            entity,
        )

    def __getattr__(
        self,
        name,
    ):
        kind = (
            self.entity
            .dxftype()
        )

        if (
            name
            == "ObjectName"
        ):
            return self.names[
                kind
            ]

        if (
            name
            == "Handle"
        ):
            return (
                self.entity
                .dxf
                .handle
            )

        if (
            name
            == "Normal"
        ):
            return tuple(
                self.entity
                .dxf
                .get(
                    "extrusion",
                    (
                        0,
                        0,
                        1,
                    ),
                )
            )

        if (
            name
            == "HasAttributes"
        ):
            return bool(
                getattr(
                    self.entity,
                    "attribs",
                    [],
                )
            )

        if (
            name
            == "Closed"
        ):
            return bool(
                self.entity.closed
                if kind
                == "LWPOLYLINE"
                else self.entity.is_closed
            )

        if (
            name
            == "Rotation"
        ):
            return math.radians(
                float(
                    self.entity
                    .dxf
                    .get(
                        "rotation",
                        0.0,
                    )
                )
            )

        if (
            name
            == "StartAngle"
        ):
            return float(
                self.entity
                .dxf
                .get(
                    "start_param",
                    0.0,
                )
            )

        if (
            name
            == "EndAngle"
        ):
            return float(
                self.entity
                .dxf
                .get(
                    "end_param",
                    math.tau,
                )
            )

        if (
            name
            == "TextOverride"
        ):
            return (
                self.entity
                .dxf
                .get(
                    "text",
                    "",
                )
            )

        if (
            name
            == "TrueColor"
        ):
            return _TrueColor(
                tuple(
                    self.entity.rgb
                )
                if (
                    self.entity.rgb
                    is not None
                )
                else (
                    0,
                    0,
                    0,
                )
            )

        if (
            name
            == "MajorAxis"
        ):
            return tuple(
                self.entity
                .dxf
                .major_axis
            )

        if (
            name
            == "MajorRadius"
        ):
            axis = tuple(
                self.entity
                .dxf
                .major_axis
            )

            return math.sqrt(
                sum(
                    float(value)
                    ** 2
                    for value
                    in axis
                )
            )

        if (
            name
            == "MinorRadius"
        ):
            return (
                self.__getattr__(
                    "MajorRadius"
                )
                * float(
                    self.entity
                    .dxf
                    .ratio
                )
            )

        if (
            name
            == "Coordinates"
        ):
            if (
                kind
                == "LWPOLYLINE"
            ):
                values = []

                for x, y in (
                    self.entity
                    .get_points(
                        "xy"
                    )
                ):
                    values.extend(
                        (
                            float(x),
                            float(y),
                        )
                    )

                return tuple(
                    values
                )

            if (
                kind
                == "POLYLINE"
            ):
                values = []

                for vertex in (
                    self.entity
                    .vertices
                ):
                    location = (
                        vertex
                        .dxf
                        .location
                    )

                    values.extend(
                        (
                            float(
                                location.x
                            ),
                            float(
                                location.y
                            ),
                            float(
                                location.z
                            ),
                        )
                    )

                return tuple(
                    values
                )

        if (
            name
            in self.fields
        ):
            value = (
                self.entity
                .dxf
                .get(
                    self.fields[
                        name
                    ]
                )
            )

            if (
                name
                in {
                    "StartPoint",
                    "EndPoint",
                    "InsertionPoint",
                    "Center",
                }
            ):
                return tuple(
                    value
                )

            return value

        raise AttributeError(
            name
        )

    def __setattr__(
        self,
        name,
        value,
    ):
        kind = (
            self.entity
            .dxftype()
        )

        if (
            name
            == "Closed"
        ):
            if (
                kind
                == "LWPOLYLINE"
            ):
                self.entity.closed = bool(
                    value
                )
            elif bool(
                value
            ):
                self.entity.close()
            else:
                self.entity.close(
                    False
                )

            return

        if hasattr(
            value,
            "value",
        ):
            value = tuple(
                value.value
            )

        if (
            name
            == "Rotation"
        ):
            self.entity.dxf.rotation = (
                math.degrees(
                    float(value)
                )
            )

            return

        if (
            name
            == "StartAngle"
        ):
            self.entity.dxf.start_param = (
                float(value)
            )

            return

        if (
            name
            == "EndAngle"
        ):
            self.entity.dxf.end_param = (
                float(value)
            )

            return

        if (
            name
            == "TextOverride"
        ):
            self.entity.dxf.text = str(
                value
            )

            return

        if (
            name
            == "TrueColor"
        ):
            self.entity.rgb = (
                int(
                    value.Red
                ),
                int(
                    value.Green
                ),
                int(
                    value.Blue
                ),
            )

            return

        if (
            name
            == "MajorAxis"
        ):
            self.entity.dxf.major_axis = (
                tuple(
                    value
                )
            )

            return

        if (
            name
            == "MajorRadius"
        ):
            axis = tuple(
                self.entity
                .dxf
                .major_axis
            )

            length = math.sqrt(
                sum(
                    float(
                        component
                    )
                    ** 2
                    for component
                    in axis
                )
            )

            if (
                length <= 0
            ):
                raise ValueError(
                    "ellipse major axis is zero"
                )

            factor = (
                float(value)
                / length
            )

            self.entity.dxf.major_axis = tuple(
                float(
                    component
                )
                * factor
                for component
                in axis
            )

            return

        if (
            name
            == "Coordinates"
        ):
            values = [
                float(item)
                for item
                in value
            ]

            if (
                kind
                == "LWPOLYLINE"
            ):
                self.entity.set_points(
                    list(
                        zip(
                            values[
                                0::2
                            ],
                            values[
                                1::2
                            ],
                        )
                    ),
                    format="xy",
                )

                return

            if (
                kind
                == "POLYLINE"
            ):
                for (
                    vertex,
                    xyz,
                ) in zip(
                    self.entity.vertices,
                    zip(
                        values[
                            0::3
                        ],
                        values[
                            1::3
                        ],
                        values[
                            2::3
                        ],
                    ),
                ):
                    vertex.dxf.location = (
                        xyz
                    )

                return

        if (
            name
            not in self.fields
        ):
            raise AttributeError(
                name
            )

        setattr(
            self.entity.dxf,
            self.fields[
                name
            ],
            value,
        )

    @staticmethod
    def _scale_point(
        value,
        basepoint,
        factor,
    ):
        return tuple(
            basepoint[i]
            + (
                float(
                    value[i]
                )
                - basepoint[i]
            )
            * factor
            for i
            in range(3)
        )

    def ScaleEntity(
        self,
        basepoint,
        factor,
    ):
        base = tuple(
            float(value)
            for value
            in (
                basepoint.value
                if hasattr(
                    basepoint,
                    "value",
                )
                else basepoint
            )
        )

        factor = float(
            factor
        )

        if factor <= 0:
            raise ValueError(
                "scale factor must "
                "be positive"
            )

        kind = (
            self.entity
            .dxftype()
        )

        def scale_point(
            value,
        ):
            return self._scale_point(
                value,
                base,
                factor,
            )

        if (
            kind
            == "LINE"
        ):
            self.entity.dxf.start = (
                scale_point(
                    tuple(
                        self.entity
                        .dxf
                        .start
                    )
                )
            )

            self.entity.dxf.end = (
                scale_point(
                    tuple(
                        self.entity
                        .dxf
                        .end
                    )
                )
            )

        elif (
            kind
            in {
                "CIRCLE",
                "ARC",
            }
        ):
            self.entity.dxf.center = (
                scale_point(
                    tuple(
                        self.entity
                        .dxf
                        .center
                    )
                )
            )

            self.entity.dxf.radius = (
                float(
                    self.entity
                    .dxf
                    .radius
                )
                * factor
            )

        elif (
            kind
            == "ELLIPSE"
        ):
            self.entity.dxf.center = (
                scale_point(
                    tuple(
                        self.entity
                        .dxf
                        .center
                    )
                )
            )

            self.entity.dxf.major_axis = tuple(
                float(value)
                * factor
                for value
                in (
                    self.entity
                    .dxf
                    .major_axis
                )
            )

        elif (
            kind
            == "LWPOLYLINE"
        ):
            elevation = float(
                self.entity
                .dxf
                .get(
                    "elevation",
                    0.0,
                )
            )

            points = []

            for (
                x,
                y,
                start_width,
                end_width,
                bulge,
            ) in (
                self.entity
                .get_points(
                    "xyseb"
                )
            ):
                (
                    px,
                    py,
                    pz,
                ) = scale_point(
                    (
                        x,
                        y,
                        elevation,
                    )
                )

                points.append(
                    (
                        px,
                        py,
                        start_width
                        * factor,
                        end_width
                        * factor,
                        bulge,
                    )
                )

                elevation = pz

            self.entity.set_points(
                points,
                format="xyseb",
            )

            self.entity.dxf.elevation = (
                elevation
            )

        elif (
            kind
            == "POLYLINE"
        ):
            for vertex in (
                self.entity
                .vertices
            ):
                vertex.dxf.location = (
                    scale_point(
                        tuple(
                            vertex
                            .dxf
                            .location
                        )
                    )
                )

        elif (
            kind
            == "INSERT"
        ):
            self.entity.dxf.insert = (
                scale_point(
                    tuple(
                        self.entity
                        .dxf
                        .insert
                    )
                )
            )

            self.entity.dxf.xscale = (
                float(
                    self.entity
                    .dxf
                    .get(
                        "xscale",
                        1.0,
                    )
                )
                * factor
            )

            self.entity.dxf.yscale = (
                float(
                    self.entity
                    .dxf
                    .get(
                        "yscale",
                        1.0,
                    )
                )
                * factor
            )

            self.entity.dxf.zscale = (
                float(
                    self.entity
                    .dxf
                    .get(
                        "zscale",
                        1.0,
                    )
                )
                * factor
            )

            for attrib in getattr(
                self.entity,
                "attribs",
                [],
            ):
                attrib.dxf.insert = (
                    scale_point(
                        tuple(
                            attrib
                            .dxf
                            .insert
                        )
                    )
                )

        else:
            raise ValueError(
                "ScaleEntity unsupported "
                f"in fake for {kind}"
            )

    def GetAttributes(
        self,
    ):
        return [
            Entity(entity)
            for entity
            in getattr(
                self.entity,
                "attribs",
                [],
            )
        ]

    def SetXData(
        self,
        data_types,
        data_values,
    ):
        types = list(
            data_types.value
            if hasattr(
                data_types,
                "value",
            )
            else data_types
        )

        values = list(
            data_values.value
            if hasattr(
                data_values,
                "value",
            )
            else data_values
        )

        if (
            not types
            or types[0]
            != 1001
        ):
            raise ValueError(
                "XData must start with "
                "a 1001 application-name entry"
            )

        appid = values[0]

        self.entity.set_xdata(
            appid,
            list(
                zip(
                    types[1:],
                    values[1:],
                )
            ),
        )

    def Delete(
        self,
    ):
        layout = (
            self.entity
            .get_layout()
        )

        if layout is None:
            raise RuntimeError(
                "Entity is not attached "
                "to a layout"
            )

        layout.delete_entity(
            self.entity
        )


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


_DWGPROPS_STANDARD = {
    "Title":
        2,
    "Subject":
        3,
    "Author":
        4,
    "Comments":
        6,
    "Keywords":
        7,
    "RevisionNumber":
        9,
}


class SummaryInfo:
    def __init__(
        self,
        doc,
    ):
        object.__setattr__(
            self,
            "_doc",
            doc,
        )

        object.__setattr__(
            self,
            "_custom",
            {},
        )

        for name in (
            _DWGPROPS_STANDARD
        ):
            object.__setattr__(
                self,
                name,
                "",
            )

        self._load()

    def _load(
        self,
    ):
        try:
            record = (
                self._doc
                .rootdict
                .get(
                    "DWGPROPS"
                )
            )
        except Exception:
            return

        if (
            record is None
            or not hasattr(
                record,
                "tags",
            )
        ):
            return

        reverse = {
            code:
                name
            for name, code
            in (
                _DWGPROPS_STANDARD
                .items()
            )
        }

        for tag in record.tags:
            if (
                tag.code
                in reverse
            ):
                object.__setattr__(
                    self,
                    reverse[
                        tag.code
                    ],
                    str(
                        tag.value
                    ),
                )

            elif (
                300
                <= tag.code
                <= 309
                and isinstance(
                    tag.value,
                    str,
                )
            ):
                (
                    key,
                    separator,
                    value,
                ) = (
                    tag.value
                    .partition(
                        "="
                    )
                )

                if (
                    separator
                    and key
                ):
                    self._custom[
                        key
                    ] = value

    def _sync(
        self,
    ):
        from ezdxf.lldxf.types import (
            DXFTag,
        )

        try:
            record = (
                self._doc
                .rootdict
                .get(
                    "DWGPROPS"
                )
            )
        except Exception:
            record = None

        if record is None:
            record = (
                self._doc
                .rootdict
                .add_xrecord(
                    "DWGPROPS"
                )
            )

        record.tags.clear()

        record.tags.extend(
            [
                DXFTag(
                    code,
                    str(
                        getattr(
                            self,
                            name,
                        )
                    ),
                )
                for name, code
                in (
                    _DWGPROPS_STANDARD
                    .items()
                )
            ]
            + [
                DXFTag(
                    300,
                    (
                        f"{key}="
                        f"{value}"
                    ),
                )
                for key, value
                in sorted(
                    self._custom
                    .items()
                )
            ]
        )

    def GetCustomByKey(
        self,
        key,
    ):
        if (
            key
            not in self._custom
        ):
            raise KeyError(
                key
            )

        return self._custom[
            key
        ]

    def AddCustomInfo(
        self,
        key,
        value,
    ):
        if (
            key
            in self._custom
        ):
            raise KeyError(
                key
            )

        self._custom[
            str(key)
        ] = str(
            value
        )

    def SetCustomByKey(
        self,
        key,
        value,
    ):
        if (
            key
            not in self._custom
        ):
            raise KeyError(
                key
            )

        self._custom[
            str(key)
        ] = str(
            value
        )

    def RemoveCustomByKey(
        self,
        key,
    ):
        del self._custom[
            key
        ]


class Document:
    def __init__(
        self,
        path,
    ):
        self.FullName = str(
            path
        )

        self.Name = (
            path.name
        )

        self.data = (
            ezdxf.readfile(
                path
            )
        )

        self.Saved = True
        self.closed = False

        self.SummaryInfo = (
            SummaryInfo(
                self.data
            )
        )

        self.Layers = Layers(
            self.data
        )

        self.Linetypes = (
            SimpleNamespace(
                Item=lambda name:
                    self.data
                    .linetypes
                    .get(
                        name
                    )
            )
        )

        self.RegApps = (
            SimpleNamespace(
                Add=lambda name:
                    self.data
                    .appids
                    .add(
                        name
                    )
            )
        )

        self.lookups = []
        self.save_calls = 0

    def HandleToObject(
        self,
        handle,
    ):
        self.lookups.append(
            handle
        )

        return Entity(
            self.data
            .entitydb[
                handle
            ]
        )

    def GetVariable(
        self,
        name,
    ):
        assert (
            name
            == "INSUNITS"
        )

        return self.data.units

    def Save(
        self,
    ):
        self.save_calls += 1

        self.SummaryInfo._sync()

        self.data.saveas(
            self.FullName
        )

        self.Saved = True

    def Close(
        self,
        save=False,
    ):
        assert not save

        self.closed = True

    @property
    def ModelSpace(
        self,
    ):
        return ModelSpace(
            self.data
            .modelspace()
        )

class Layer:
    def __init__(
        self,
        layer,
    ):
        self.layer = (
            layer
        )

    @property
    def Color(
        self,
    ):
        return (
            self.layer
            .dxf
            .color
        )

    @Color.setter
    def Color(
        self,
        color,
    ):
        self.layer.dxf.color = (
            color
        )


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

        requested = Path(path)
        self.opened.append(path)

        # Real AcadDocuments.Open can return an already-open Document instead
        # of creating another document object. The fake must reproduce that
        # behaviour or ownership bugs in session.open_document() remain hidden.
        #
        # samefile() compares filesystem identity rather than just the path
        # spelling, which also gives us a reliable way to test aliases.
        for doc in self.documents:
            if doc.closed or not getattr(doc, "FullName", None):
                continue

            try:
                if Path(doc.FullName).samefile(requested):
                    return doc
            except (FileNotFoundError, OSError):
                # If filesystem identity cannot be checked, retain a sensible
                # path-based fallback.
                try:
                    if Path(doc.FullName).resolve() == requested.resolve():
                        return doc
                except (FileNotFoundError, OSError):
                    pass

        doc = Document(requested)
        self.documents.append(doc)
        return doc


class Acad:
    def __init__(self, documents=()):
        self.Documents = Documents(documents)

    @property
    def ActiveDocument(self):
        raise AssertionError("Implicit active-document targeting is forbidden")
