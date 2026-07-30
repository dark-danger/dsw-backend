from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from typing import List
from app.database import get_db
from app.core.deps import require_role
from app.models.all_models import (
    User, UserRole, Event, Task, TaskStatus, QueryItem, QueryStatus,
    Announcement, DynamicForm, DynamicFormResponse, FeedbackForm, FeedbackResponse,
    StudentPointsLedger, AuditLog
)
from app.schemas.schemas import DashboardSummaryOut, AuditLogOut

router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])

@router.get("/summary", response_model=DashboardSummaryOut)
async def get_dashboard_summary(
    current_user: User = Depends(require_role([UserRole.super_admin])),
    db: AsyncSession = Depends(get_db)
):
    # Faculty & Student count
    fac_cnt = (await db.execute(select(func.count(User.id)).where(User.role == UserRole.faculty, User.is_active == True))).scalar_one()
    stu_cnt = (await db.execute(select(func.count(User.id)).where(User.role == UserRole.student, User.is_active == True))).scalar_one()

    # Events count & breakdown
    ev_cnt = (await db.execute(select(func.count(Event.id)))).scalar_one()
    ev_planned = (await db.execute(select(func.count(Event.id)).where(Event.status == "planned"))).scalar_one()
    ev_ongoing = (await db.execute(select(func.count(Event.id)).where(Event.status == "ongoing"))).scalar_one()
    ev_completed = (await db.execute(select(func.count(Event.id)).where(Event.status == "completed"))).scalar_one()

    # Tasks count & breakdown
    task_cnt = (await db.execute(select(func.count(Task.id)))).scalar_one()
    task_pending = (await db.execute(select(func.count(Task.id)).where(Task.status.in_(["pending", "in_progress"])))).scalar_one()
    task_submitted = (await db.execute(select(func.count(Task.id)).where(Task.status == "submitted"))).scalar_one()
    task_approved = (await db.execute(select(func.count(Task.id)).where(Task.status == "approved"))).scalar_one()
    task_declined = (await db.execute(select(func.count(Task.id)).where(Task.status == "declined"))).scalar_one()

    # Queries count & breakdown
    q_cnt = (await db.execute(select(func.count(QueryItem.id)))).scalar_one()
    q_open = (await db.execute(select(func.count(QueryItem.id)).where(QueryItem.status == "open"))).scalar_one()
    q_closed = (await db.execute(select(func.count(QueryItem.id)).where(QueryItem.status == "closed"))).scalar_one()

    # Announcements
    ann_cnt = (await db.execute(select(func.count(Announcement.id)))).scalar_one()

    # Dynamic Forms & Responses
    df_cnt = (await db.execute(select(func.count(DynamicForm.id)))).scalar_one()
    df_resp_cnt = (await db.execute(select(func.count(DynamicFormResponse.id)))).scalar_one()

    # Feedback Forms & Responses
    fb_cnt = (await db.execute(select(func.count(FeedbackForm.id)))).scalar_one()
    fb_resp_cnt = (await db.execute(select(func.count(FeedbackResponse.id)))).scalar_one()

    # Student Points Total
    total_pts = (await db.execute(select(func.coalesce(func.sum(StudentPointsLedger.points), 0)))).scalar_one()

    return DashboardSummaryOut(
        total_faculty=fac_cnt,
        total_students=stu_cnt,
        total_events=ev_cnt,
        events_breakdown={"planned": ev_planned, "ongoing": ev_ongoing, "completed": ev_completed},
        total_tasks=task_cnt,
        tasks_breakdown={"pending": task_pending, "submitted": task_submitted, "approved": task_approved, "declined": task_declined},
        total_queries=q_cnt,
        queries_breakdown={"open": q_open, "closed": q_closed},
        total_announcements=ann_cnt,
        total_dynamic_forms=df_cnt,
        total_form_responses=df_resp_cnt,
        total_feedback_forms=fb_cnt,
        total_feedback_responses=fb_resp_cnt,
        total_student_points_awarded=total_pts
    )

@router.get("/activity", response_model=List[AuditLogOut])
async def get_recent_activity_feed(
    current_user: User = Depends(require_role([UserRole.super_admin])),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(AuditLog).options(selectinload(AuditLog.actor)).order_by(AuditLog.created_at.desc()).limit(20)
    )
    logs = result.scalars().all()
    out = []
    for l in logs:
        out.append(AuditLogOut(
            id=l.id,
            actor_id=l.actor_id,
            actor_name=l.actor.name if l.actor else "System",
            action=l.action,
            entity_type=l.entity_type,
            entity_id=l.entity_id,
            meta=l.meta,
            created_at=l.created_at
        ))
    return out
