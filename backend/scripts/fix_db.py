import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from backend.db.database import engine
from sqlalchemy import text
import structlog

logger = structlog.get_logger(__name__)

def run_fix():
    with engine.connect() as conn:
        try:
            conn.execute(text("ALTER TABLE users ADD COLUMN name VARCHAR(255);"))
            logger.info("Added 'name' column to users table.")
        except Exception as e:
            logger.warning("Column 'name' might already exist.", error=str(e))
            
        try:
            conn.execute(text("ALTER TABLE users ADD COLUMN picture VARCHAR(500);"))
            logger.info("Added 'picture' column to users table.")
        except Exception as e:
            logger.warning("Column 'picture' might already exist.", error=str(e))
            
        conn.commit()
    logger.info("Database fix complete!")

if __name__ == "__main__":
    run_fix()
