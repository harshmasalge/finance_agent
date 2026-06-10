import os
import structlog
import hashlib
from datetime import datetime, timedelta, timezone
from backend.celery_app import celery_app
from backend.db.database import SessionLocal
from backend.services.sentiment_pipeline import SentimentPipeline
from backend.tasks.data_ingestion import get_tracked_tickers
import requests
import feedparser

logger = structlog.get_logger(__name__)



def get_newsapi_articles(tickers):
    keys_env = os.getenv("NEWSAPI_KEYS") or os.getenv("NEWSAPI_KEY")
    if not keys_env:
        logger.warning("NEWSAPI_KEYS not set. Skipping NewsAPI.")
        return []
        
    keys = [k.strip() for k in keys_env.split(",") if k.strip()]
    if not keys:
        return []
        
    articles = []
    # Strip .NS for searching
    search_queries = [t.replace(".NS", "") for t in tickers if not t.startswith("^")]
    
    for idx, query in enumerate(search_queries):
        if not query: continue
        try:
            current_key = keys[idx % len(keys)] # Round-robin key selection
            url = f"https://newsapi.org/v2/everything?q={query}&language=en&sortBy=publishedAt&apiKey={current_key}"
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                for item in data.get("articles", [])[:10]: # Limit to top 10 per ticker to avoid overload
                    text = f"{item.get('title', '')}. {item.get('description', '')}"
                    articles.append({"text": text, "source": "NewsAPI"})
        except Exception as e:
            logger.error("Error fetching NewsAPI", query=query, error=str(e))
            
    return articles



def get_rss_feeds():
    articles = []
    feeds = [
        ("Moneycontrol", "https://www.moneycontrol.com/rss/latestnews.xml"),
        ("ET Markets", "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms")
    ]
    
    two_hours_ago = datetime.now(timezone.utc) - timedelta(hours=2)
    
    for source, url in feeds:
        try:
            parsed = feedparser.parse(url)
            for entry in parsed.entries:
                # Basic time check if published_parsed is available
                if hasattr(entry, 'published_parsed') and entry.published_parsed:
                    dt = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                    if dt < two_hours_ago:
                        continue
                text = f"{entry.get('title', '')}. {entry.get('summary', '')}"
                articles.append({"text": text, "source": source})
        except Exception as e:
            logger.error("Error fetching RSS", source=source, error=str(e))
            
    return articles

@celery_app.task
def run_sentiment_ingestion():
    logger.info("Starting sentiment ingestion...")
    db = SessionLocal()
    
    try:
        tracked_tickers = get_tracked_tickers(db)
        
        # 1. Fetch from sources
        newsapi_data = get_newsapi_articles(tracked_tickers)
        rss_data = get_rss_feeds()
        
        all_articles = newsapi_data + rss_data
        
        # 2. Deduplicate
        seen_hashes = set()
        unique_articles = []
        for article in all_articles:
            if not article["text"].strip(): continue
            h = hashlib.md5(article["text"].encode('utf-8')).hexdigest()
            if h not in seen_hashes:
                seen_hashes.add(h)
                unique_articles.append(article)
                
        # 3. Process
        pipeline = SentimentPipeline(db)
        counts = {}
        for article in unique_articles:
            src = article["source"]
            counts[src] = counts.get(src, 0) + 1
            pipeline.process_and_store(article["text"], src, tracked_tickers)
            
        logger.info("Sentiment ingestion completed", total_processed=len(unique_articles), counts_by_source=counts)
    except Exception as e:
        logger.error("Sentiment ingestion failed", error=str(e))
    finally:
        db.close()
