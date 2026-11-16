"""Zip the complete Windows bundle, sharing reads with indexers and scanners."""

import sys
import time
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


def package(source, destination):
    source = Path(source).resolve(strict=True)
    destination = Path(destination).resolve()
    for attempt in range(10):
        try:
            with ZipFile(destination, "w", compression=ZIP_DEFLATED) as archive:
                for path in sorted(source.rglob("*")):
                    if path.is_file():
                        archive.write(path, path.relative_to(source.parent))
            return
        except PermissionError:
            if attempt == 9:
                raise
            time.sleep(2)


if __name__ == "__main__":
    package(*sys.argv[1:])
