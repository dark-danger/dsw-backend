from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, or_
from typing import List
from app.database import get_db
from app.core.deps import get_current_user
from app.models.all_models import User, Notification
from app.schemas.schemas import NotificationOut

router = APIRouter(prefix="/api/notifications", tags=["Notifications"])

@router.get("", response_model=List[NotificationOut])
async def get_my_notifications(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    # Get user notifications or global broadcast notifications (user_id IS NULL)
    result = await db.execute(
        select(Notification)
        .where(or_(Notification.user_id == current_user.id, Notification.user_id == None))
        .order_by(Notification.created_at.desc())
        .limit(30)
    )
    notifs = result.scalars().all()
    return [NotificationOut.model_validate(n) for n in notifs]

@router.post("/{notification_id}/read")
async def mark_notification_read(
    notification_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Notification).where(Notification.id == notification_id))
    notif = result.scalar_one_or_none()
    if notif and (notif.user_id == current_user.id or notif.user_id is None):
        notif.is_read = True
        await db.commit()
    return {"message": "Marked as read"}

@router.post("/read-all")
async def mark_all_read(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    await db.execute(
        update(Notification)
        .where(or_(Notification.user_id == current_user.id, Notification.user_id == None))
        .values(is_read=True)
    )
    await db.commit()
    return {"message": "All notifications marked as read"}
