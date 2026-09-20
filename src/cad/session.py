"""One COM critical section; documents are resolved by path, never by focus."""
from contextlib import contextmanager
import os
from pathlib import Path

from .locks import CAD_LOCK, serialized


def canonical_path(path):
    if not path or not Path(path).is_absolute():
        raise ValueError("An explicit absolute drawing path is required")
    return str(Path(path).resolve())


def same_path(a, b):
    return os.path.normcase(canonical_path(a)) == os.path.normcase(canonical_path(b))


def find_open_document(acad, target_dwg_path):
    target = canonical_path(target_dwg_path)
    for index in range(acad.Documents.Count):
        document = acad.Documents.Item(index)
        if document.FullName and same_path(document.FullName, target):
            return document
    return None


def mark_open(path, is_open):
    from src.storage.database import connection
    with connection() as conn:
        conn.execute("INSERT INTO drawing_sessions VALUES (?,?) ON CONFLICT(path) DO UPDATE SET is_open=excluded.is_open",
                     (canonical_path(path), int(is_open)))


def get_document(acad, target_dwg_path):
    path = canonical_path(target_dwg_path)
    if not Path(path).is_file():
        raise FileNotFoundError(path)
    doc = find_open_document(acad, path)
    if doc is None:
        doc = acad.Documents.Open(path)
    if not same_path(doc.FullName, path):
        raise ValueError("AutoCAD returned a different document than the explicit target")
    mark_open(path, True)
    return doc


@contextmanager
def cad_session(acad=None):
    with CAD_LOCK:
        if acad is not None:
            yield acad
            return
        import pythoncom
        pythoncom.CoInitialize()
        try:
            from src.parametric.vessel.dwg_export import _get_acad
            yield _get_acad()
        finally:
            pythoncom.CoUninitialize()


def point(value):
    import pythoncom
    import win32com.client
    return win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_R8, tuple(value))
