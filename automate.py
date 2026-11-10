#!/usr/bin/env python3
"""FII's simple, sequential command-line entry point."""

from __future__ import annotations

import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE / "src"))

from fii.runner import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
