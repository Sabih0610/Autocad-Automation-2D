"""
Dimension style setup for vessel drawings.

Phase 16:
- Provides one standard dimension style for vessel drawings.
- Used by ezdxf dimension entities.
"""

from __future__ import annotations

from ezdxf.document import Drawing


DIMSTYLE_NAME = "STANDARD_VESSEL"


def setup_vessel_dimstyle(doc: Drawing) -> None:
    """
    Create/update the standard vessel dimension style.

    Units:
    - Drawing units are millimeters.
    - Dimension text is whole millimeters.
    """
    doc.header["$INSUNITS"] = 4  # millimeters

    if DIMSTYLE_NAME not in doc.dimstyles:
        dimstyle = doc.dimstyles.new(DIMSTYLE_NAME)
    else:
        dimstyle = doc.dimstyles.get(DIMSTYLE_NAME)

    # Text and arrow sizing for vessel-scale drawings.
    dimstyle.dxf.dimtxt = 120.0      # text height
    dimstyle.dxf.dimasz = 90.0       # arrow size
    dimstyle.dxf.dimexe = 60.0       # extension beyond dim line
    dimstyle.dxf.dimexo = 35.0       # offset from measured point
    dimstyle.dxf.dimdec = 0          # no decimal places

    # Put dimension text above dimension line.
    dimstyle.dxf.dimtad = 1

    # Keep dimension text horizontal.
    dimstyle.dxf.dimtih = 0
    dimstyle.dxf.dimtoh = 0

    # Color: 2 = yellow
    dimstyle.dxf.dimclrd = 2
    dimstyle.dxf.dimclre = 2
    dimstyle.dxf.dimclrt = 2