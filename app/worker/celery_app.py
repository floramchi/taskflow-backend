from celery import Celery

from app.core.config import settings

celery_app = Celery("taskflow", broker=settings.redis_url)
celery_app.conf.update(
    task_always_eager=settings.celery_task_always_eager,
    task_eager_propagates=True,
    imports=["app.worker.jobs"],
    timezone="UTC",
)

celery_app.conf.beat_schedule = {
    "scan-overdue-tasks": {
        "task": "app.worker.jobs.scan_overdue_tasks",
        "schedule": float(settings.overdue_scan_seconds),
    },
}
