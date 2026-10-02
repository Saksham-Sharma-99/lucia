import uuid
from datetime import datetime

from fastapi import status
from sqlalchemy import select, update

from lucia.api.tags import api_router
from lucia.auth.deps import CurrentUser, DbSession
from lucia.core.clock import get_clock
from lucia.core.schema import Read
from lucia.db.models import Notification, StepResult

router = api_router("notifications", "/notifications")


class NotificationOut(Read):
    id: uuid.UUID
    run_id: uuid.UUID | None
    step_result_id: uuid.UUID | None
    summary: str
    urgency: str
    read_at: datetime | None
    created_at: datetime


def _mine(user_id: uuid.UUID):
    return (Notification.channel == "in_app") & (Notification.target == str(user_id))


@router.get("", summary="My in-app notifications, newest first", operation_id="listNotifications")
async def list_notifications(
    session: DbSession, user: CurrentUser, unread: bool = False
) -> list[NotificationOut]:
    stmt = (
        select(Notification, StepResult.summary, StepResult.urgency)
        .join(StepResult, StepResult.id == Notification.step_result_id)
        .where(_mine(user.id))
        .order_by(Notification.created_at.desc())
        .limit(50)
    )
    if unread:
        stmt = stmt.where(Notification.read_at.is_(None))
    return [
        NotificationOut(
            id=n.id,
            run_id=n.run_id,
            step_result_id=n.step_result_id,
            summary=summary,
            urgency=urgency,
            read_at=n.read_at,
            created_at=n.created_at,
        )
        for n, summary, urgency in (await session.execute(stmt)).all()
    ]


@router.post(
    "/{notification_id}/read",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Mark a notification read",
    operation_id="markNotificationRead",
)
async def mark_read(notification_id: uuid.UUID, session: DbSession, user: CurrentUser) -> None:
    await session.execute(
        update(Notification)
        .where(Notification.id == notification_id, _mine(user.id))
        .values(read_at=get_clock().now())
    )
    await session.commit()


@router.post(
    "/read-all",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Mark all my notifications read",
    operation_id="markAllNotificationsRead",
)
async def mark_all_read(session: DbSession, user: CurrentUser) -> None:
    await session.execute(
        update(Notification)
        .where(_mine(user.id), Notification.read_at.is_(None))
        .values(read_at=get_clock().now())
    )
    await session.commit()
