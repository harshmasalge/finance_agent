import json
import structlog
from backend.celery_app import celery_app
from backend.providers.market_data_provider import MarketDataProvider
from backend.db.database import redis_client, SessionLocal
from backend.db.models import OHLCVData

logger = structlog.get_logger(__name__)
market_data = MarketDataProvider()

# Hardcoded tracked tickers for now. Will be dynamic based on portfolios later.
TRACKED_TICKERS = ["RELIANCE.NS", "TCS.NS", "INFY.NS", "^NSEI"]

@celery_app.task
def fetch_live_prices():
    """
    Fetches the latest prices for tracked tickers and caches them in Redis.
    """
    logger.info("Fetching live prices...")
    for ticker in TRACKED_TICKERS:
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
        for ticker in TRACKED_TICKERS:
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
