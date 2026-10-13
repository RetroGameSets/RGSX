"""Select the system sqlite3 module or RGSX's bundled fallback."""

import sys
from pathlib import Path

try:
    import sqlite3
except ModuleNotFoundError as exc:
    if exc.name not in {"sqlite3", "_sqlite3"}:
        raise

    vendor_directory = str(Path(__file__).resolve().parent / "vendor")
    if vendor_directory not in sys.path:
        sys.path.insert(0, vendor_directory)

    from pysqlite3 import dbapi2 as sqlite3 #type: ignore
