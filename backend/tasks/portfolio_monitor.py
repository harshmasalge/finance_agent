import json
import structlog
from backend.celery_app import celery_app
from backend.db.database import SessionLocal, redis_client
from backend.db.models import Portfolio, AlertLog, SentimentScore, OHLCVData
from sqlalchemy import desc

logger = structlog.get_logger(__name__)

@celery_app.task
def run_portfolio_monitor():
    logger.info("Starting portfolio monitor...")
    db = SessionLocal()
    alerts_generated = 0
    
    try:
        # 1. Fetch all Portfolios with quantity > 0
        holdings = db.query(Portfolio).filter(Portfolio.quantity > 0).all()
        
        # Group by user_id
        user_holdings = {}
        for h in holdings:
            user_holdings.setdefault(h.user_id, []).append(h)
            
        for user_id, user_portfolios in user_holdings.items():
            for h in user_portfolios:
                # Fetch current price from redis
                cached_price = redis_client.get(f"live_price:{h.ticker}")
                if not cached_price:
                    continue
                current_price = float(cached_price)
                
                alerts = []
                
                # Check A - Stop-loss breach
                if h.sl_pct is not None:
                    sl_price = h.avg_cost * (1 - h.sl_pct / 100)
                    if current_price <= sl_price:
                        alerts.append({
                            "type": "STOP_LOSS_BREACH",
                            "message": f"{h.ticker} down from your buy price. Stop-loss at {sl_price:.2f} breached.",
                            "signal": "SELL"
                        })
                        
                # Check B - Target hit
                if h.tg_pct is not None:
                    tg_price = h.avg_cost * (1 + h.tg_pct / 100)
                    if current_price >= tg_price:
                        alerts.append({
                            "type": "TARGET_HIT",
                            "message": f"{h.ticker} up from your buy price. Target at {tg_price:.2f} hit.",
                            "signal": "SELL"
                        })
                        
                # Check C - Sentiment crash
                sentiments = db.query(SentimentScore).filter(SentimentScore.ticker == h.ticker).order_by(desc(SentimentScore.timestamp)).limit(2).all()
                if len(sentiments) == 2:
                    if sentiments[0].score - sentiments[1].score < -0.4:
                        alerts.append({
                            "type": "SENTIMENT_CRASH",
                            "message": f"Sudden drop in sentiment for {h.ticker}. Recent news is highly negative.",
                            "signal": "CAUTION"
                        })
                        
                # Check D - RSI & Check E - Volume spike
                # Using timescale data (OHLCVData)
                recent_ohlcv = db.query(OHLCVData).filter(OHLCVData.ticker == h.ticker).order_by(desc(OHLCVData.timestamp)).limit(21).all()
                if len(recent_ohlcv) >= 15:
                    # Simple RSI approximation for the sake of completion:
                    # Calculate price differences
                    diffs = [recent_ohlcv[i].close - recent_ohlcv[i+1].close for i in range(14)]
                    gains = [d for d in diffs if d > 0]
                    losses = [abs(d) for d in diffs if d < 0]
                    avg_gain = sum(gains) / 14 if gains else 0
                    avg_loss = sum(losses) / 14 if losses else 0
                    
                    if avg_loss > 0:
                        rs = avg_gain / avg_loss
                        rsi = 100 - (100 / (1 + rs))
                        if rsi > 75:
                            alerts.append({
                                "type": "RSI_OVERBOUGHT",
                                "message": f"{h.ticker} RSI is {rsi:.1f} (Overbought). Consider booking profits.",
                                "signal": "SELL"
                            })
                        elif rsi < 30:
                            alerts.append({
                                "type": "RSI_OVERSOLD",
                                "message": f"{h.ticker} RSI is {rsi:.1f} (Oversold). Might be a good entry point.",
                                "signal": "BUY"
                            })
                
                if len(recent_ohlcv) == 21:
                    today_vol = recent_ohlcv[0].volume
                    avg_vol = sum([x.volume for x in recent_ohlcv[1:]]) / 20
                    if today_vol > 3 * avg_vol:
                        alerts.append({
                            "type": "VOLUME_SPIKE",
                            "message": f"Unusual volume detected in {h.ticker}. Today's volume is >3x the 20-day average.",
                            "signal": "HOLD"
                        })
                        
                # 3. Create AlertLog
                for alert in alerts:
                    # Check if similar alert recently generated to avoid spam
                    # (Skipped for simplicity in this implementation)
                    
                    new_alert = AlertLog(
                        user_id=user_id,
                        ticker=h.ticker,
                        alert_type=alert["type"],
                        message=alert["message"],
                        signal=alert["signal"],
                        price_at_alert=current_price
                    )
                    db.add(new_alert)
                    db.commit()
                    db.refresh(new_alert)
                    alerts_generated += 1
                    
                    # 4. Publish to Redis
                    redis_client.publish("user_alerts", json.dumps({
                        "user_id": user_id,
                        "alert_type": new_alert.alert_type,
                        "ticker": new_alert.ticker,
                        "message": new_alert.message,
                        "signal": new_alert.signal
                    }))
                    
        logger.info("Portfolio monitor completed", alerts_generated=alerts_generated)
    except Exception as e:
        logger.error("Portfolio monitor failed", error=str(e))
    finally:
        db.close()
