import os
from celery import Celery
from celery.schedules import crontab

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "finsight_tasks",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["backend.tasks.data_ingestion"]
)

celery_app.conf.timezone = 'Asia/Kolkata'

celery_app.conf.beat_schedule = {
    # Fetch historical data once a day at 15:30 IST (market close)
    "fetch-historical-eod": {
        "task": "backend.tasks.data_ingestion.fetch_and_store_historical_data",
        "schedule": crontab(hour=15, minute=30, day_of_week="1-5"),
    },
    # Fetch live prices every 1 minute during market hours (09:15-15:30 IST, Mon-Fri)
    "fetch-live-prices": {
        "task": "backend.tasks.data_ingestion.fetch_live_prices",
        "schedule": crontab(minute="*", hour="9-15", day_of_week="1-5"),
    }
}
