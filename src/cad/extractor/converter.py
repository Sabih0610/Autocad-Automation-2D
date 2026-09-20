"""Contract for offline DWG-to-DXF conversion backends."""

from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class DWGToDXFConverter(Protocol):
    def convert(self, source: Path, workdir: Path) -> Path:
        """Write a DXF in the supplied temporary work directory and return its path."""
        ...
