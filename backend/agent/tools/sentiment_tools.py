import re
from functools import lru_cache

import yfinance as yf

from backend.db.database import SessionLocal
from backend.db.models import SentimentScore
from backend.tasks.sentiment_ingestion import fetch_newsapi_headlines


@lru_cache(maxsize=256)
def _company_name(ticker: str) -> str:
    """Best-effort company name for news search (falls back to the bare symbol)."""
    try:
        info = yf.Ticker(ticker).info
        name = info.get("shortName") or info.get("longName") or ticker.split(".")[0]
    except Exception:
        name = ticker.split(".")[0]
    # "TECH MAHINDRA LIMITED" -> "Tech Mahindra" (exact-phrase news search needs the common name)
    words = [w for w in re.split(r"\s+", name.replace(".", " ")) if w.upper() not in {"LIMITED", "LTD", "INC", "CORPORATION", "CORP", "CO"}]
    cleaned = " ".join(words).strip()
    try:
        return cleaned.title() if cleaned.isupper() else cleaned
    except Exception:
        return ticker.split(".")[0]


def get_recent_headlines(ticker: str) -> dict:
    """
    Fetches up to 6 recent news headlines about an NSE/BSE stock (e.g. 'TCS.NS').
    Each headline includes its source, publish time and URL.
    If nothing is found, 'available' is False - do NOT invent news in that case.
    """
    name = _company_name(ticker)
    headlines = fetch_newsapi_headlines(name, limit=6)
    if not headlines:
        return {
            "ticker": ticker,
            "available": False,
            "message": f"No recent headlines found for {name}. Report this as a data gap; do not guess the news.",
        }
    return {"ticker": ticker, "company": name, "available": True, "headlines": headlines}


def get_sentiment_score(ticker: str) -> dict:
    """
    Returns the latest stored news-sentiment score (-1 bearish .. +1 bullish) for an NSE/BSE stock.
    If no score has been computed yet, 'available' is False - do NOT describe sentiment as stable or neutral then.
    """
    db = SessionLocal()
    try:
        rows = (
            db.query(SentimentScore)
            .filter(SentimentScore.ticker == ticker)
            .order_by(SentimentScore.timestamp.desc())
            .limit(10)
            .all()
        )
        if not rows:
            return {
                "ticker": ticker,
                "available": False,
                "message": "No sentiment score stored for this stock. Treat sentiment as UNKNOWN (data gap), not neutral.",
            }
        latest = rows[0]
        avg = sum(r.score for r in rows) / len(rows)
        return {
            "ticker": ticker,
            "available": True,
            "latest_score": round(float(latest.score), 3),
            "avg_score_last_n": round(float(avg), 3),
            "n_scores": len(rows),
            "confidence": float(latest.confidence),
            "as_of": latest.timestamp.isoformat() if latest.timestamp else None,
        }
    except Exception as e:
        return {"ticker": ticker, "available": False, "message": f"Sentiment lookup failed: {e}"}
    finally:
        db.close()
