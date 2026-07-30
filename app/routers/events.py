from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from typing import List, Optional
from app.database import get_db
from app.core.deps import get_current_user, require_role
from app.models.all_models import User, UserRole, Event, Task, TaskStatus, TaskSubmission
from app.schemas.schemas import EventCreate, EventUpdate, EventOut, TaskOut
from app.services.pdf_report_service import generate_micro_report_html, generate_merged_report_html
from app.services.notification_service import log_audit
from app.routers.tasks import build_task_out

router = APIRouter(prefix="/api/events", tags=["Events & Reports"])

def build_event_out(e: Event) -> EventOut:
    tasks = e.tasks if hasattr(e, "tasks") and e.tasks else []
    total = len(tasks)
    completed = sum(1 for t in tasks if t.status == TaskStatus.approved)
    pct = round((completed / total * 100), 1) if total > 0 else 0.0

    return EventOut(
        id=e.id,
        title=e.title,
        description=e.description,
        event_type=e.event_type,
        start_date=e.start_date,
        end_date=e.end_date,
        venue=e.venue,
        coordinator_id=e.coordinator_id,
        coordinator=e.coordinator,
        status=e.status,
        created_by=e.created_by,
        created_at=e.created_at,
        tasks_count=total,
        completed_tasks_count=completed,
        completion_percentage=pct
    )

@router.post("", response_model=EventOut)
async def create_event(
    payload: EventCreate,
    current_user: User = Depends(require_role([UserRole.super_admin])),
    db: AsyncSession = Depends(get_db)
):
    event = Event(
        title=payload.title,
        description=payload.description,
        event_type=payload.event_type,
        start_date=payload.start_date,
        end_date=payload.end_date,
        venue=payload.venue,
        coordinator_id=payload.coordinator_id,
        status=payload.status,
        created_by=current_user.id
    )
    db.add(event)
    await db.commit()

    res = await db.execute(
        select(Event).options(selectinload(Event.coordinator), selectinload(Event.tasks)).where(Event.id == event.id)
    )
    created = res.scalar_one()

    await log_audit(db, action="CREATE_EVENT", entity_type="event", actor_id=current_user.id, entity_id=event.id, meta={"title": event.title})
    await db.commit()

    return build_event_out(created)

from app.core.deps import get_current_user, get_current_user_optional, require_role

@router.get("", response_model=List[EventOut])
async def list_events(
    status_filter: Optional[str] = None,
    search: Optional[str] = None,
    current_user: Optional[User] = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db)
):
    query = select(Event).options(selectinload(Event.coordinator), selectinload(Event.tasks))
    if status_filter:
        query = query.where(Event.status == status_filter)
    if search:
        query = query.where(Event.title.ilike(f"%{search}%"))

    result = await db.execute(query.order_by(Event.start_date.desc()))
    events = result.scalars().all()
    return [build_event_out(e) for e in events]

@router.get("/{event_id}", response_model=EventOut)
async def get_event_detail(
    event_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(Event).options(selectinload(Event.coordinator), selectinload(Event.tasks)).where(Event.id == event_id)
    )
    event = result.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return build_event_out(event)

@router.patch("/{event_id}", response_model=EventOut)
async def update_event(
    event_id: int,
    payload: EventUpdate,
    current_user: User = Depends(require_role([UserRole.super_admin])),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(Event).options(selectinload(Event.coordinator), selectinload(Event.tasks)).where(Event.id == event_id)
    )
    event = result.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(event, k, v)

    await db.commit()
    await db.refresh(event)
    return build_event_out(event)

@router.delete("/{event_id}")
async def delete_event(
    event_id: int,
    current_user: User = Depends(require_role([UserRole.super_admin])),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Event).where(Event.id == event_id))
    event = result.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
        
    await db.delete(event)
    await db.commit()
    return {"message": "Event deleted successfully"}


