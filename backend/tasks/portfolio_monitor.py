"""Portfolio monitor: checks every holding every 15 minutes in market hours and logs alerts.

Checks: stop-loss / target (if set on the holding), news-sentiment drop, RSI(14) overbought/oversold
and volume spike (daily candles from Yahoo Finance). Every alert carries `citations`: the articles or
the data it was raised on. The same alert type for the same stock is not repeated within its cooldown.
"""
import json
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import structlog
from sqlalchemy import desc

from backend.celery_app import celery_app
from backend.db.database import SessionLocal, ensure_schema, redis_client
from backend.db.models import AlertLog, OHLCVData, Portfolio, SentimentScore
from backend.providers.market_data_provider import MarketDataProvider
from backend.services.sentiment_pipeline import SentimentPipeline, _aware, article_citation

logger = structlog.get_logger(__name__)
market_data = MarketDataProvider()

COOLDOWN_HOURS = {
    "STOP_LOSS_BREACH": 24, "TARGET_HIT": 24, "SENTIMENT_CRASH": 12,
    "RSI_OVERBOUGHT": 20, "RSI_OVERSOLD": 20, "VOLUME_SPIKE": 20,
}
SENTIMENT_MIN_ARTICLES = 3
SENTIMENT_FRESH_HOURS = 3
SENTIMENT_DROP = 0.35       # fall in the rolling score vs ~24h earlier
SENTIMENT_NEGATIVE = -0.35  # rolling score this low is an alert on its own


def _yahoo(ticker: str, history: bool = False) -> str:
    return f"https://finance.yahoo.com/quote/{ticker}/history" if history else f"https://finance.yahoo.com/quote/{ticker}"


def _window(hours: int) -> str:
    return f"{hours // 24} days" if hours and hours % 24 == 0 else f"{hours}h"


def _inr(v: float) -> str:
    return f"₹{v:,.2f}"


def price_alerts(h: Portfolio, price: float, price_time: datetime) -> List[dict]:
    alerts = []
    price_cite = {"kind": "data", "title": f"Last traded price {_inr(price)} at {price_time:%d %b %Y %H:%M} UTC",
                  "source": "Yahoo Finance", "url": _yahoo(h.ticker)}
    if h.sl_pct is not None:
        sl = h.avg_cost * (1 - h.sl_pct / 100)
        if price <= sl:
            alerts.append({
                "type": "STOP_LOSS_BREACH", "signal": "SELL",
                "message": f"{h.ticker} at {_inr(price)} is below your stop-loss of {_inr(sl)} "
                           f"({h.sl_pct:g}% under your average cost {_inr(h.avg_cost)}).",
                "citations": [price_cite, {"kind": "data", "title": f"Your holding: {h.quantity:g} shares, average cost "
                                           f"{_inr(h.avg_cost)}, stop-loss {h.sl_pct:g}%", "source": "Your paper portfolio"}],
            })
    if h.tg_pct is not None:
        tg = h.avg_cost * (1 + h.tg_pct / 100)
        if price >= tg:
            alerts.append({
                "type": "TARGET_HIT", "signal": "SELL",
                "message": f"{h.ticker} at {_inr(price)} reached your target of {_inr(tg)} "
                           f"({h.tg_pct:g}% over your average cost {_inr(h.avg_cost)}).",
                "citations": [price_cite, {"kind": "data", "title": f"Your holding: {h.quantity:g} shares, average cost "
                                           f"{_inr(h.avg_cost)}, target {h.tg_pct:g}%", "source": "Your paper portfolio"}],
            })
    return alerts


