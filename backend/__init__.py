# Load environment variables from the repo-root .env before any module reads them.
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:  # python-dotenv not installed; rely on the process environment
    pass
