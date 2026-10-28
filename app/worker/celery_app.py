from celery import Celery

from app.core.config import settings

celery_app = Celery("taskflow", broker=settings.redis_url)
celery_app.conf.update(
    task_always_eager=settings.celery_task_always_eager,
    task_eager_propagates=True,
    timezone="UTC",
)
