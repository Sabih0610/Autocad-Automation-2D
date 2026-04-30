"""Minimal ezdxf hello-world smoke test."""

from __future__ import annotations

import logging
from pathlib import Path

import ezdxf


def main() -> None:
    logging.getLogger("fontTools").setLevel(logging.ERROR)

    output_dir = Path("outputs") / "scratch"
    output_dir.mkdir(parents=True, exist_ok=True)

    output_path = output_dir / "ezdxf_hello.dxf"
    document = ezdxf.new("R2010")
    modelspace = document.modelspace()
    modelspace.add_circle((0.0, 0.0), radius=50.0)
    modelspace.add_line((0.0, 0.0), (200.0, 0.0))
    document.saveas(output_path)
    print(f"DXF hello-world file written to: {output_path.resolve()}")


if __name__ == "__main__":
    main()
