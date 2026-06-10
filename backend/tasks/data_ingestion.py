import json
import structlog
from backend.celery_app import celery_app
from backend.providers.market_data_provider import MarketDataProvider
from backend.db.database import redis_client, SessionLocal
from backend.db.models import OHLCVData, Portfolio
import datetime
import pytz

logger = structlog.get_logger(__name__)
market_data = MarketDataProvider()

def get_tracked_tickers(db):
    tickers = set(["^NSEI", "^BSESN"])
    portfolios = db.query(Portfolio.ticker).filter(Portfolio.quantity > 0).distinct().all()
    for (t,) in portfolios:
        tickers.add(t)
    
    # Fallback if no holdings
    if len(tickers) == 2: # Only the baseline indices are there
        return ["RELIANCE.NS", "TCS.NS", "INFY.NS", "^NSEI", "^BSESN"]
    return list(tickers)

@celery_app.task
def fetch_live_prices():
    """
    Fetches the latest prices for tracked tickers and caches them in Redis.
    """
    tz = pytz.timezone('Asia/Kolkata')
    now = datetime.datetime.now(tz)
    
    # Check weekday (0=Monday, ..., 4=Friday)
    is_weekday = now.weekday() <= 4
    
    # Check time (9:15 AM to 3:30 PM IST)
    market_start = now.replace(hour=9, minute=15, second=0, microsecond=0)
    market_end = now.replace(hour=15, minute=30, second=0, microsecond=0)
    is_market_hours = market_start <= now <= market_end
    
    if not (is_weekday and is_market_hours):
        logger.info("Market is closed. Skipping live price fetch.")
        return

    logger.info("Fetching live prices...")
    db = SessionLocal()
    try:
        tracked_tickers = get_tracked_tickers(db)
    finally:
        db.close()
        
    for ticker in tracked_tickers:
        price = market_data.get_latest_price(ticker)
        if price is not None:
            # Cache the latest price with a 60s TTL
            redis_client.setex(f"live_price:{ticker}", 60, price)
            # Publish to pub/sub for websockets
            payload = json.dumps({"ticker": ticker, "price": price})
            redis_client.publish("live_prices", payload)
            logger.info("Live price updated and published", ticker=ticker, price=price)
        else:
            logger.warning("Failed to get live price", ticker=ticker)

@celery_app.task
def fetch_and_store_historical_data():
    """
    Fetches end-of-day OHLCV data and stores it in TimescaleDB.
    """
    logger.info("Fetching EOD historical data...")
    db = SessionLocal()
    try:
        tracked_tickers = get_tracked_tickers(db)
        for ticker in tracked_tickers:
            df = market_data.get_historical_data(ticker, period="1d", interval="1d")
            if df is not None and not df.empty:
                for index, row in df.iterrows():
                    # Check if it already exists to prevent duplicate key errors (or handle via upsert)
                    exists = db.query(OHLCVData).filter_by(ticker=ticker, timestamp=index).first()
                    if not exists:
                        data_point = OHLCVData(
                            ticker=ticker,
                            timestamp=index,
                            open=float(row['Open']),
                            high=float(row['High']),
                            low=float(row['Low']),
                            close=float(row['Close']),
                            volume=float(row['Volume'])
                        )
                        db.add(data_point)
        db.commit()
        logger.info("Historical data stored successfully")
    except Exception as e:
        db.rollback()
        logger.error("Error storing historical data", error=str(e))
    finally:
        db.close()
