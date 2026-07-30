from typing import Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.all_models import Notification, AuditLog

async def create_notification(
    db: AsyncSession,
    title: str,
    body: str,
    type: str,
    user_id: Optional[int] = None,
    link: Optional[str] = None
):
    notif = Notification(
        user_id=user_id,
        title=title,
        body=body,
        type=type,
        link=link
    )
    db.add(notif)
    # caller commits transaction

async def log_audit(
    db: AsyncSession,
    action: str,
    entity_type: str,
    actor_id: Optional[int] = None,
    entity_id: Optional[int] = None,
    meta: Optional[Dict[str, Any]] = None
):
    audit = AuditLog(
        actor_id=actor_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        meta=meta or {}
    )
    db.add(audit)
