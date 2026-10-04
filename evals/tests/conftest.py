"""Make the repository root importable so `backend.*` and `evals.*` resolve under pytest."""
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.environ.setdefault("POSTGRES_URL", "sqlite:///:memory:")
