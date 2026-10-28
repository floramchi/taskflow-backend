import logging

from sqlalchemy import func, literal, select, text
from sqlalchemy.dialects.postgresql import insert

from app.core.database import SessionLocal
from app.models import Notification, NotificationType, Task, TaskStatus
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


@celery_app.task
def scan_overdue_tasks() -> int:
    """Create one overdue notification per past-due, unfinished, assigned task."""
    overdue = select(
        Task.assignee_id,
        Task.id,
        literal(NotificationType.overdue, Notification.type.type),
        func.concat("Task '", Task.title, "' is overdue"),
    ).where(
        Task.due_date < func.now(),
        Task.status != TaskStatus.done,
        Task.assignee_id.is_not(None),
    )
    # The partial unique index makes repeated scans idempotent: tasks that already
    # have an overdue notification are skipped instead of notified again.
    stmt = (
        insert(Notification)
        .from_select(["user_id", "task_id", "type", "message"], overdue)
        .on_conflict_do_nothing(
            index_elements=["task_id", "type"], index_where=text("type = 'overdue'")
        )
    )
    with SessionLocal() as db:
        created = len(db.execute(stmt.returning(Notification.id)).all())
        db.commit()
    logger.info("overdue scan created %s notification(s)", created)
    return created
