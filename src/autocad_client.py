"""
AutoCAD client module (pywin32-based).

Reusable connection + drawing helpers for AutoCAD COM automation.
We use pywin32 instead of comtypes because pywin32 handles AutoCAD's
variant arrays (e.g., GetAttributes) more reliably.

Usage:
    from autocad_client import safe_connect

    cad = safe_connect()
    cad.add_circle(100, 100, 50)
    cad.zoom_extents()
"""

import sys
import win32com.client
import pythoncom


# ---------- errors ----------

class AutoCADNotRunningError(Exception):
    """Raised when AutoCAD is not running."""


class NoActiveDrawingError(Exception):
    """Raised when AutoCAD is running but no drawing is open."""


# ---------- COM-point helper ----------

def point(x, y, z=0.0):
    """
    Build a 3-element variant array of doubles for AutoCAD COM calls.
    AutoCAD expects this for any coordinate input.
    """
    return win32com.client.VARIANT(
        pythoncom.VT_ARRAY | pythoncom.VT_R8,
        (float(x), float(y), float(z)),
    )


# ---------- client ----------

class AutoCADClient:
    """Thin wrapper around the AutoCAD COM Application."""

    def __init__(self):
        self.app = self._connect()
        self.doc = self._get_active_doc()
        self.model = self.doc.ModelSpace

    def _connect(self):
        try:
            return win32com.client.GetActiveObject("AutoCAD.Application")
        except Exception:
            raise AutoCADNotRunningError(
                "AutoCAD is not running. Open AutoCAD and try again."
            )

    def _get_active_doc(self):
        try:
            doc = self.app.ActiveDocument
            _ = doc.Name
            return doc
        except Exception:
            raise NoActiveDrawingError(
                "No drawing is open in AutoCAD. Open or create a drawing, then try again."
            )

    # ---------- info ----------

    @property
    def caption(self):
        return self.app.Caption

    @property
    def drawing_name(self):
        return self.doc.Name

    # ---------- drawing helpers ----------

    def add_circle(self, x, y, radius, z=0.0):
        return self.model.AddCircle(point(x, y, z), float(radius))

    def add_line(self, x1, y1, x2, y2, z=0.0):
        return self.model.AddLine(point(x1, y1, z), point(x2, y2, z))

    def add_rectangle(self, x1, y1, x2, y2):
        coords = win32com.client.VARIANT(
            pythoncom.VT_ARRAY | pythoncom.VT_R8,
            (float(x1), float(y1),
             float(x2), float(y1),
             float(x2), float(y2),
             float(x1), float(y2)),
        )
        poly = self.model.AddLightWeightPolyline(coords)
        poly.Closed = True
        return poly

    def add_text(self, content, x, y, height=10.0, z=0.0):
        return self.model.AddText(str(content), point(x, y, z), float(height))

    def zoom_extents(self):
        self.app.ZoomExtents()

    # ---------- file ops ----------

    def open_drawing(self, path):
        """Open a DWG by absolute path. Returns the Document object."""
        self.app.Documents.Open(str(path))
        self.doc = self.app.ActiveDocument
        self.model = self.doc.ModelSpace
        return self.doc

    def save_drawing(self):
        self.doc.Save()

    def close_drawing(self, save_changes=True):
        self.doc.Close(save_changes)


def safe_connect():
    """Connect with friendly CLI error messages, or sys.exit on failure."""
    try:
        return AutoCADClient()
    except AutoCADNotRunningError as e:
        print(f"ERROR: {e}")
        sys.exit(1)
    except NoActiveDrawingError as e:
        print(f"ERROR: {e}")
        sys.exit(1)