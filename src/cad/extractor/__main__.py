"""Usage: python -m src.cad.extractor drawing.dxf [--oda-executable PATH]."""
import argparse
from dataclasses import asdict
import json
import os

from .dxf_extractor import DXFExtractor
from .oda import ODAConverter


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path")
    parser.add_argument("--oda-executable", default=os.getenv("ODA_FILE_CONVERTER"))
    args = parser.parse_args()
    converter = ODAConverter(args.oda_executable) if args.oda_executable else None
    print(json.dumps(asdict(DXFExtractor(converter).extract(args.path)), indent=2))


if __name__ == "__main__":
    main()
