"""Pure geometry for dimension changes. No model, COM or file access."""
import math


def resize_endpoint(start, end, *, delta=None, value=None):
    if len(start) != 3 or len(end) != 3 or not all(math.isfinite(v) for v in (*start, *end)):
        raise ValueError("Endpoints must be finite 3D coordinates")
    length = math.dist(start, end)
    if length <= 1e-9:
        raise ValueError("Cannot resize a zero-length line")
    desired = value if value is not None else length + delta
    if not math.isfinite(desired) or desired <= 1e-9:
        raise ValueError("New length must be positive and finite")
    return tuple(a + (b - a) * desired / length for a, b in zip(start, end))


def box_for_points(start, end):
    return {f"{kind}_{axis}": function(a, b) for axis, a, b in zip("xyz", start, end)
            for kind, function in (("min", min), ("max", max))}
