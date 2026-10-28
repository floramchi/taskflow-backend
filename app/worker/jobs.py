import logging

from app.core.database import SessionLocal
from app.models import Notification, NotificationType, Task
from app.worker.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task
def notify_reassigned(task_id: int, assignee_id: int) -> None:
    with SessionLocal() as db:
        task = db.get(Task, task_id)
        # The task may have been deleted or reassigned again before this job ran.
        if task is None or task.assignee_id != assignee_id:
            return
        message = f"Task '{task.title}' was assigned to you"
        db.add(
            Notification(
                user_id=assignee_id,
                task_id=task.id,
                type=NotificationType.reassigned,
                message=message,
            )
        )
        db.commit()
    # Delivery is simulated: the notifications row plus this log line.
    logger.info("notification user=%s type=reassigned task=%s", assignee_id, task_id)
