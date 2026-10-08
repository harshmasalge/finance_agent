"""News sentiment: score articles (FinBERT, VADER fallback), store them per ticker with their URL,
and keep a rolling per-ticker aggregate in SentimentScore.

Ticker matching uses company names and aliases (backend/services/company_names.py): news says
"State Bank of India", never "SBIN".
"""
import re
import threading
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional

import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.db.models import NewsArticle, SentimentScore
from backend.services import company_names

logger = structlog.get_logger(__name__)

WINDOW_HOURS = 168         # articles published in the last 7 days make up the aggregate (NewsAPI's free tier lags ~1 day)
MAX_ARTICLES = 25          # newest N articles in the window are averaged

_model_lock = threading.Lock()
_model: Dict[str, object] = {}


def _load_models():
    """Load FinBERT once per process (it is ~400 MB). Falls back to VADER if it can't be loaded."""
    with _model_lock:
        if _model:
            return _model
        from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
        _model["vader"] = SentimentIntensityAnalyzer()
        try:
            from transformers import AutoModelForSequenceClassification, AutoTokenizer
            logger.info("Loading FinBERT model...")
            tok = AutoTokenizer.from_pretrained("ProsusAI/finbert")
            mdl = AutoModelForSequenceClassification.from_pretrained("ProsusAI/finbert")
            mdl.eval()
            # Read the label order from the model config instead of assuming it.
            labels = {i: str(l).lower() for i, l in mdl.config.id2label.items()}
            _model.update(tokenizer=tok, finbert=mdl, labels=labels)
            logger.info("FinBERT loaded.", labels=labels)
        except Exception as e:
            logger.warning("Could not load FinBERT, using VADER.", error=str(e))
        return _model


def clean_text(text: str) -> str:
    text = re.sub(r"http\S+", "", text or "")
    text = re.sub(r"<[^>]+>", " ", text)  # RSS summaries carry HTML
    text = re.sub(r"[^\w\s.,!?%&'-]", " ", text)
    return " ".join(text.split())


def model_name() -> str:
    return "finbert" if _load_models().get("finbert") is not None else "vader"


def score_text(text: str) -> float:
    """-1.0 (bearish) .. +1.0 (bullish)."""
    m = _load_models()
    text = clean_text(text)
    if not text:
        return 0.0
    if m.get("finbert") is not None:
        try:
            import torch
            inputs = m["tokenizer"](text, return_tensors="pt", truncation=True, max_length=256)
            with torch.no_grad():
                probs = torch.nn.functional.softmax(m["finbert"](**inputs).logits, dim=-1)[0]
            by_label = {m["labels"][i]: probs[i].item() for i in range(len(probs))}
            return round(by_label.get("positive", 0.0) - by_label.get("negative", 0.0), 4)
        except Exception as e:
            logger.error("FinBERT scoring failed, using VADER", error=str(e))
    return round(m["vader"].polarity_scores(text)["compound"], 4)


def article_text(a: dict) -> str:
    title = (a.get("title") or "").strip()
    desc = (a.get("description") or "").strip()
    return f"{title}. {desc}" if desc else title


def _parse_dt(v) -> Optional[datetime]:
    if not v:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    """SQLite returns naive datetimes; treat them as UTC."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def score_articles(articles: Iterable[dict]) -> List[dict]:
    """Add a 'sentiment' score to each article dict (title/description/url/source/published_at)."""
    out = []
    for a in articles:
        a = dict(a)
        a["sentiment"] = score_text(article_text(a))
        out.append(a)
    return out


class SentimentPipeline:
    def __init__(self, db: Session):
        self.db = db

    def store_articles(self, ticker: str, articles: Iterable[dict], require_mention: bool = True) -> int:
        """Score and store new articles for one ticker (deduplicated on URL). Returns how many were added."""
        existing = {u for (u,) in self.db.query(NewsArticle.url).filter(NewsArticle.ticker == ticker).all()}
        added = 0
        model = model_name()
        for a in articles:
            url = (a.get("url") or "").strip()
            title = (a.get("title") or "").strip()
            if not url or not title or url in existing:
                continue
            text = article_text(a)
            if require_mention and not company_names.about(title, ticker):
                continue  # passing mentions / round-ups / other companies with the same prefix
            row = NewsArticle(
                ticker=ticker, url=url[:1000], title=title, description=(a.get("description") or "")[:1000] or None,
                source=a.get("source"), feed=a.get("feed"), published_at=_parse_dt(a.get("published_at")),
                score=score_text(text), model=model,
            )
            existing.add(url)
            try:
                with self.db.begin_nested():  # another run may have stored the same URL meanwhile
                    self.db.add(row)
                added += 1
            except IntegrityError:
                pass
        self.db.commit()
        return added

    def window_articles(self, ticker: str, now: Optional[datetime] = None) -> List[NewsArticle]:
        now = now or datetime.now(timezone.utc)
        since = now - timedelta(hours=WINDOW_HOURS)
        rows = (self.db.query(NewsArticle).filter(NewsArticle.ticker == ticker)
                .order_by(NewsArticle.published_at.desc().nulls_last(), NewsArticle.fetched_at.desc())
                .limit(MAX_ARTICLES * 3).all())
        recent, seen_titles = [], set()
        for r in rows:
            if (_aware(r.published_at) or _aware(r.fetched_at) or now) < since:
                continue
            # re-check with the current rules, so articles stored under older rules drop out
            if not company_names.about(r.title, ticker):
                continue
            key = re.sub(r"\W+", " ", r.title.lower()).strip()
            if key in seen_titles:  # the same story syndicated under several URLs counts once
                continue
            seen_titles.add(key)
            recent.append(r)
        return recent[:MAX_ARTICLES]

    def aggregate(self, ticker: str, now: Optional[datetime] = None) -> Optional[SentimentScore]:
        """Store one aggregate SentimentScore for the ticker from its recent articles (None if there are none)."""
        arts = self.window_articles(ticker, now)
        if not arts:
            return None
        n = len(arts)
        mean = sum(a.score for a in arts) / n
        finbert = sum(1 for a in arts if a.model == "finbert") / n
        # More articles and FinBERT (vs VADER) -> more confidence. 5+ articles counts as a full sample.
        confidence = round(min(1.0, n / 5) * (0.5 + 0.5 * finbert), 2)
        row = SentimentScore(ticker=ticker, score=round(mean, 4), source_count=n, confidence=confidence,
                             window_hours=WINDOW_HOURS)
        if now is not None:
            row.timestamp = now
        self.db.add(row)
        self.db.commit()
        return row

    # Kept for scripts/test_sentiment.py: score free text and store it against every ticker it names.
    def process_and_store(self, text: str, source: str, tracked_tickers: List[str], url: Optional[str] = None):
        for t in tracked_tickers:
            if company_names.mentions(text, t):
                self.store_articles(t, [{"title": text, "url": url or f"text:{hash(text)}", "source": source}],
                                    require_mention=False)
                self.aggregate(t)


def article_citation(a: NewsArticle) -> dict:
    return {
        "kind": "article", "title": a.title, "url": a.url, "source": a.source or a.feed,
        "published_at": a.published_at.isoformat() if a.published_at else None, "score": round(a.score, 3),
    }
