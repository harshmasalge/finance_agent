from datetime import datetime, timedelta, timezone

from backend.db.database import SessionLocal
from backend.db.models import SentimentScore
from backend.services import company_names
from backend.services.sentiment_pipeline import SentimentPipeline, _aware, article_citation, model_name, score_articles
from backend.tasks.sentiment_ingestion import fetch_newsapi

FRESH_HOURS = 24  # a stored aggregate older than this is not used; the score is computed from live headlines instead


def _company_name(ticker: str) -> str:
    return company_names.company_name(ticker)


def _headlines(ticker: str, limit: int = 8) -> list:
    """Recent articles that actually name the company, newest first."""
    query = company_names.news_query(ticker)
    found = fetch_newsapi(query, limit=limit * 3)
    relevant, seen = [], set()
    for a in found:
        key = " ".join(a["title"].lower().split())
        if company_names.about(a["title"], ticker) and key not in seen:
            seen.add(key)
            relevant.append(a)
    return relevant[:limit]


def get_recent_headlines(ticker: str) -> dict:
    """
    Fetches up to 8 recent news headlines that name an NSE/BSE stock (e.g. 'TCS.NS'), newest first.
    Each headline includes its source, publish time, URL and a sentiment score (-1 bearish .. +1 bullish).
    If nothing is found, 'available' is False - do NOT invent news in that case.
    """
    name = _company_name(ticker)
    headlines = _headlines(ticker)
    if not headlines:
        return {
            "ticker": ticker,
            "company": name,
            "available": False,
            "message": f"No recent headlines found for {name}. Report this as a data gap; do not guess the news.",
        }
    scored = score_articles(headlines)
    return {"ticker": ticker, "company": name, "available": True, "query": company_names.news_query(ticker),
            "headlines": [{**{k: h.get(k) for k in ("title", "description", "source", "url", "published_at")},
                           "sentiment": h["sentiment"]} for h in scored]}


def _label(score: float) -> str:
    return "positive" if score >= 0.15 else "negative" if score <= -0.15 else "mixed/neutral"


def get_sentiment_score(ticker: str) -> dict:
    """
    Returns the news-sentiment score (-1 bearish .. +1 bullish) for an NSE/BSE stock: the average of the
    per-article scores of recent articles that name the company, plus the articles themselves (title, source,
    URL, score) so every sentiment claim can be cited. Uses the FinSight pipeline's stored score when it is
    fresh, otherwise scores live headlines on demand. If no articles exist, 'available' is False - do NOT
    describe sentiment as stable or neutral then.
    """
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        rows = (db.query(SentimentScore)
                .filter(SentimentScore.ticker == ticker, SentimentScore.window_hours.isnot(None))
                .order_by(SentimentScore.timestamp.desc()).limit(50).all())
        latest = rows[0] if rows else None
        if latest and _aware(latest.timestamp) >= now - timedelta(hours=FRESH_HOURS):
            arts = SentimentPipeline(db).window_articles(ticker, now)
            if arts:
                mean = sum(a.score for a in arts) / len(arts)  # recomputed so it matches the articles listed
                day_ago = next((r for r in rows if _aware(r.timestamp) <= _aware(latest.timestamp) - timedelta(hours=24)), None)
                return {
                    "ticker": ticker, "available": True, "method": "stored pipeline aggregate",
                    "score": round(mean, 3), "label": _label(mean),
                    "n_articles": len(arts), "window_hours": latest.window_hours,
                    "confidence": float(latest.confidence),
                    "score_24h_earlier": round(float(day_ago.score), 3) if day_ago else None,
                    "as_of": latest.timestamp.isoformat(),
                    "articles": [{k: v for k, v in article_citation(a).items() if k != "kind"} for a in arts],
                }

        heads = _headlines(ticker, limit=10)
        if not heads:
            return {"ticker": ticker, "available": False,
                    "message": f"No recent articles naming {_company_name(ticker)} were found, so sentiment is UNKNOWN "
                               "(data gap), not neutral."}
        scored = score_articles(heads)
        mean = sum(h["sentiment"] for h in scored) / len(scored)
        return {
            "ticker": ticker, "available": True, "method": f"computed now from {len(scored)} live headlines",
            "score": round(mean, 3), "label": _label(mean), "n_articles": len(scored),
            "confidence": round(min(1.0, len(scored) / 5) * (1.0 if model_name() == "finbert" else 0.5), 2),
            "as_of": now.isoformat(),
            "articles": [{"title": h["title"], "url": h["url"], "source": h.get("source"),
                          "published_at": h.get("published_at"), "score": h["sentiment"]} for h in scored],
        }
    except Exception as e:
        return {"ticker": ticker, "available": False, "message": f"Sentiment lookup failed: {e}"}
    finally:
        db.close()
