import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

import structlog
from backend.db.database import SessionLocal, Base, engine
from backend.db.models import User, TradeSide
from backend.services.trading_engine import TradingEngine, TradeException

logger = structlog.get_logger(__name__)

def run_test_trade():
    db = SessionLocal()
    
    # 1. Create a dummy user if not exists
    user = db.query(User).filter_by(email="test@finsight.ai").first()
    if not user:
        user = User(email="test@finsight.ai", virtual_balance=100000.0)
        db.add(user)
        db.commit()
        db.refresh(user)
        logger.info("Created dummy user", user_id=user.id, balance=user.virtual_balance)
        
    engine_service = TradingEngine(db)
    
    # 2. Try to execute a BUY trade
    ticker = "RELIANCE.NS"
    quantity = 5.0
    logger.info("Attempting BUY trade", ticker=ticker, quantity=quantity)
    try:
        log = engine_service.execute_trade(user.id, ticker, TradeSide.BUY, quantity)
        logger.info("Trade Success!", trade_id=log.id, fill_price=log.fill_price, new_balance=log.virtual_balance_after)
    except TradeException as e:
        logger.error("Trade failed", error=str(e))
        
    db.close()

if __name__ == "__main__":
    run_test_trade()
