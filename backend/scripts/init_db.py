import sys
import os

# Add parent dir to path so we can import backend
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

import structlog
from sqlalchemy import text
from backend.db.database import engine, Base
from backend.db.models import OHLCVData

logger = structlog.get_logger(__name__)

def init_db():
    logger.info("Creating database tables...")
    # Create all tables (this creates the standard postgres tables)
    Base.metadata.create_all(bind=engine)
    
    logger.info("Creating additional indexes...")
    try:
        with engine.connect() as conn:
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_alert_log_user_read ON alert_log(user_id, is_read);"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_signal_log_created_at ON signal_log(created_at);"))
            conn.commit()
    except Exception as e:
        logger.error("Failed to create indexes", error=str(e))
    
    logger.info("Converting OHLCV table to TimescaleDB hypertable (if not already converted)...")
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT create_hypertable('ohlcv_data', 'timestamp', if_not_exists => TRUE);"))
            conn.commit()
            logger.info("Hypertable creation successful")
    except Exception as e:
        logger.error("Failed to create hypertable", error=str(e))

if __name__ == "__main__":
    init_db()
