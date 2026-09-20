"""Optional converter. Never downloads software or launches AutoCAD."""
from dataclasses import dataclass
from pathlib import Path
import shutil
import subprocess

from .converter import DWGToDXFConverter


@dataclass(frozen=True)
class ODAConverter(DWGToDXFConverter):
    executable: str
    timeout: float = 120

    def convert(self, source: Path, workdir: Path) -> Path:
        # An isolated input directory prevents accidentally converting sibling files.
        input_dir, output_dir = workdir / "input", workdir / "output"
        input_dir.mkdir()
        output_dir.mkdir()
        shutil.copy2(source, input_dir / source.name)
        subprocess.run([self.executable, str(input_dir), str(output_dir),
                        "ACAD2018", "DXF", "0", "1", "*.dwg"],
                       check=True, timeout=self.timeout, capture_output=True)
        result = next((p for p in output_dir.iterdir()
                       if p.suffix.lower() == ".dxf" and p.stem.casefold() == source.stem.casefold()), None)
        if result is None:
            raise RuntimeError(f"ODA produced no DXF for {source.name}")
        return result
