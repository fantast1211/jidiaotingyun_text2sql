"""Pytest configuration - adds backend/ to Python path."""

import sys
from pathlib import Path

# Add backend directory to Python path so `app` package can be imported
backend_dir = str(Path(__file__).parent.parent / "backend")
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)
