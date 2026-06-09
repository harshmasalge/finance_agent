import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

import structlog
from backend.db.database import SessionLocal
from backend.services.sentiment_pipeline import SentimentPipeline
from backend.db.models import SentimentScore

logger = structlog.get_logger(__name__)

def run_test_sentiment():
    db = SessionLocal()
    pipeline = SentimentPipeline(db)
    
    tracked_tickers = ["RELIANCE.NS", "TCS.NS"]
    
    # Positive sample
    sample_text_1 = "Reliance Industries reports record-breaking profits for Q3, margins expand significantly."
    logger.info("Processing positive sample...", text=sample_text_1)
    pipeline.process_and_store(sample_text_1, "NewsAPI", tracked_tickers)
    
    # Negative sample
    sample_text_2 = "TCS shares plunge 5% amidst management crisis and weak forward guidance."
    logger.info("Processing negative sample...", text=sample_text_2)
    pipeline.process_and_store(sample_text_2, "NewsAPI", tracked_tickers)
    
    # Verify in DB
    scores = db.query(SentimentScore).order_by(SentimentScore.id.desc()).limit(2).all()
    for s in scores:
        logger.info("DB Record", ticker=s.ticker, score=s.score, confidence=s.confidence)
        
    db.close()

if __name__ == "__main__":
    run_test_sentiment()
