from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Project, Task, User
from app.schemas.task import TaskCreate, TaskUpdate


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
    return task


def update_task(db: Session, task: Task, data: TaskUpdate) -> Task:
    changes = data.model_dump(exclude_unset=True)
    if "assignee_id" in changes:
        _check_assignee_exists(db, changes["assignee_id"])
    for field, value in changes.items():
        setattr(task, field, value)
    db.commit()
    return task


def delete_task(db: Session, task: Task) -> None:
    db.delete(task)
    db.commit()
