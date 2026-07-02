#!/usr/bin/env python3
"""Run the unit test suite (integration tests skipped unless DATABASE_URL is set)."""

from __future__ import annotations

import subprocess
import sys


def main() -> int:
    cmd = [sys.executable, "-m", "pytest", "tests/", "-ra"]
    if not __import__("os").environ.get("DATABASE_URL", "").startswith("mysql"):
        cmd.extend(["-m", "not integration"])
        print("[tests] DATABASE_URL not set — running unit tests only")
    return subprocess.call(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