@router.get("/{event_id}/tasks", response_model=List[TaskOut])
async def get_event_tasks(
    event_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(Task)
        .options(
            selectinload(Task.assignee),
            selectinload(Task.event),
            selectinload(Task.submissions),
            selectinload(Task.subtasks).selectinload(Task.assignee),
            selectinload(Task.subtasks).selectinload(Task.event),
            selectinload(Task.subtasks).selectinload(Task.submissions)
        )
        .where(Task.event_id == event_id)
        .order_by(Task.created_at.asc())
    )
    tasks = result.scalars().all()
    # Filter top-level tasks to avoid duplicate listing if they are subtasks
    top_tasks = [t for t in tasks if t.parent_task_id is None]
    return [build_task_out(t) for t in top_tasks]

# REPORT AUTOMATION (MICRO & MERGED HTML/PDF PREVIEWS)
@router.get("/{event_id}/reports/micro/{task_id}", response_class=HTMLResponse)
async def get_micro_task_report_html(
    event_id: int,
    task_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    ev_res = await db.execute(select(Event).options(selectinload(Event.coordinator)).where(Event.id == event_id))
    event = ev_res.scalar_one_or_none()
    
    t_res = await db.execute(
        select(Task).options(selectinload(Task.assignee), selectinload(Task.submissions)).where(Task.id == task_id)
    )
    task = t_res.scalar_one_or_none()
    if not task or task.event_id != event_id:
        raise HTTPException(status_code=404, detail="Task not found under this event")

    latest_sub = task.submissions[-1] if task.submissions else None
    
    task_dict = {
        "title": task.title,
        "description": task.description,
        "priority": task.priority.value,
        "status": task.status.value,
        "due_date": task.due_date.strftime("%Y-%m-%d %H:%M") if task.due_date else None,
        "created_at": task.created_at.strftime("%Y-%m-%d"),
        "assignee": {"name": task.assignee.name} if task.assignee else None
    }
    event_dict = {"title": event.title} if event else None
    sub_dict = {
        "description": latest_sub.description,
        "file_url": latest_sub.file_url,
        "file_name": latest_sub.file_name,
        "submitted_at": latest_sub.submitted_at.strftime("%Y-%m-%d %H:%M"),
        "review_remarks": latest_sub.review_remarks
    } if latest_sub else None

    html_content = generate_micro_report_html(task_dict, event_dict, sub_dict)
    return HTMLResponse(content=html_content)

@router.get("/{event_id}/reports/merged", response_class=HTMLResponse)
async def get_merged_event_report_html(
    event_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    ev_res = await db.execute(
        select(Event)
        .options(selectinload(Event.coordinator), selectinload(Event.tasks).selectinload(Task.assignee), selectinload(Event.tasks).selectinload(Task.submissions))
        .where(Event.id == event_id)
    )
    event = ev_res.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    tasks_data = []
    completed_count = 0
    for t in event.tasks:
        if t.status == TaskStatus.approved:
            completed_count += 1
        sub_list = []
        if t.submissions:
            latest = t.submissions[-1]
            sub_list.append({
                "description": latest.description,
                "file_url": latest.file_url,
                "file_name": latest.file_name,
                "review_remarks": latest.review_remarks
            })
        tasks_data.append({
            "title": t.title,
            "description": t.description,
            "priority": t.priority.value,
            "status": t.status.value,
            "assignee": {"name": t.assignee.name} if t.assignee else None,
            "submissions": sub_list
        })

    total_tasks = len(event.tasks)
    pct = round((completed_count / total_tasks * 100), 1) if total_tasks > 0 else 0.0

    event_dict = {
        "title": event.title,
        "description": event.description,
        "event_type": event.event_type,
        "venue": event.venue,
        "status": event.status.value,
        "start_date": event.start_date.strftime("%Y-%m-%d") if event.start_date else "N/A",
        "end_date": event.end_date.strftime("%Y-%m-%d") if event.end_date else "N/A",
        "coordinator": {"name": event.coordinator.name} if event.coordinator else None
    }
    stats_dict = {
        "total_tasks": total_tasks,
        "completed_tasks": completed_count,
        "completion_percentage": pct
    }

    html_content = generate_merged_report_html(event_dict, tasks_data, stats_dict)
    return HTMLResponse(content=html_content)
