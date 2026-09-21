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


def open_document(acad, target_dwg_path):
    """Resolve a document by path, reporting whether *this call* opened it.

    Returns `(document, opened_here)`. A caller that opens a drawing for the
    duration of one operation has to close it again — otherwise every request
    with an explicit target leaves another drawing open in the user's AutoCAD
    session, accumulating until they notice. But it must never close one the
    user already had open, and `opened_here` is the only way to tell the two
    apart after the fact.
    """
    path = canonical_path(target_dwg_path)
    if not Path(path).is_file():
        raise FileNotFoundError(path)
    existing = find_open_document(acad, path)
    doc = acad.Documents.Open(path) if existing is None else existing
    if not same_path(doc.FullName, path):
        raise ValueError("AutoCAD returned a different document than the explicit target")
    mark_open(path, True)
    return doc, existing is None


def get_document(acad, target_dwg_path):
    doc, _opened_here = open_document(acad, target_dwg_path)
    return doc


def close_document(doc, target_dwg_path):
    """Close a document this process opened and clear its open marker.

    The marker has to be cleared even if the close fails, otherwise
    `rename_file`'s open-file guard refuses to rename the drawing for the rest
    of the process's life. Never call this for a document the user already had
    open — see `open_document`.
    """
    try:
        doc.Close(False)
    finally:
        try:
            mark_open(target_dwg_path, False)
        except Exception:
            pass


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
