import sys
import os

# Add parent dir to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from sqlalchemy.orm import Session
from backend.db.database import SessionLocal
from backend.db.models import User, Portfolio, TradeLog, TradeSide
from backend.services.auth import get_or_create_default_user
import structlog

logger = structlog.get_logger(__name__)

def seed_database():
    db: Session = SessionLocal()
    try:
        user = get_or_create_default_user(db)

        logger.info(f"Seeding data for user {user.email}...")

        # 1. Add some Portfolio Holdings
        holdings = [
            Portfolio(user_id=user.id, ticker="RELIANCE.NS", quantity=15.0, avg_cost=2950.0),
            Portfolio(user_id=user.id, ticker="TCS.NS", quantity=10.0, avg_cost=3800.0),
            Portfolio(user_id=user.id, ticker="HDFCBANK.NS", quantity=50.0, avg_cost=1450.0)
        ]
        
        # Check if already seeded
        existing = db.query(Portfolio).filter(Portfolio.user_id == user.id).first()
        if not existing:
            db.add_all(holdings)
            logger.info("Added dummy portfolio holdings.")

        # 2. Add some Trade Logs
        trades = [
            TradeLog(user_id=user.id, ticker="RELIANCE.NS", side=TradeSide.BUY, quantity=15.0, fill_price=2950.0, slippage=0.01, virtual_balance_after=user.virtual_balance - (15*2950)),
            TradeLog(user_id=user.id, ticker="TCS.NS", side=TradeSide.BUY, quantity=10.0, fill_price=3800.0, slippage=0.01, virtual_balance_after=user.virtual_balance - (15*2950) - (10*3800)),
            TradeLog(user_id=user.id, ticker="HDFCBANK.NS", side=TradeSide.BUY, quantity=50.0, fill_price=1450.0, slippage=0.01, virtual_balance_after=user.virtual_balance - (15*2950) - (10*3800) - (50*1450))
        ]
        
        existing_trades = db.query(TradeLog).filter(TradeLog.user_id == user.id).first()
        if not existing_trades:
            db.add_all(trades)
            logger.info("Added dummy trade logs.")

        db.commit()
        logger.info("Database seeding complete! Refresh the frontend.")

    except Exception as e:
        logger.error(f"Error seeding database: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    seed_database()
