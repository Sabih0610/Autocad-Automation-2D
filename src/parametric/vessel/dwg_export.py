"""
DXF -> DWG conversion via AutoCAD COM.

AutoCAD must be running.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pywintypes
import win32com.client


DWG_R2018 = 64
DWG_R2013 = 60
DWG_R2010 = 48
DWG_R2007 = 36

DEFAULT_DWG_VERSION = DWG_R2018

RPC_E_CALL_REJECTED = -2147418111
RPC_E_SERVERCALL_RETRYLATER = -2147417846


class AutoCADNotRunningError(Exception):
    """AutoCAD is not reachable via COM."""


class DwgExportError(Exception):
    """DWG export failed."""


def _is_busy_error(exc: Exception) -> bool:
    if isinstance(exc, pywintypes.com_error):
        try:
            return int(exc.hresult) in {
                RPC_E_CALL_REJECTED,
                RPC_E_SERVERCALL_RETRYLATER,
            }
        except Exception:
            return False

    if isinstance(exc, AttributeError):
        return True

    return False


def _com_retry(operation, description: str, attempts: int = 5, delay_seconds: float = 0.5):
    last_error = None

    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except Exception as exc:
            last_error = exc

            if not _is_busy_error(exc):
                raise

            if attempt >= attempts:
                break

            print(
                f"AutoCAD busy during {description}. Retrying {attempt}/{attempts - 1}...",
                file=sys.stderr,
            )
            time.sleep(delay_seconds * attempt)

    raise last_error


def _get_acad():
    try:
        return win32com.client.GetActiveObject("AutoCAD.Application")
    except Exception as exc:
        raise AutoCADNotRunningError(
            "AutoCAD is not running. Open AutoCAD with any drawing active and try again. "
            f"Details: {type(exc).__name__}: {exc}"
        )


def convert_dxf_to_dwg(
    dxf_path: str,
    dwg_path: str,
    dwg_version: int = DEFAULT_DWG_VERSION,
) -> dict:
    dxf = Path(dxf_path).resolve()
    dwg = Path(dwg_path).resolve()

    if not dxf.exists():
        raise FileNotFoundError(f"DXF source not found: {dxf}")

    dwg.parent.mkdir(parents=True, exist_ok=True)

    acad = _get_acad()

    doc = _com_retry(
        lambda: acad.Documents.Open(str(dxf)),
        f"opening DXF {dxf.name}",
    )

    time.sleep(0.3)

    try:
        _com_retry(lambda: doc.Name, "reading opened document name")

        _com_retry(
            lambda: doc.SaveAs(str(dwg), dwg_version),
            f"saving DWG {dwg.name}",
        )

        _com_retry(
            lambda: doc.Close(False),
            f"closing {dxf.name}",
        )

    except Exception as exc:
        try:
            doc.Close(False)
        except Exception:
            pass

        raise DwgExportError(
            f"Failed to convert {dxf.name} -> {dwg.name}: "
            f"{type(exc).__name__}: {exc}"
        )

    return {
        "ok": True,
        "dxf_path": str(dxf),
        "dwg_path": str(dwg),
        "dwg_version": dwg_version,
        "message": "DXF converted to DWG successfully.",
    }


def convert_batch(
    pairs: list[tuple[str, str]],
    dwg_version: int = DEFAULT_DWG_VERSION,
    pause_between_seconds: float = 1.5,
) -> list[dict]:
    results = []

    for index, (dxf_path, dwg_path) in enumerate(pairs):
        if index > 0:
            time.sleep(pause_between_seconds)

        try:
            results.append(convert_dxf_to_dwg(dxf_path, dwg_path, dwg_version))
        except Exception as exc:
            results.append(
                {
                    "ok": False,
                    "dxf_path": dxf_path,
                    "dwg_path": dwg_path,
                    "dwg_version": dwg_version,
                    "message": f"{type(exc).__name__}: {exc}",
                }
            )

    return results


def _cli_convert() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--dxf", required=True)
    parser.add_argument("--dwg", required=True)
    parser.add_argument("--version", type=int, default=DEFAULT_DWG_VERSION)

    args = parser.parse_args()

    result = convert_dxf_to_dwg(
        dxf_path=args.dxf,
        dwg_path=args.dwg,
        dwg_version=args.version,
    )

    print(result)


if __name__ == "__main__":
    _cli_convert()