def sentiment_alerts(db, ticker: str, now: datetime) -> List[dict]:
    rows = (db.query(SentimentScore)
            .filter(SentimentScore.ticker == ticker, SentimentScore.window_hours.isnot(None))
            .order_by(desc(SentimentScore.timestamp)).limit(200).all())
    if not rows:
        return []
    latest = rows[0]
    if _aware(latest.timestamp) < now - timedelta(hours=SENTIMENT_FRESH_HOURS) or (latest.source_count or 0) < SENTIMENT_MIN_ARTICLES:
        return []
    earlier = next((r for r in rows if _aware(r.timestamp) <= _aware(latest.timestamp) - timedelta(hours=20)), None)
    dropped = earlier is not None and (earlier.score - latest.score) >= SENTIMENT_DROP and latest.score < 0
    very_negative = latest.score <= SENTIMENT_NEGATIVE
    if not (dropped or very_negative):
        return []

    arts = SentimentPipeline(db).window_articles(ticker, now)
    negative = sorted([a for a in arts if a.score < 0], key=lambda a: a.score)[:5]
    if not negative:
        return []
    worst = negative[0]
    if dropped:
        head = (f"News sentiment for {ticker} fell from {earlier.score:+.2f} to {latest.score:+.2f} "
                f"(average of {latest.source_count} articles from the last {_window(latest.window_hours)}).")
    else:
        head = (f"News sentiment for {ticker} is strongly negative at {latest.score:+.2f} "
                f"(average of {latest.source_count} articles from the last {_window(latest.window_hours)}).")
    msg = f"{head} {len(negative)} negative article{'s' if len(negative) != 1 else ''}, most negative: \"{worst.title}\""
    if worst.source:
        msg += f" ({worst.source})"
    return [{"type": "SENTIMENT_CRASH", "signal": "CAUTION", "message": msg + ".",
             "citations": [article_citation(a) for a in negative]}]


def _daily_history(db, ticker: str):
    """(dates, closes, volumes), oldest first. Yahoo Finance 3 months; the OHLCV table as fallback."""
    df = market_data.get_historical_data(ticker, period="3mo", interval="1d")
    if df is not None and not df.empty:
        df = df.dropna(subset=["Close"])
        return [d.date() for d in df.index], [float(x) for x in df["Close"]], [float(x) for x in df["Volume"]], "Yahoo Finance"
    rows = db.query(OHLCVData).filter(OHLCVData.ticker == ticker).order_by(desc(OHLCVData.timestamp)).limit(60).all()[::-1]
    return [r.timestamp.date() for r in rows], [r.close for r in rows], [r.volume for r in rows], "FinSight OHLCV table"


def rsi(closes: List[float], period: int = 14) -> Optional[float]:
    """Wilder's RSI on daily closes."""
    if len(closes) < period + 1:
        return None
    diffs = [b - a for a, b in zip(closes[:-1], closes[1:])]
    gain = sum(max(d, 0) for d in diffs[:period]) / period
    loss = sum(max(-d, 0) for d in diffs[:period]) / period
    for d in diffs[period:]:
        gain = (gain * (period - 1) + max(d, 0)) / period
        loss = (loss * (period - 1) + max(-d, 0)) / period
    if loss == 0:
        return 100.0
    return 100 - 100 / (1 + gain / loss)


def technical_alerts(ticker: str, dates, closes, volumes, source: str) -> List[dict]:
    alerts = []
    if len(closes) < 15:
        return alerts
    cite = {"kind": "data", "source": source, "url": _yahoo(ticker, history=True)}
    r = rsi(closes)
    if r is not None and (r > 75 or r < 30):
        over = r > 75
        alerts.append({
            "type": "RSI_OVERBOUGHT" if over else "RSI_OVERSOLD", "signal": "SELL" if over else "BUY",
            "message": f"{ticker} RSI(14) is {r:.1f} on daily closes ({'overbought, above 75 - consider booking profits' if over else 'oversold, below 30 - possible entry point'}). "
                       f"Latest daily close {_inr(closes[-1])} ({dates[-1]:%d %b}).",
            "citations": [{**cite, "title": f"Daily closes {dates[0]:%d %b} - {dates[-1]:%d %b %Y} ({len(closes)} sessions), RSI(14) {r:.1f}"}],
        })
    if len(volumes) >= 21:
        today, base = volumes[-1], volumes[-21:-1]
        avg = sum(base) / 20
        if avg > 0 and today > 3 * avg:
            alerts.append({
                "type": "VOLUME_SPIKE", "signal": "HOLD",
                "message": f"Unusual volume in {ticker}: {today:,.0f} shares on {dates[-1]:%d %b}, "
                           f"{today / avg:.1f}x the 20-day average of {avg:,.0f}.",
                "citations": [{**cite, "title": f"Daily volume {dates[-21]:%d %b} - {dates[-1]:%d %b %Y}: today {today:,.0f}, 20-day average {avg:,.0f}"}],
            })
    return alerts


