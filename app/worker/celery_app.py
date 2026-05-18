from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery_app = Celery(
    "anvila",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=[
        "app.worker.tasks.generation",
        "app.worker.tasks.cleanup",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    beat_schedule={
        "purge-soft-deleted-records": {
            "task": "app.worker.tasks.cleanup.purge_soft_deleted",
            "schedule": crontab(hour=3, minute=0),
        }
    },
)
