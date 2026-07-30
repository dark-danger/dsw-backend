from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from typing import List, Optional
from app.database import get_db
from app.core.deps import get_current_user, require_role
from app.models.all_models import User, UserRole, Announcement, AnnouncementReaction, AnnouncementAudience
from app.schemas.schemas import AnnouncementCreate, AnnouncementOut, ReactionPayload, UserOut
from app.services.notification_service import create_notification, log_audit

router = APIRouter(prefix="/api/announcements", tags=["Announcements"])

def build_announcement_out(a: Announcement, current_user_id: int) -> AnnouncementOut:
    counts: dict = {}
    user_react = None

    if hasattr(a, "reactions") and a.reactions:
        for r in a.reactions:
            counts[r.reaction_type] = counts.get(r.reaction_type, 0) + 1
            if r.user_id == current_user_id:
                user_react = r.reaction_type

    return AnnouncementOut(
        id=a.id,
        title=a.title,
        body=a.body,
        audience=a.audience,
        created_by=a.created_by,
        author=UserOut.model_validate(a.author) if a.author else None,
        pinned=a.pinned,
        attachment_url=a.attachment_url,
        expiry_date=a.expiry_date,
        created_at=a.created_at,
        reaction_counts=counts,
        user_reaction=user_react
    )

@router.post("", response_model=AnnouncementOut)
async def create_announcement(
    payload: AnnouncementCreate,
    current_user: User = Depends(require_role([UserRole.super_admin])),
    db: AsyncSession = Depends(get_db)
):
    announcement = Announcement(
        title=payload.title,
        body=payload.body,
        audience=payload.audience,
        pinned=payload.pinned,
        attachment_url=payload.attachment_url,
        expiry_date=payload.expiry_date,
        created_by=current_user.id
    )
    db.add(announcement)
    await db.commit()

    res = await db.execute(
        select(Announcement).options(selectinload(Announcement.author), selectinload(Announcement.reactions)).where(Announcement.id == announcement.id)
    )
    created = res.scalar_one()

    # Create global broadcast notification
    await create_notification(
        db,
        title="📢 New Announcement",
        body=f"{payload.title}",
        type="announcement",
        user_id=None, # broadcast
        link=f"/{current_user.role.value}/announcements"
    )
    await log_audit(db, action="CREATE_ANNOUNCEMENT", entity_type="announcement", actor_id=current_user.id, entity_id=announcement.id)
    await db.commit()

    return build_announcement_out(created, current_user.id)

@router.get("", response_model=List[AnnouncementOut])
async def list_announcements(
    audience_filter: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    query = select(Announcement).options(selectinload(Announcement.author), selectinload(Announcement.reactions))

    if current_user.role == UserRole.faculty:
        query = query.where(Announcement.audience.in_([AnnouncementAudience.faculty, AnnouncementAudience.both]))
    elif current_user.role == UserRole.student:
        query = query.where(Announcement.audience.in_([AnnouncementAudience.students, AnnouncementAudience.both]))
    elif audience_filter:
        query = query.where(Announcement.audience == audience_filter)

    # Pinned first, then latest created
    result = await db.execute(query.order_by(Announcement.pinned.desc(), Announcement.created_at.desc()))
    items = result.scalars().all()
    return [build_announcement_out(a, current_user.id) for a in items]

@router.delete("/{announcement_id}")
async def delete_announcement(
    announcement_id: int,
    current_user: User = Depends(require_role([UserRole.super_admin])),
    db: AsyncSession = Depends(get_db)
):
    res = await db.execute(select(Announcement).where(Announcement.id == announcement_id))
    ann = res.scalar_one_or_none()
    if not ann:
        raise HTTPException(status_code=404, detail="Announcement not found")

    await db.delete(ann)
    await db.commit()
    return {"message": "Announcement deleted"}

@router.post("/{announcement_id}/react", response_model=AnnouncementOut)
async def react_to_announcement(
    announcement_id: int,
    payload: ReactionPayload,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    ann_res = await db.execute(
        select(Announcement).options(selectinload(Announcement.author), selectinload(Announcement.reactions)).where(Announcement.id == announcement_id)
    )
    ann = ann_res.scalar_one_or_none()
    if not ann:
        raise HTTPException(status_code=404, detail="Announcement not found")

    # Check existing reaction by user
    react_res = await db.execute(
        select(AnnouncementReaction).where(
            AnnouncementReaction.announcement_id == announcement_id,
            AnnouncementReaction.user_id == current_user.id
        )
    )
    existing_react = react_res.scalar_one_or_none()

    if existing_react:
        if existing_react.reaction_type == payload.reaction_type:
            # Toggle off
            await db.delete(existing_react)
        else:
            # Change reaction
            existing_react.reaction_type = payload.reaction_type
    else:
        new_react = AnnouncementReaction(
            announcement_id=announcement_id,
            user_id=current_user.id,
            reaction_type=payload.reaction_type
        )
        db.add(new_react)

    await db.commit()

    # Re-fetch for updated count
    ann_updated = (await db.execute(
        select(Announcement).options(selectinload(Announcement.author), selectinload(Announcement.reactions)).where(Announcement.id == announcement_id)
    )).scalar_one()

    return build_announcement_out(ann_updated, current_user.id)
