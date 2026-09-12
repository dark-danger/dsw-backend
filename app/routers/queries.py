from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from typing import List, Optional
from datetime import datetime, timezone
from app.database import get_db
from app.core.deps import get_current_user, require_role
from app.models.all_models import User, UserRole, QueryItem, QueryStatus
from app.schemas.schemas import QueryCreate, QueryClosePayload, QueryOut
from app.services.notification_service import create_notification, log_audit

router = APIRouter(prefix="/api/queries", tags=["Queries & Grievances"])

def build_query_out(q: QueryItem) -> QueryOut:
    target_fac_out = None
    if q.target_faculty:
        target_fac_out = UserOut.model_validate(q.target_faculty)

    return QueryOut(
        id=q.id,
        raised_by=q.raised_by,
        raiser=q.raiser,
        raiser_role=q.raiser_role,
        subject=q.subject,
        category=q.category,
        description=q.description,
        status=q.status,
        target_type=q.target_type or "admin",
        target_faculty_id=q.target_faculty_id,
        target_faculty_name=q.target_faculty_name,
        target_faculty=target_fac_out,
        admin_remarks=q.admin_remarks,
        closed_by=q.closed_by,
        closer=q.closer,
        closed_at=q.closed_at,
        created_at=q.created_at
    )

@router.post("", response_model=QueryOut)
async def raise_query(
    payload: QueryCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    target_faculty_name = payload.target_faculty_name
    if payload.target_type == "faculty_head" and payload.target_faculty_id and not target_faculty_name:
        f_res = await db.execute(select(User).where(User.id == payload.target_faculty_id))
        fac = f_res.scalar_one_or_none()
        if fac:
            target_faculty_name = fac.name

    query_item = QueryItem(
        raised_by=current_user.id,
        raiser_role=current_user.role.value,
        subject=payload.subject,
        category=payload.category,
        description=payload.description,
        target_type=payload.target_type or "admin",
        target_faculty_id=payload.target_faculty_id if payload.target_type == "faculty_head" else None,
        target_faculty_name=target_faculty_name if payload.target_type == "faculty_head" else None,
        status=QueryStatus.open
    )
    db.add(query_item)
    await db.commit()

    res = await db.execute(
        select(QueryItem).options(
            selectinload(QueryItem.raiser),
            selectinload(QueryItem.target_faculty)
        ).where(QueryItem.id == query_item.id)
    )
    created = res.scalar_one()

    # If target is faculty head, notify that faculty coordinator
    if payload.target_type == "faculty_head" and payload.target_faculty_id:
        await create_notification(
            db,
            title="Student Query Received",
            body=f"{current_user.name} submitted a query to you: '{payload.subject}'",
            type="query_assigned",
            user_id=payload.target_faculty_id,
            link="/faculty/queries"
        )

    await log_audit(db, action="RAISE_QUERY", entity_type="query", actor_id=current_user.id, entity_id=query_item.id)
    await db.commit()

    return build_query_out(created)

@router.get("", response_model=List[QueryOut])
async def list_queries(
    status_filter: Optional[str] = None,
    category: Optional[str] = None,
    role_filter: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    query = select(QueryItem).options(
        selectinload(QueryItem.raiser),
        selectinload(QueryItem.closer),
        selectinload(QueryItem.target_faculty)
    )

    if current_user.role == UserRole.student:
        query = query.where(QueryItem.raised_by == current_user.id)
    elif current_user.role == UserRole.faculty:
        # Faculty sees queries they raised OR queries addressed to them as Faculty Head
        query = query.where(
            (QueryItem.raised_by == current_user.id) | (QueryItem.target_faculty_id == current_user.id)
        )
    else: # super_admin
        if role_filter:
            query = query.where(QueryItem.raiser_role == role_filter)

    if status_filter:
        query = query.where(QueryItem.status == status_filter)
    if category:
        query = query.where(QueryItem.category == category)

    result = await db.execute(query.order_by(QueryItem.created_at.desc()))
    items = result.scalars().all()
    return [build_query_out(q) for q in items]

@router.get("/{query_id}", response_model=QueryOut)
async def get_query_detail(
    query_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(QueryItem).options(
            selectinload(QueryItem.raiser),
            selectinload(QueryItem.closer),
            selectinload(QueryItem.target_faculty)
        ).where(QueryItem.id == query_id)
    )
    query_item = result.scalar_one_or_none()
    if not query_item:
        raise HTTPException(status_code=404, detail="Query not found")

    if current_user.role == UserRole.student and query_item.raised_by != current_user.id:
        raise HTTPException(status_code=403, detail="You do not have permission to view this query")
    elif current_user.role == UserRole.faculty and query_item.raised_by != current_user.id and query_item.target_faculty_id != current_user.id:
        raise HTTPException(status_code=403, detail="You do not have permission to view this query")

    return build_query_out(query_item)

@router.post("/{query_id}/close", response_model=QueryOut)
async def close_query(
    query_id: int,
    payload: QueryClosePayload,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(QueryItem).options(
            selectinload(QueryItem.raiser),
            selectinload(QueryItem.target_faculty)
        ).where(QueryItem.id == query_id)
    )
    query_item = result.scalar_one_or_none()
    if not query_item:
        raise HTTPException(status_code=404, detail="Query not found")

    # Super admin or targeted faculty head can resolve
    if current_user.role != UserRole.super_admin and query_item.target_faculty_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to resolve this query")

    query_item.status = QueryStatus.closed
    query_item.admin_remarks = payload.admin_remarks
    query_item.closed_by = current_user.id
    query_item.closed_at = datetime.now(timezone.utc)

    await db.commit()

    resolver_label = "DSW Admin" if current_user.role == UserRole.super_admin else f"Faculty Head ({current_user.name})"
    await create_notification(
        db,
        title="Query Resolved & Closed",
        body=f"Your query '{query_item.subject}' has been closed by {resolver_label}. Remarks: '{payload.admin_remarks}'",
        type="query_closed",
        user_id=query_item.raised_by,
        link=f"/{query_item.raiser_role}/queries"
    )
    await log_audit(db, action="CLOSE_QUERY", entity_type="query", actor_id=current_user.id, entity_id=query_item.id)
    await db.commit()

    return await get_query_detail(query_id, current_user, db)

@router.post("/{query_id}/reopen", response_model=QueryOut)
async def reopen_query(
    query_id: int,
    current_user: User = Depends(require_role([UserRole.super_admin])),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(QueryItem).where(QueryItem.id == query_id))
    query_item = result.scalar_one_or_none()
    if not query_item:
        raise HTTPException(status_code=404, detail="Query not found")

    query_item.status = QueryStatus.open
    query_item.closed_at = None
    await db.commit()

    return await get_query_detail(query_id, current_user, db)

@router.delete("/{query_id}")
async def delete_query(
    query_id: int,
    current_user: User = Depends(require_role([UserRole.super_admin])),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(QueryItem).where(QueryItem.id == query_id))
    query_item = result.scalar_one_or_none()
    if not query_item:
        raise HTTPException(status_code=404, detail="Query not found")
        
    await db.delete(query_item)
    await db.commit()
    return {"message": "Query deleted successfully"}

