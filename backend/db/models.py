from sqlalchemy import Column, String, Float, DateTime, Integer, Boolean, ForeignKey, Enum
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import enum
from .database import Base

class OHLCVData(Base):
    """
    SQLAlchemy model for historical price data.
    We will convert this table to a TimescaleDB hypertable in our init script.
    """
    __tablename__ = "ohlcv_data"

    ticker = Column(String(50), primary_key=True, index=True)
    timestamp = Column(DateTime(timezone=True), primary_key=True, index=True)
    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    volume = Column(Float, nullable=False)

class User(Base):
    """
    Placeholder User model. Full implementation in Checkpoint 11.
    """
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True)
    name = Column(String(255), nullable=True)
    picture = Column(String(500), nullable=True)
    virtual_balance = Column(Float, default=100000.0) # Start with ₹1L
    
    portfolios = relationship("Portfolio", back_populates="owner")
    trades = relationship("TradeLog", back_populates="owner")

class TradeSide(enum.Enum):
    BUY = "BUY"
    SELL = "SELL"

class TradeLog(Base):
    """
    Record of every executed paper trade.
    """
    __tablename__ = "trade_log"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    ticker = Column(String(50), index=True)
    side = Column(Enum(TradeSide))
    quantity = Column(Float, nullable=False)
    fill_price = Column(Float, nullable=False)
    slippage = Column(Float, nullable=False)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    virtual_balance_after = Column(Float, nullable=False)
    
    owner = relationship("User", back_populates="trades")

class Portfolio(Base):
    """
    Current holdings per user.
    """
    __tablename__ = "portfolios"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    ticker = Column(String(50), index=True)
    quantity = Column(Float, nullable=False, default=0.0)
    avg_cost = Column(Float, nullable=False, default=0.0)
    # Stop loss and target percentages specific to this holding
    sl_pct = Column(Float, nullable=True) 
    tg_pct = Column(Float, nullable=True)
    
    owner = relationship("User", back_populates="portfolios")

class SentimentScore(Base):
    """
    Aggregated sentiment score per ticker.
    """
    __tablename__ = "sentiment_scores"
    
    id = Column(Integer, primary_key=True, index=True)
    ticker = Column(String(50), index=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    score = Column(Float, nullable=False) # -1.0 to +1.0
    source_count = Column(Integer, default=1)
    confidence = Column(Float, default=1.0)

