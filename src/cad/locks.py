"""Shared scan/write serialization without importing AutoCAD integration code."""

from functools import wraps
from threading import RLock


CAD_LOCK = RLock()


def serialized(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with CAD_LOCK:
            return function(*args, **kwargs)

    return wrapped
