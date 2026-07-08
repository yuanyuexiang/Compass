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
    # 每分钟轻量 tick：读取管理员配置的采集间隔（system_settings），到点才真正派发。
    # 间隔改动即时生效，无需重启 beat；按 sources.cron 逐源精确调度留 V1.x（需 RedBeat）。
    "crawl-scheduler-tick": {
        "task": "app.tasks.pipeline.crawl_tick",
        "schedule": crontab(),  # 每分钟
    },
    # 每日商机日报（§7，默认 8:30）
    "daily-digest": {
        "task": "app.tasks.pipeline.daily_digest",
        "schedule": crontab(hour=8, minute=30),
    },
}
