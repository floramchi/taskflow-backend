from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Project
from app.schemas.project import ProjectCreate, ProjectUpdate


def list_projects(db: Session, owner_id: int) -> list[Project]:
    return list(
        db.scalars(select(Project).where(Project.owner_id == owner_id).order_by(Project.id))
    )


def get_owned_project(db: Session, project_id: int, owner_id: int) -> Project | None:
    return db.scalar(select(Project).where(Project.id == project_id, Project.owner_id == owner_id))


def create_project(db: Session, owner_id: int, data: ProjectCreate) -> Project:
    project = Project(owner_id=owner_id, **data.model_dump())
    db.add(project)
    db.commit()
    return project


def update_project(db: Session, project: Project, data: ProjectUpdate) -> Project:
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(project, field, value)
    db.commit()
    return project


def delete_project(db: Session, project: Project) -> None:
    db.delete(project)
    db.commit()
