from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models import TaskStatus
from app.schemas.common import PageParams


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = None
    status: TaskStatus = TaskStatus.todo
    assignee_id: int | None = None
    due_date: datetime | None = None


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    status: TaskStatus | None = None
    assignee_id: int | None = None
    due_date: datetime | None = None


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    title: str
    description: str | None
    status: TaskStatus
    assignee_id: int | None
    due_date: datetime | None
    created_at: datetime
    updated_at: datetime


class TaskFilter(PageParams):
    status: TaskStatus | None = None
    assignee_id: int | None = None
    project_id: int | None = None
    due_after: datetime | None = None
    due_before: datetime | None = None
