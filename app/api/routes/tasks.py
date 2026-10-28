from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, get_owned_project, get_owned_task
from app.models import Project, Task, User
from app.schemas.task import Page, TaskCreate, TaskFilter, TaskOut, TaskUpdate
from app.services import task_service

router = APIRouter(tags=["tasks"])


@router.post(
    "/projects/{project_id}/tasks", response_model=TaskOut, status_code=status.HTTP_201_CREATED
)
def create_task(
    payload: TaskCreate,
    project: Project = Depends(get_owned_project),
    db: Session = Depends(get_db),
) -> Task:
    return task_service.create_task(db, project, payload)


@router.get("/tasks/{task_id}", response_model=TaskOut)
def get_task(task: Task = Depends(get_owned_task)) -> Task:
    return task


@router.patch("/tasks/{task_id}", response_model=TaskOut)
def update_task(
    payload: TaskUpdate, task: Task = Depends(get_owned_task), db: Session = Depends(get_db)
) -> Task:
    return task_service.update_task(db, task, payload)


@router.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(task: Task = Depends(get_owned_task), db: Session = Depends(get_db)) -> Response:
    task_service.delete_task(db, task)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/tasks", response_model=Page[TaskOut])
def list_tasks(
    filters: Annotated[TaskFilter, Query()],
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Page[TaskOut]:
    items, total = task_service.list_tasks(db, user.id, filters)
    return Page(items=items, total=total, page=filters.page, size=filters.size)
