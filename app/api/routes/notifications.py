from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.models import User
from app.schemas.common import Page, PageParams
from app.schemas.notification import NotificationOut
from app.services import notification_service

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=Page[NotificationOut])
def list_notifications(
    params: Annotated[PageParams, Query()],
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Page[NotificationOut]:
    items, total = notification_service.list_notifications(db, user.id, params)
    return Page(items=items, total=total, page=params.page, size=params.size)
