from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from typing import List, Optional
from app.database import get_db
from app.core.deps import get_current_user, require_role
from app.models.all_models import User, UserRole, Event, Task, TaskStatus, DutyChart
from app.schemas.schemas import DutyChartCreate, DutyChartOut
from app.services.notification_service import create_notification, log_audit

router = APIRouter(prefix="/api/duty-charts", tags=["Duty Charts"])

@router.post("", response_model=DutyChartOut)
async def create_duty_chart(
    payload: DutyChartCreate,
    current_user: User = Depends(require_role([UserRole.super_admin])),
    db: AsyncSession = Depends(get_db)
):
    # Verify Event exists
    ev_res = await db.execute(select(Event).where(Event.id == payload.event_id))
    event = ev_res.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=400, detail="Linked Event not found")

    enriched_duty_items = []
    
    for item in payload.duty_items:
        fac_res = await db.execute(select(User).where(User.id == item.assigned_to_id, User.role == UserRole.faculty))
        faculty = fac_res.scalar_one_or_none()
        
        fac_name = faculty.name if faculty else "Unassigned Staff"
        fac_dept = faculty.department if faculty else "DSW"
        fac_phone = faculty.phone if faculty else ""

        enriched_item = {
            "duty_name": item.duty_name,
            "assigned_to_id": item.assigned_to_id,
            "assigned_to_name": fac_name,
            "department": fac_dept,
            "phone": fac_phone,
            "role_description": item.role_description or "",
            "venue": item.venue or "",
            "time_slot": item.time_slot or ""
        }
        enriched_duty_items.append(enriched_item)

        # Create linked Task for each assigned faculty member
        if faculty:
            task_desc = f"Duty Role: {item.duty_name}\nVenue: {item.venue or 'Event Location'}\nTiming: {item.time_slot or 'Event Hours'}\nInstructions: {item.role_description or 'None'}"
            task = Task(
                title=f"Duty: {item.duty_name} ({event.title})",
                description=task_desc,
                task_type="event_linked",
                event_id=event.id,
                assigned_to=faculty.id,
                assigned_by=current_user.id,
                priority="high",
                status=TaskStatus.pending
            )
            db.add(task)
            
            # Send Notification
            await create_notification(
                db,
                title=f"Event Duty Assigned: {item.duty_name}",
                body=f"You have been assigned '{item.duty_name}' for event '{event.title}'. Venue: {item.venue or 'Campus'}",
                type="task_assigned",
                user_id=faculty.id,
                link="/faculty/tasks"
            )

    duty_chart = DutyChart(
        title=payload.title,
        event_id=payload.event_id,
        notes=payload.notes,
        duty_items=enriched_duty_items,
        created_by=current_user.id
    )
    db.add(duty_chart)
    await db.commit()
    await db.refresh(duty_chart)

    await log_audit(db, action="CREATE_DUTY_CHART", entity_type="duty_chart", actor_id=current_user.id, entity_id=duty_chart.id, meta={"title": duty_chart.title, "event": event.title})
    await db.commit()

    return DutyChartOut(
        id=duty_chart.id,
        title=duty_chart.title,
        event_id=duty_chart.event_id,
        event_title=event.title,
        notes=duty_chart.notes,
        duty_items=duty_chart.duty_items,
        created_by=duty_chart.created_by,
        creator_name=current_user.name,
        created_at=duty_chart.created_at
    )

@router.get("", response_model=List[DutyChartOut])
async def list_duty_charts(
    event_id: Optional[int] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    query = select(DutyChart).options(selectinload(DutyChart.event), selectinload(DutyChart.creator))
    if event_id:
        query = query.where(DutyChart.event_id == event_id)

    result = await db.execute(query.order_by(DutyChart.created_at.desc()))
    charts = result.scalars().all()

    out = []
    for c in charts:
        out.append(DutyChartOut(
            id=c.id,
            title=c.title,
            event_id=c.event_id,
            event_title=c.event.title if c.event else "N/A",
            notes=c.notes,
            duty_items=c.duty_items,
            created_by=c.created_by,
            creator_name=c.creator.name if c.creator else "DSW Office",
            created_at=c.created_at
        ))
    return out

@router.get("/{chart_id}", response_model=DutyChartOut)
async def get_duty_chart(
    chart_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(DutyChart)
        .options(selectinload(DutyChart.event), selectinload(DutyChart.creator))
        .where(DutyChart.id == chart_id)
    )
    c = result.scalar_one_or_none()
    if not c:
        raise HTTPException(status_code=404, detail="Duty Chart not found")

    return DutyChartOut(
        id=c.id,
        title=c.title,
        event_id=c.event_id,
        event_title=c.event.title if c.event else "N/A",
        notes=c.notes,
        duty_items=c.duty_items,
        created_by=c.created_by,
        creator_name=c.creator.name if c.creator else "DSW Office",
        created_at=c.created_at
    )

@router.delete("/{chart_id}")
async def delete_duty_chart(
    chart_id: int,
    current_user: User = Depends(require_role([UserRole.super_admin])),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(DutyChart).where(DutyChart.id == chart_id))
    c = result.scalar_one_or_none()
    if not c:
        raise HTTPException(status_code=404, detail="Duty Chart not found")

    await db.delete(c)
    await db.commit()
    return {"message": "Duty Chart deleted successfully"}
