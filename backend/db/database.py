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
