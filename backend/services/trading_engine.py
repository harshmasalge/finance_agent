import structlog
from typing import Dict, Any, Tuple
from sqlalchemy.orm import Session
from backend.db.models import User, Portfolio, TradeLog, TradeSide
from backend.db.database import redis_client
from backend.providers.market_data_provider import MarketDataProvider

logger = structlog.get_logger(__name__)
market_data = MarketDataProvider()

SLIPPAGE_RATE = 0.0005 # 0.05%
STT_RATE_SELL = 0.001 # 0.1% on sell side (approx NSE STT + charges)
MAX_CONCENTRATION_PCT = 0.30 # 30%

class TradeException(Exception):
    pass

class TradingEngine:
    def __init__(self, db: Session):
        self.db = db

    def _get_fill_price(self, ticker: str) -> float:
        """Fetch latest price from Redis, fallback to yfinance."""
        cached_price = redis_client.get(f"live_price:{ticker}")
        if cached_price:
            return float(cached_price)
        
        # Fallback
        price = market_data.get_latest_price(ticker)
        if price is None:
            raise TradeException(f"Could not fetch real-time price for {ticker}")
        return price

    def _get_portfolio_value(self, user_id: int) -> float:
        """Calculate total portfolio value based on current prices."""
        portfolios = self.db.query(Portfolio).filter(Portfolio.user_id == user_id).all()
        total_val = 0.0
        for p in portfolios:
            if p.quantity > 0:
                current_price = self._get_fill_price(p.ticker)
                total_val += (p.quantity * current_price)
        return total_val

    def execute_trade(self, user_id: int, ticker: str, side: TradeSide, quantity: float) -> TradeLog:
        """Executes a paper trade with validation and simulated fills."""
        user = self.db.query(User).filter(User.id == user_id).first()
        if not user:
            raise TradeException("User not found")

        if quantity <= 0:
            raise TradeException("Quantity must be positive")

        fill_price = self._get_fill_price(ticker)
        
        # Apply slippage
        if side == TradeSide.BUY:
            execution_price = fill_price * (1 + SLIPPAGE_RATE)
            trade_value = execution_price * quantity
            
            # Validation: Balance
            if user.virtual_balance < trade_value:
                raise TradeException("Insufficient virtual balance")
            
            # Validation: Concentration Risk
            current_portfolio_val = self._get_portfolio_value(user_id)
            total_account_value = current_portfolio_val + user.virtual_balance
            
            # Check existing holding value
            holding = self.db.query(Portfolio).filter_by(user_id=user_id, ticker=ticker).first()
            holding_val_before = (holding.quantity * fill_price) if holding else 0.0
            holding_val_after = holding_val_before + trade_value
            
            if total_account_value > 0 and (holding_val_after / total_account_value) > MAX_CONCENTRATION_PCT:
                raise TradeException(f"Trade exceeds single-stock concentration limit of {MAX_CONCENTRATION_PCT*100}%")
                
            # Execute BUY
            user.virtual_balance -= trade_value
            
            if not holding:
                holding = Portfolio(user_id=user_id, ticker=ticker, quantity=quantity, avg_cost=execution_price)
                self.db.add(holding)
            else:
                total_cost = (holding.quantity * holding.avg_cost) + trade_value
                holding.quantity += quantity
                holding.avg_cost = total_cost / holding.quantity
                
        elif side == TradeSide.SELL:
            holding = self.db.query(Portfolio).filter_by(user_id=user_id, ticker=ticker).first()
            if not holding or holding.quantity < quantity:
                raise TradeException("Insufficient holdings to sell")
                
            execution_price = fill_price * (1 - SLIPPAGE_RATE)
            gross_value = execution_price * quantity
            # Deduct STT on sell
            net_value = gross_value * (1 - STT_RATE_SELL)
            
            # Execute SELL
            user.virtual_balance += net_value
            holding.quantity -= quantity
            
            if holding.quantity == 0:
                self.db.delete(holding)
                
        # Record TradeLog
        log = TradeLog(
            user_id=user_id,
            ticker=ticker,
            side=side,
            quantity=quantity,
            fill_price=execution_price,
            slippage=SLIPPAGE_RATE,
            virtual_balance_after=user.virtual_balance
        )
        self.db.add(log)
        self.db.commit()
        self.db.refresh(log)
        
        logger.info("Trade executed successfully", trade_id=log.id, ticker=ticker, side=side.name, quantity=quantity)
        return log
