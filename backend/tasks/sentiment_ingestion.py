import itertools
import os
from datetime import datetime, timedelta, timezone

import feedparser
import requests
import structlog

from backend.celery_app import celery_app
from backend.db.database import SessionLocal, ensure_schema
from backend.services import company_names
from backend.services.sentiment_pipeline import SentimentPipeline
from backend.tasks.data_ingestion import get_tracked_tickers

logger = structlog.get_logger(__name__)

_key_cursor = itertools.count()


def _newsapi_keys():
    keys_env = os.getenv("NEWSAPI_KEYS") or os.getenv("NEWSAPI_KEY") or ""
    return [k.strip() for k in keys_env.split(",") if k.strip()]


def fetch_newsapi(query: str, limit: int = 6, search_in: str = "title", days: int = 7):
    """Structured articles (title, description, source, url, published_at) for a NewsAPI query, newest first.

    `query` is passed as-is (use company_names.news_query for '"Tata Steel" OR ...'). Keys are used round
    robin; a key that is rate limited or rejected falls through to the next one.
    """
    keys = _newsapi_keys()
    if not keys:
        logger.warning("NEWSAPI_KEYS not set. Skipping NewsAPI.")
        return []
    start = next(_key_cursor)
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
    for i in range(len(keys)):
        key = keys[(start + i) % len(keys)]
        try:
            resp = requests.get(
                "https://newsapi.org/v2/everything",
                params={"q": query, "searchIn": search_in, "language": "en", "sortBy": "publishedAt",
                        "from": since, "pageSize": limit, "apiKey": key},
                timeout=10,
            )
        except Exception as e:
            logger.error("Error fetching NewsAPI", query=query, error=str(e))
            continue
        if resp.status_code in (401, 402, 403, 429):
            continue
        if resp.status_code != 200:
            logger.warning("NewsAPI error", query=query, status=resp.status_code, body=resp.text[:200])
            return []
        out = []
        for a in resp.json().get("articles", [])[:limit]:
            if not a.get("title") or a.get("title") == "[Removed]" or not a.get("url"):
                continue
            out.append({
                "title": a.get("title"),
                "description": (a.get("description") or "")[:500],
                "source": (a.get("source") or {}).get("name"),
                "url": a.get("url"),
                "published_at": a.get("publishedAt"),
                "feed": "NewsAPI",
            })
        return out
    logger.warning("All NewsAPI keys rate limited or rejected", query=query)
    return []


def fetch_newsapi_headlines(query: str, limit: int = 6):
    """Backwards-compatible wrapper: exact-phrase search for one company name."""
    return fetch_newsapi(f'"{query}"', limit=limit)


RSS_FEEDS = [
    ("Moneycontrol", "https://www.moneycontrol.com/rss/latestnews.xml"),
    ("ET Markets", "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"),
]


def get_rss_articles(hours: int = 24):
    articles = []
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    for source, url in RSS_FEEDS:
        try:
            # feedparser has no timeout of its own; a slow feed would stall the whole run.
            resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0 (FinSight news reader)"})
            parsed = feedparser.parse(resp.content)
            for entry in parsed.entries:
                published = None
                if getattr(entry, "published_parsed", None):
                    published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                    if published < since:
                        continue
                if not entry.get("link") or not entry.get("title"):
                    continue
                articles.append({
                    "title": entry.get("title"), "description": (entry.get("summary") or "")[:300],
                    "url": entry.get("link"), "source": source, "feed": source,
                    "published_at": published.isoformat() if published else None,
                })
            logger.info("RSS fetched", source=source, entries=len(parsed.entries), status=resp.status_code)
        except Exception as e:
            logger.error("Error fetching RSS", source=source, error=str(e))
    return articles


@celery_app.task
def run_sentiment_ingestion():
    logger.info("Starting sentiment ingestion...")
    ensure_schema()
    db = SessionLocal()
    try:
        tickers = [t for t in get_tracked_tickers(db) if not t.startswith("^")]
        rss = get_rss_articles()
        pipeline = SentimentPipeline(db)
        summary = {}
        for ticker in tickers:
            fetched = fetch_newsapi(company_names.news_query(ticker), limit=20)
            fetched += [a for a in rss if company_names.about(a["title"], ticker)]
            added = pipeline.store_articles(ticker, fetched)
            agg = pipeline.aggregate(ticker)
            summary[ticker] = {"fetched": len(fetched), "new": added,
                               "score": agg.score if agg else None, "n": agg.source_count if agg else 0}
        logger.info("Sentiment ingestion completed", rss_articles=len(rss), per_ticker=summary)
        return summary
    except Exception as e:
        logger.error("Sentiment ingestion failed", error=str(e))
        db.rollback()
    finally:
        db.close()
