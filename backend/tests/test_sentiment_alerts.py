"""News sentiment pipeline and portfolio-monitor alerts (SQLite, no network, VADER scoring)."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.db.database import Base, ensure_schema
from backend.db.models import AlertLog, Portfolio, SentimentScore
from backend.services import company_names, sentiment_pipeline as sp
from backend.tasks import portfolio_monitor as pm

NOW = datetime(2026, 10, 8, 6, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def vader_only(monkeypatch):
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
    monkeypatch.setattr(sp, "_model", {"vader": SentimentIntensityAnalyzer()})


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    ensure_schema(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def test_aliases_match_company_names_not_symbols():
    assert company_names.mentions("State Bank of India posts record profit", "SBIN.NS")
    assert company_names.mentions("SBI cuts lending rates", "SBIN.NS")
    assert company_names.mentions("Tata Steel shares slide", "TATASTEEL.NS")
    assert company_names.mentions("ICICI Bank Q2 preview", "ICICIBANK.NS")
    assert not company_names.mentions("Users switch to new phones", "ITC.NS")
    assert not company_names.mentions("an eternal question", "ETERNAL.NS")
    assert company_names.news_query("TCS.NS") == '"Tata Consultancy Services" OR "TCS"'


def _art(i, title, hours_ago=1, desc=""):
    return {"title": title, "description": desc, "url": f"https://news.example/{i}", "source": "Example",
            "published_at": (NOW - timedelta(hours=hours_ago)).isoformat()}


def test_store_dedupes_filters_and_aggregates(db):
    p = sp.SentimentPipeline(db)
    arts = [_art(1, "TCS wins a large deal, shares rally strongly"),
            _art(2, "TCS shares plunge after weak guidance and layoffs"),
            _art(2, "duplicate url"),
            _art(3, "Infosys signs a deal")]  # not about TCS
    assert p.store_articles("TCS.NS", arts) == 2  # duplicate URL and non-TCS headline skipped
    assert p.store_articles("TCS.NS", arts) == 0
    assert p.store_articles("TCS.NS", [_art(4, "Day Trading Guide for October 7", desc="Stocks: TCS, SBI, ITC")]) == 0
    agg = p.aggregate("TCS.NS", now=NOW)
    assert agg.source_count == 2 and agg.window_hours == sp.WINDOW_HOURS
    old = [_art(9, "TCS old news, shares crash", hours_ago=400)]
    p.store_articles("TCS.NS", old)
    assert p.aggregate("TCS.NS", now=NOW).source_count == 2  # outside the 7-day window


def test_sentiment_alert_cites_negative_articles(db):
    p = sp.SentimentPipeline(db)
    p.store_articles("TCS.NS", [_art(i, f"TCS shares crash as fraud probe widens, losses mount {i}") for i in range(4)])
    db.add(SentimentScore(ticker="TCS.NS", score=0.3, source_count=5, window_hours=72, timestamp=NOW - timedelta(hours=24)))
    db.commit()
    p.aggregate("TCS.NS", now=NOW)
    alerts = pm.sentiment_alerts(db, "TCS.NS", NOW)
    assert len(alerts) == 1
    a = alerts[0]
    assert a["type"] == "SENTIMENT_CRASH" and "fell from +0.30" in a["message"]
    assert len(a["citations"]) == 4 and all(c["url"].startswith("https://news.example/") for c in a["citations"])


def test_no_sentiment_alert_on_one_article_or_mixed_news(db):
    p = sp.SentimentPipeline(db)
    p.store_articles("TCS.NS", [_art(1, "TCS shares crash after fraud probe")])
    p.aggregate("TCS.NS", now=NOW)
    assert pm.sentiment_alerts(db, "TCS.NS", NOW) == []  # fewer than 3 articles
    p.store_articles("TCS.NS", [_art(2, "TCS wins record deal, strong growth"), _art(3, "TCS dividend boost delights investors")])
    p.aggregate("TCS.NS", now=NOW)
    assert pm.sentiment_alerts(db, "TCS.NS", NOW) == []


def test_legacy_single_article_rows_are_ignored(db):
    db.add(SentimentScore(ticker="TCS.NS", score=-0.9, source_count=1, timestamp=NOW))
    db.add(SentimentScore(ticker="TCS.NS", score=0.6, source_count=1, timestamp=NOW - timedelta(minutes=5)))
    db.commit()
    assert pm.sentiment_alerts(db, "TCS.NS", NOW) == []


def test_price_alerts_and_citations():
    h = Portfolio(ticker="TCS.NS", quantity=4, avg_cost=2000.0, sl_pct=4, tg_pct=4, user_id=1)
    assert pm.price_alerts(h, 2000.0, NOW) == []
    sl = pm.price_alerts(h, 1900.0, NOW)
    assert sl[0]["type"] == "STOP_LOSS_BREACH" and "1,920.00" in sl[0]["message"]
    assert sl[0]["citations"][0]["url"] == "https://finance.yahoo.com/quote/TCS.NS"
    assert pm.price_alerts(h, 2100.0, NOW)[0]["type"] == "TARGET_HIT"


def test_rsi_and_volume():
    dates = [datetime(2026, 7, 1).date() + timedelta(days=i) for i in range(40)]
    up = [100 + i * 2 for i in range(40)]
    assert pm.rsi(up) == 100.0
    falling = [200 - i * 2 + (1 if i % 5 == 0 else 0) for i in range(40)]
    assert pm.rsi(falling) < 30
    vols = [1000.0] * 39 + [5000.0]
    alerts = pm.technical_alerts("SBIN.NS", dates, up, vols, "Yahoo Finance")
    assert {a["type"] for a in alerts} == {"RSI_OVERBOUGHT", "VOLUME_SPIKE"}
    assert all(a["citations"][0]["url"].endswith("/SBIN.NS/history") for a in alerts)


def test_cooldown(db):
    db.add(AlertLog(user_id=1, ticker="TCS.NS", alert_type="SENTIMENT_CRASH", message="x", signal="CAUTION",
                    created_at=NOW - timedelta(hours=2)))
    db.commit()
    assert pm._recently_alerted(db, 1, "TCS.NS", "SENTIMENT_CRASH", NOW)
    assert not pm._recently_alerted(db, 1, "TCS.NS", "SENTIMENT_CRASH", NOW + timedelta(hours=13))
    assert not pm._recently_alerted(db, 1, "SBIN.NS", "SENTIMENT_CRASH", NOW)


def test_subsidiaries_are_not_the_parent():
    assert not company_names.mentions("SBI Life Insurance shares rise 3%", "SBIN.NS")
    assert not company_names.mentions("SBI Card posts higher profit", "SBIN.NS")
    assert company_names.mentions("SBI Life rallies; State Bank of India flat", "SBIN.NS")
    assert not company_names.mentions("HDFC Life Q2 results", "HDFCBANK.NS")


def test_window_drops_articles_that_fail_current_rules(db):
    from backend.db.models import NewsArticle
    db.add(NewsArticle(ticker="SBIN.NS", url="u1", title="SBI Life shares jump", score=0.5, published_at=NOW))
    db.add(NewsArticle(ticker="SBIN.NS", url="u2", title="SBI raises deposit rates", score=0.2, published_at=NOW))
    db.commit()
    assert [a.url for a in sp.SentimentPipeline(db).window_articles("SBIN.NS", NOW)] == ["u2"]


def test_syndicated_duplicates_and_non_english_are_dropped(db):
    p = sp.SentimentPipeline(db)
    p.store_articles("SBIN.NS", [_art(1, "SBI raises FD rates"), _art(2, "SBI raises FD rates"),
                                 _art(3, "【SBI証券】遊びながら学ぶ教室を開催")])
    assert len(p.window_articles("SBIN.NS", NOW)) == 1


def test_evidence_text_lists_sentiment_articles():
    from backend.agent.evidence import evidence_digest
    ev = [{"id": "S1", "agent": "Sentiment Agent", "tool": "get_sentiment_score", "input": {"ticker": "TCS.NS"},
           "output": {"ticker": "TCS.NS", "available": True, "score": -0.4, "n_articles": 2,
                      "articles": [{"title": "TCS falls", "url": "u", "source": "BS", "published_at": "2026-10-07T00:00:00", "score": -0.8},
                                   {"title": "TCS flat", "url": "v", "source": "ET", "published_at": None, "score": 0.0}]}}]
    text = evidence_digest(ev)
    assert "[-0.80] 2026-10-07 BS: TCS falls" in text and "articles averaged (2)" in text
