"""Expose the backend application package when commands run from the repository root."""

from __future__ import annotations

import sys
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parent.parent / "backend"
_backend_root = str(_BACKEND_ROOT)
if _backend_root not in sys.path:
    sys.path.insert(0, _backend_root)

__path__.append(str(_BACKEND_ROOT / "app"))
