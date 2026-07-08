from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery = Celery("compass", broker=settings.redis_url, include=["app.tasks.pipeline"])

celery.conf.update(
    timezone="Asia/Shanghai",
    task_acks_late=True,
    worker_prefetch_multiplier=1,  # 采集任务耗时不均，避免囤积
    broker_connection_retry_on_startup=True,
)

celery.conf.beat_schedule = {
    # 每半小时全量调度；按 sources.cron 逐源精确调度留 V1.x（需 RedBeat）
    "crawl-all-sources": {
        "task": "app.tasks.pipeline.crawl_all_sources",
        "schedule": crontab(minute="0,30"),
    },
    # 每日商机日报（§7，默认 8:30）
    "daily-digest": {
        "task": "app.tasks.pipeline.daily_digest",
        "schedule": crontab(hour=8, minute=30),
    },
}
