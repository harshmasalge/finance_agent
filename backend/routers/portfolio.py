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

class TradeRequest(BaseModel):
    ticker: str
    side: str # "BUY" | "SELL"
    quantity: float

class LimitUpdateRequest(BaseModel):
    sl_pct: Optional[float] = None
    tg_pct: Optional[float] = None

@portfolio_router.get("/holdings")
def get_holdings(user_id: int = Depends(AuthService.get_current_user_id), db: Session = Depends(get_db)):
    holdings = db.query(Portfolio).filter(Portfolio.user_id == user_id, Portfolio.quantity > 0).all()
    
    result = []
    for h in holdings:
        # fetch current price from Redis
        cached_price = redis_client.get(f"live_price:{h.ticker}")
        if cached_price:
            current_price = float(cached_price)
        else:
            # yfinance fallback or assume avg_cost for now
            current_price = h.avg_cost
            
        current_value = current_price * h.quantity
        invested_value = h.avg_cost * h.quantity
        unrealised_pnl = current_value - invested_value
        unrealised_pnl_pct = (unrealised_pnl / invested_value) * 100 if invested_value > 0 else 0
        
        result.append({
            "ticker": h.ticker,
            "quantity": h.quantity,
            "avg_cost": h.avg_cost,
            "sl_pct": h.sl_pct,
            "tg_pct": h.tg_pct,
            "current_price": current_price,
            "current_value": current_value,
            "unrealised_pnl": unrealised_pnl,
            "unrealised_pnl_pct": unrealised_pnl_pct
        })
    return result

@portfolio_router.post("/trade")
def execute_trade(request: TradeRequest, user_id: int = Depends(AuthService.get_current_user_id), db: Session = Depends(get_db)):
    try:
        side_enum = TradeSide[request.side]
    except KeyError:
        raise HTTPException(status_code=400, detail="Invalid trade side. Must be BUY or SELL")
        
    engine = TradingEngine(db)
    try:
        trade_log = engine.execute_trade(user_id, request.ticker, side_enum, request.quantity)
        
        # Publish to Redis channel user_alerts with updated balance so WebSocket reflects it
        redis_client.publish("user_alerts", json.dumps({
            "type": "balance_update",
            "user_id": user_id,
            "balance": trade_log.virtual_balance_after
        }))
        
        return trade_log
    except TradeException as e:
        raise HTTPException(status_code=400, detail=str(e))

@portfolio_router.patch("/holdings/{ticker}/limits")
def update_limits(ticker: str, request: LimitUpdateRequest, user_id: int = Depends(AuthService.get_current_user_id), db: Session = Depends(get_db)):
    holding = db.query(Portfolio).filter(Portfolio.user_id == user_id, Portfolio.ticker == ticker).first()
    if not holding:
        raise HTTPException(status_code=404, detail="Holding not found")
        
    if request.sl_pct is not None:
        holding.sl_pct = request.sl_pct
    if request.tg_pct is not None:
        holding.tg_pct = request.tg_pct
        
    db.commit()
    db.refresh(holding)
    return holding

@portfolio_router.delete("/holdings/{ticker}")
def delete_holding(ticker: str, user_id: int = Depends(AuthService.get_current_user_id), db: Session = Depends(get_db)):
    holding = db.query(Portfolio).filter(Portfolio.user_id == user_id, Portfolio.ticker == ticker).first()
    if not holding:
        raise HTTPException(status_code=404, detail="Holding not found")
    if holding.quantity > 0:
        raise HTTPException(status_code=400, detail="Cannot delete holding with active quantity. Close position first.")
        
    db.delete(holding)
    db.commit()
    return {"message": "Holding removed"}

@portfolio_router.get("/trades")
def get_trades(user_id: int = Depends(AuthService.get_current_user_id), db: Session = Depends(get_db)):
    trades = db.query(TradeLog).filter(TradeLog.user_id == user_id).order_by(TradeLog.timestamp.desc()).limit(50).all()
    return trades

@portfolio_router.get("/history")
def get_portfolio_history(user_id: int = Depends(AuthService.get_current_user_id), db: Session = Depends(get_db)):
    trades = db.query(TradeLog).filter(TradeLog.user_id == user_id).order_by(TradeLog.timestamp.asc()).all()
    if not trades:
        return []
    
    tz = pytz.timezone('Asia/Kolkata')
    for t in trades:
        if t.timestamp.tzinfo is None:
            t.timestamp = pytz.utc.localize(t.timestamp).astimezone(tz)
        else:
            t.timestamp = t.timestamp.astimezone(tz)
            
    start_time = trades[0].timestamp
    end_time = datetime.now(tz)
    
    days_diff = (end_time - start_time).days
    interval = "1h" if days_diff > 7 else "15m"
    period = "1mo"

    tickers = set([t.ticker for t in trades])
    prices_cache = {}
    
    for ticker in tickers:
        stock = yf.Ticker(ticker)
        df = stock.history(period=period, interval=interval)
        if not df.empty:
            if df.index.tz is None:
                df.index = df.index.tz_localize('UTC').tz_convert(tz)
            else:
                df.index = df.index.tz_convert(tz)
            prices_cache[ticker] = {idx: row['Close'] for idx, row in df.iterrows()}
        else:
            prices_cache[ticker] = {}

    all_timestamps = set()
    for t_cache in prices_cache.values():
        for ts in t_cache.keys():
            if ts >= start_time:
                all_timestamps.add(ts)
                
    if not all_timestamps:
        all_timestamps.add(end_time)
        
    sorted_times = sorted(list(all_timestamps))
    
    history = []
    current_cash = 100000.0
    current_holdings = {}
    trade_idx = 0
    num_trades = len(trades)
    
    for current_time in sorted_times:
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
            
        if len(current_holdings) == 0:
            history = []
            continue 
            
        eod_asset_value = 0.0
        time_str = current_time.strftime("%b %d %H:%M")
        day_record = {"time": time_str}
        
        for ticker, h_data in current_holdings.items():
            price = prices_cache[ticker].get(current_time)
            if price is None:
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
