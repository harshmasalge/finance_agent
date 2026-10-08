from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
import redis
import os

# PostgreSQL connection using psycopg2
POSTGRES_URL = os.getenv("POSTGRES_URL", "postgresql://postgres:password@localhost:5432/finsight")
engine = create_engine(POSTGRES_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

# Redis connection
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
redis_client = redis.from_url(REDIS_URL)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Columns added after the tables first shipped. create_all() only creates missing tables, so add these by hand.
_ADDED_COLUMNS = [
    ("alert_log", "citations", "JSON"),
    ("sentiment_scores", "window_hours", "INTEGER"),
]
_schema_ready = False


def ensure_schema(bind=None) -> None:
    """Create missing tables and columns. Idempotent; called by the API on startup and by the Celery tasks."""
    global _schema_ready
    if _schema_ready and bind is None:
        return
    from sqlalchemy import inspect, text
    from backend.db import models  # noqa: F401  (register tables)
    bind = bind or engine
    Base.metadata.create_all(bind=bind)
    insp = inspect(bind)
    with bind.begin() as conn:
        for table, col, typ in _ADDED_COLUMNS:
            if table in insp.get_table_names() and col not in {c["name"] for c in insp.get_columns(table)}:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {typ}"))
    if bind is engine:
        _schema_ready = True
