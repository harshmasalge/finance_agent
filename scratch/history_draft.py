from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from backend.db.database import get_db, redis_client
from backend.db.models import Portfolio, TradeLog, TradeSide
from backend.services.auth import AuthService
from backend.services.trading_engine import TradingEngine, TradeException
from pydantic import BaseModel
from typing import Optional, List
import json
import structlog
import yfinance as yf
from datetime import datetime, timedelta
import pytz

logger = structlog.get_logger(__name__)

portfolio_router = APIRouter(prefix="/portfolio", tags=["Portfolio"])

# ... existing schemas ...

@portfolio_router.get("/history")
def get_portfolio_history(user_id: int = Depends(AuthService.get_current_user_id), db: Session = Depends(get_db)):
    trades = db.query(TradeLog).filter(TradeLog.user_id == user_id).order_by(TradeLog.timestamp.asc()).all()
    if not trades:
        return []
    
    tz = pytz.timezone('Asia/Kolkata')
    # Make sure timestamps are in IST
    for t in trades:
        if t.timestamp.tzinfo is None:
            t.timestamp = pytz.utc.localize(t.timestamp).astimezone(tz)
        else:
            t.timestamp = t.timestamp.astimezone(tz)
            
    start_time = trades[0].timestamp
    end_time = datetime.now(tz)
    
    # To keep it performant, if start_time is > 7 days ago, use 1h interval, else 15m interval
    days_diff = (end_time - start_time).days
    interval = "1h" if days_diff > 7 else "15m"
    period = "1mo" if days_diff > 7 else "1mo" # 1mo covers both securely

    tickers = set([t.ticker for t in trades])
    prices_cache = {}
    
    for ticker in tickers:
        stock = yf.Ticker(ticker)
        df = stock.history(period=period, interval=interval)
        if not df.empty:
            # Convert index to timezone-aware IST
            if df.index.tz is None:
                df.index = df.index.tz_localize('UTC').tz_convert(tz)
            else:
                df.index = df.index.tz_convert(tz)
            # Store map of exact timestamp -> close price
            prices_cache[ticker] = {idx: row['Close'] for idx, row in df.iterrows()}
        else:
            prices_cache[ticker] = {}

    # Iterate through each fetched timestamp from the main index (to align times)
    # Get all unique timestamps across all fetched data
    all_timestamps = set()
    for t_cache in prices_cache.values():
        for ts in t_cache.keys():
            if ts >= start_time:
                all_timestamps.add(ts)
                
    # If no market data timestamps found (e.g. market closed since trade), generate one for right now
    if not all_timestamps:
        all_timestamps.add(end_time)
        
    sorted_times = sorted(list(all_timestamps))
    
    history = []
    current_cash = 100000.0
    current_holdings = {}
    trade_idx = 0
    num_trades = len(trades)
    
    for current_time in sorted_times:
        # Apply trades up to current_time
        while trade_idx < num_trades and trades[trade_idx].timestamp <= current_time:
            t = trades[trade_idx]
            current_cash = t.virtual_balance_after
            
            if t.ticker not in current_holdings:
                current_holdings[t.ticker] = {"qty": 0.0, "avg_cost": 0.0}
            
            if t.side == TradeSide.BUY:
                prev_qty = current_holdings[t.ticker]["qty"]
                prev_cost = current_holdings[t.ticker]["avg_cost"]
                new_qty = prev_qty + t.quantity
                new_cost = ((prev_qty * prev_cost) + (t.quantity * t.fill_price)) / new_qty
                current_holdings[t.ticker] = {"qty": new_qty, "avg_cost": new_cost}
            elif t.side == TradeSide.SELL:
                new_qty = current_holdings[t.ticker]["qty"] - t.quantity
                if new_qty <= 0:
                    del current_holdings[t.ticker]
                else:
                    current_holdings[t.ticker]["qty"] = new_qty
            trade_idx += 1
            
        # "since the last time my holdings were 0"
        if len(current_holdings) == 0:
            history = []
            continue # Skip adding history points if holding is 0
            
        eod_asset_value = 0.0
        time_str = current_time.strftime("%b %d %H:%M")
        day_record = {"time": time_str}
        
        for ticker, h_data in current_holdings.items():
            price = prices_cache[ticker].get(current_time)
            
            # Forward-fill if no price at this exact minute
            if price is None:
                # Find most recent price before current_time
                past_times = [ts for ts in prices_cache[ticker].keys() if ts <= current_time]
                if past_times:
                    price = prices_cache[ticker][max(past_times)]
                else:
                    price = h_data["avg_cost"]
                    
            eod_asset_value += (price * h_data["qty"])
            roi = ((price - h_data["avg_cost"]) / h_data["avg_cost"]) * 100 if h_data["avg_cost"] > 0 else 0
            day_record[ticker] = round(roi, 2)
            
        total_value = current_cash + eod_asset_value
        day_record["TotalValue"] = round(total_value, 2)
        history.append(day_record)
        
    return history
