"""Optional ODA File Converter integration.

Never downloads software and never launches AutoCAD.
"""

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import subprocess

from .converter import (
    DWGToDXFConverter,
)


ODA_ENV_VAR = (
    "ODA_FILE_CONVERTER"
)

ODA_INSTALL_URL = (
    "https://www.opendesign.com/"
    "guestfiles/oda_file_converter"
)


def oda_configuration_error(
    value=None,
):
    detail = (
        (
            f"{ODA_ENV_VAR} "
            "is not set"
        )
        if not value
        else (
            f"{ODA_ENV_VAR} does not "
            "point to an existing file: "
            f"{value}"
        )
    )

    return RuntimeError(
        "DWG extraction requires "
        "an injected ODA converter. "
        "DWG scanning uses the "
        "ODA File Converter. "
        f"{detail}. "
        "Install ODA File Converter from "
        f"{ODA_INSTALL_URL} and set "
        f"{ODA_ENV_VAR} to the full path "
        "of the converter executable."
    )


def require_oda_converter():
    raw = os.getenv(
        ODA_ENV_VAR,
        "",
    ).strip()

    if not raw:
        raise (
            oda_configuration_error()
        )

    executable = (
        Path(
            raw
        )
        .expanduser()
    )

    if not executable.is_file():
        raise (
            oda_configuration_error(
                raw
            )
        )

    return ODAConverter(
        str(
            executable
        )
    )


@dataclass(
    frozen=True
)
class ODAConverter(
    DWGToDXFConverter
):
    executable: str
    timeout: float = 120

    def convert(
        self,
        source: Path,
        workdir: Path,
    ) -> Path:
        # Do not validate the path here.
        # Injected converters are allowed
        # in tests; environment-created
        # converters are validated by
        # require_oda_converter().
        executable = (
            Path(
                self.executable
            )
            .expanduser()
        )

        input_dir = (
            workdir
            / "input"
        )

        output_dir = (
            workdir
            / "output"
        )

        input_dir.mkdir()

        output_dir.mkdir()

        shutil.copy2(
            source,
            input_dir
            / source.name,
        )

        subprocess.run(
            [
                str(
                    executable
                ),
                str(
                    input_dir
                ),
                str(
                    output_dir
                ),
                "ACAD2018",
                "DXF",
                "0",
                "1",
                "*.dwg",
            ],
            check=True,
            timeout=
                self.timeout,
            capture_output=True,
        )

        result = next(
            (
                path
                for path
                in output_dir.iterdir()
                if (
                    path.suffix.lower()
                    == ".dxf"
                    and (
                        path
                        .stem
                        .casefold()
                        == source
                        .stem
                        .casefold()
                    )
                )
            ),
            None,
        )

        if result is None:
            raise RuntimeError(
                "ODA produced no DXF "
                f"for {source.name}"
            )

        return result
