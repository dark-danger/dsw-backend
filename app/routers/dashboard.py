from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, case
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
    # 1. Faculty & Student count in a single query
    user_counts = (await db.execute(
        select(
            func.count(case((User.role == UserRole.faculty, 1))).label("faculty_cnt"),
            func.count(case((User.role == UserRole.student, 1))).label("student_cnt")
        ).where(User.is_active == True)
    )).one()

    # 2. Events count & breakdown in a single query
    event_counts = (await db.execute(
        select(
            func.count(Event.id).label("total"),
            func.count(case((Event.status == "planned", 1))).label("planned"),
            func.count(case((Event.status == "ongoing", 1))).label("ongoing"),
            func.count(case((Event.status == "completed", 1))).label("completed")
        )
    )).one()

    # 3. Tasks count & breakdown in a single query
    task_counts = (await db.execute(
        select(
            func.count(Task.id).label("total"),
            func.count(case((Task.status.in_([TaskStatus.pending, TaskStatus.in_progress]), 1))).label("pending"),
            func.count(case((Task.status == TaskStatus.submitted, 1))).label("submitted"),
            func.count(case((Task.status == TaskStatus.approved, 1))).label("approved"),
            func.count(case((Task.status == TaskStatus.declined, 1))).label("declined")
        )
    )).one()

    # 4. Queries count & breakdown in a single query
    query_counts = (await db.execute(
        select(
            func.count(QueryItem.id).label("total"),
            func.count(case((QueryItem.status == "open", 1))).label("open"),
            func.count(case((QueryItem.status == "closed", 1))).label("closed")
        )
    )).one()

    # 5. Announcements, Forms, Feedback, Points
    ann_cnt = (await db.execute(select(func.count(Announcement.id)))).scalar_one()
    df_cnt = (await db.execute(select(func.count(DynamicForm.id)))).scalar_one()
    df_resp_cnt = (await db.execute(select(func.count(DynamicFormResponse.id)))).scalar_one()
    fb_cnt = (await db.execute(select(func.count(FeedbackForm.id)))).scalar_one()
    fb_resp_cnt = (await db.execute(select(func.count(FeedbackResponse.id)))).scalar_one()
    total_pts = (await db.execute(select(func.coalesce(func.sum(StudentPointsLedger.points), 0)))).scalar_one()

    return DashboardSummaryOut(
        total_faculty=int(user_counts.faculty_cnt or 0),
        total_students=int(user_counts.student_cnt or 0),
        total_events=int(event_counts.total or 0),
        events_breakdown={
            "planned": int(event_counts.planned or 0),
            "ongoing": int(event_counts.ongoing or 0),
            "completed": int(event_counts.completed or 0)
        },
        total_tasks=int(task_counts.total or 0),
        tasks_breakdown={
            "pending": int(task_counts.pending or 0),
            "submitted": int(task_counts.submitted or 0),
            "approved": int(task_counts.approved or 0),
            "declined": int(task_counts.declined or 0)
        },
        total_queries=int(query_counts.total or 0),
        queries_breakdown={
            "open": int(query_counts.open or 0),
            "closed": int(query_counts.closed or 0)
        },
        total_announcements=int(ann_cnt or 0),
        total_dynamic_forms=int(df_cnt or 0),
        total_form_responses=int(df_resp_cnt or 0),
        total_feedback_forms=int(fb_cnt or 0),
        total_feedback_responses=int(fb_resp_cnt or 0),
        total_student_points_awarded=int(total_pts or 0)
    )

@router.get("/activity", response_model=List[AuditLogOut])
@router.get("/recent-activity", response_model=List[AuditLogOut])
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