def _recently_alerted(db, user_id: int, ticker: str, alert_type: str, now: datetime) -> bool:
    since = now - timedelta(hours=COOLDOWN_HOURS.get(alert_type, 12))
    last = (db.query(AlertLog).filter(AlertLog.user_id == user_id, AlertLog.ticker == ticker,
                                      AlertLog.alert_type == alert_type)
            .order_by(desc(AlertLog.created_at)).first())
    return last is not None and last.created_at is not None and _aware(last.created_at) >= since


def _live_price(ticker: str) -> Optional[float]:
    try:
        cached = redis_client.get(f"live_price:{ticker}")
        if cached:
            return float(cached)
    except Exception:
        pass
    return market_data.get_latest_price(ticker)


def check_holding(db, h: Portfolio, now: datetime, price: Optional[float], history) -> List[dict]:
    alerts = []
    if price is not None:
        alerts += price_alerts(h, price, now)
    alerts += sentiment_alerts(db, h.ticker, now)
    if history:
        alerts += technical_alerts(h.ticker, *history)
    return alerts


@celery_app.task
def run_portfolio_monitor():
    logger.info("Starting portfolio monitor...")
    ensure_schema()
    db = SessionLocal()
    generated, skipped = 0, 0
    raised = []
    try:
        now = datetime.now(timezone.utc)
        holdings = db.query(Portfolio).filter(Portfolio.quantity > 0).all()
        history_cache, price_cache = {}, {}
        for h in holdings:
            try:
                if h.ticker not in price_cache:
                    price_cache[h.ticker] = _live_price(h.ticker)
                    history_cache[h.ticker] = _daily_history(db, h.ticker)
                price = price_cache[h.ticker]
                for alert in check_holding(db, h, now, price, history_cache[h.ticker]):
                    if _recently_alerted(db, h.user_id, h.ticker, alert["type"], now):
                        skipped += 1
                        raised.append({"ticker": h.ticker, "type": alert["type"], "status": "suppressed (cooldown)"})
                        continue
                    raised.append({"ticker": h.ticker, "type": alert["type"], "status": "new"})
                    row = AlertLog(user_id=h.user_id, ticker=h.ticker, alert_type=alert["type"], message=alert["message"],
                                   signal=alert["signal"], price_at_alert=price, citations=alert.get("citations") or [])
                    db.add(row)
                    db.commit()
                    db.refresh(row)
                    generated += 1
                    try:
                        redis_client.publish("user_alerts", json.dumps({
                            "user_id": h.user_id, "id": row.id, "alert_type": row.alert_type, "ticker": row.ticker,
                            "message": row.message, "signal": row.signal, "citations": row.citations,
                        }))
                    except Exception as e:
                        logger.warning("Could not publish alert", error=str(e))
            except Exception as e:
                db.rollback()
                logger.error("Monitor check failed", ticker=h.ticker, error=str(e))
        logger.info("Portfolio monitor completed", alerts_generated=generated, suppressed_by_cooldown=skipped)
        return {"generated": generated, "suppressed": skipped, "alerts": raised}
    finally:
        db.close()
