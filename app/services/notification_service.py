from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Notification
from app.schemas.common import PageParams


def list_notifications(
    db: Session, user_id: int, params: PageParams
) -> tuple[list[Notification], int]:
    base = select(Notification).where(Notification.user_id == user_id)
    total = db.scalar(select(func.count()).select_from(base.subquery()))
    items = db.scalars(
        base.order_by(Notification.created_at.desc(), Notification.id.desc())
        .offset((params.page - 1) * params.size)
        .limit(params.size)
    )
    return list(items), total
