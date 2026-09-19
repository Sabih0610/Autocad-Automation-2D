import math
from ezdxf.units import conversion_factor


def from_mm(value, units):
    if not math.isfinite(value):
        raise ValueError("Dimension must be finite")
    if units == 0:
        raise ValueError("Drawing units are unspecified; set INSUNITS before a millimetre operation")
    return value * conversion_factor(4, units)
