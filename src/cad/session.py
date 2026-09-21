"""One COM critical section; documents are resolved by path, never by focus."""
from contextlib import contextmanager
import os
from pathlib import Path

from .locks import CAD_LOCK, serialized
import warnings

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


def _snapshot_open_documents(acad):
    """Return the documents that were open before a potentially destructive open."""
    return [
        acad.Documents.Item(index)
        for index in range(acad.Documents.Count)
    ]


def _same_document_identity(left, right):
    """Compare two AutoCAD document wrappers by COM identity when available.

    Python object identity is sufficient for the test fake. Real pywin32
    Dispatch wrappers may be different Python objects referring to the same
    underlying COM object, so compare their underlying OLE objects when they
    are available.
    """
    if left is right:
        return True

    left_ole = getattr(left, "_oleobj_", None)
    right_ole = getattr(right, "_oleobj_", None)

    if left_ole is not None and right_ole is not None:
        try:
            return bool(left_ole == right_ole)
        except Exception:
            pass

    try:
        return bool(left == right)
    except Exception:
        return False


def _record_bookkeeping_failure(
    path,
    is_open,
    exc,
    bookkeeping_warnings=None,
):
    state = "open" if is_open else "closed"

    message = (
        "Drawing-session bookkeeping skipped while marking "
        f"{path!s} as {state}: {type(exc).__name__}: {exc}"
    )

    if bookkeeping_warnings is not None:
        bookkeeping_warnings.append(message)
    else:
        warnings.warn(
            message,
            RuntimeWarning,
            stacklevel=2,
        )

    return message


def summarize_bookkeeping_warnings(
    bookkeeping_warnings,
):
    if not bookkeeping_warnings:
        return None

    return " | ".join(
        str(item)
        for item in bookkeeping_warnings
    )


def open_document(
    acad,
    target_dwg_path,
    bookkeeping_warnings=None,
):
    path = canonical_path(target_dwg_path)

    if not Path(path).is_file():
        raise FileNotFoundError(path)

    open_before = _snapshot_open_documents(acad)
    existing = find_open_document(acad, path)

    if existing is not None:
        doc = existing
        opened_here = False
    else:
        doc = acad.Documents.Open(path)

        opened_here = not any(
            _same_document_identity(
                doc,
                document,
            )
            for document in open_before
        )

    if (
        opened_here
        and not same_path(
            doc.FullName,
            path,
        )
    ):
        raise ValueError(
            "AutoCAD returned a different document "
            "than the explicit target"
        )

    try:
        mark_open(
            path,
            True,
        )
    except Exception as exc:
        _record_bookkeeping_failure(
            path,
            True,
            exc,
            bookkeeping_warnings,
        )

    return doc, opened_here


def get_document(
    acad,
    target_dwg_path,
):
    doc, _opened_here = open_document(
        acad,
        target_dwg_path,
    )

    return doc


def close_document(
    doc,
    target_dwg_path,
    bookkeeping_warnings=None,
):
    """Close our document even when SQLite bookkeeping is unavailable."""
    try:
        doc.Close(False)
    finally:
        try:
            mark_open(
                target_dwg_path,
                False,
            )
        except Exception as exc:
            _record_bookkeeping_failure(
                target_dwg_path,
                False,
                exc,
                bookkeeping_warnings,
            )


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
