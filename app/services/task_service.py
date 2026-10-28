import logging

from kombu.exceptions import OperationalError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import cache
from app.models import Project, Task, User
from app.schemas.common import Page
from app.schemas.task import TaskCreate, TaskFilter, TaskOut, TaskUpdate
from app.worker.jobs import notify_reassigned

logger = logging.getLogger(__name__)


class AssigneeNotFoundError(Exception):
    pass


def _check_assignee_exists(db: Session, assignee_id: int | None) -> None:
    if assignee_id is not None and db.get(User, assignee_id) is None:
        raise AssigneeNotFoundError(assignee_id)


def get_owned_task(db: Session, task_id: int, owner_id: int) -> Task | None:
    # Tasks are only reachable through projects the user owns.
    return db.scalar(
        select(Task)
        .join(Project, Task.project_id == Project.id)
        .where(Task.id == task_id, Project.owner_id == owner_id)
    )


def create_task(db: Session, project: Project, data: TaskCreate) -> Task:
    _check_assignee_exists(db, data.assignee_id)
    task = Task(project_id=project.id, **data.model_dump())
    db.add(task)
    db.commit()
    cache.bump_tasks_version(project.owner_id)
    return task


def update_task(db: Session, task: Task, data: TaskUpdate, owner_id: int) -> Task:
    changes = data.model_dump(exclude_unset=True)
    if "assignee_id" in changes:
        _check_assignee_exists(db, changes["assignee_id"])
    new_assignee_id = changes.get("assignee_id")
    reassigned = new_assignee_id is not None and new_assignee_id != task.assignee_id
    for field, value in changes.items():
        setattr(task, field, value)
    db.commit()
    cache.bump_tasks_version(owner_id)
    if reassigned:
        _enqueue_reassignment_notification(task.id, new_assignee_id)
    return task


def _enqueue_reassignment_notification(task_id: int, assignee_id: int) -> None:
    # Enqueued after the commit so the worker always sees the committed row.
    # If the broker is down the update still stands; the notification is lost.
    try:
        notify_reassigned.delay(task_id, assignee_id)
    except OperationalError:
        logger.exception("Could not enqueue reassignment notification for task %s", task_id)


def delete_task(db: Session, task: Task, owner_id: int) -> None:
    db.delete(task)
    db.commit()
    cache.bump_tasks_version(owner_id)


def list_tasks(db: Session, owner_id: int, filters: TaskFilter) -> tuple[list[Task], int]:
    conditions = [Project.owner_id == owner_id]
    if filters.status is not None:
        conditions.append(Task.status == filters.status)
    if filters.assignee_id is not None:
        conditions.append(Task.assignee_id == filters.assignee_id)
    if filters.project_id is not None:
        conditions.append(Task.project_id == filters.project_id)
    if filters.due_after is not None:
        conditions.append(Task.due_date >= filters.due_after)
    if filters.due_before is not None:
        conditions.append(Task.due_date <= filters.due_before)

    base = select(Task).join(Project, Task.project_id == Project.id).where(*conditions)
    total = db.scalar(select(func.count()).select_from(base.subquery()))
    items = db.scalars(
        base.order_by(Task.id).offset((filters.page - 1) * filters.size).limit(filters.size)
    )
    return list(items), total


def list_tasks_json(db: Session, owner_id: int, filters: TaskFilter) -> tuple[str, bool]:
    """Return the serialized page and whether it came from the cache."""
    key = cache.tasks_key(owner_id, filters.model_dump(mode="json"))
    cached = cache.get_cached(key)
    if cached is not None:
        return cached, True

    items, total = list_tasks(db, owner_id, filters)
    page = Page[TaskOut](
        items=[TaskOut.model_validate(t) for t in items],
        total=total,
        page=filters.page,
        size=filters.size,
    )
    body = page.model_dump_json()
    cache.set_cached(key, body)
    return body, False
