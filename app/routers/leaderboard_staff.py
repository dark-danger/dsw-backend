from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, case
from typing import List
from app.database import get_db
from app.core.deps import get_current_user
from app.models.all_models import User, UserRole, Task, TaskStatus, FacultyPerformanceLedger
from app.schemas.schemas import StaffRankingOut

router = APIRouter(prefix="/api/leaderboard/staff", tags=["Staff Leaderboard"])

@router.get("/rankings", response_model=List[StaffRankingOut])
async def get_staff_rankings(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    faculty_res = await db.execute(
        select(User).where(User.role == UserRole.faculty, User.is_active == True).order_by(User.name)
    )
    faculty_members = faculty_res.scalars().all()
    if not faculty_members:
        return []

    # Aggregated performance scores in a single query
    scores_res = await db.execute(
        select(
            FacultyPerformanceLedger.faculty_id,
            func.coalesce(func.sum(FacultyPerformanceLedger.score_delta), 0).label("total_score")
        )
        .group_by(FacultyPerformanceLedger.faculty_id)
    )
    scores_map = {row.faculty_id: int(row.total_score or 0) for row in scores_res.all()}

    # Aggregated task counts in a single query
    tasks_res = await db.execute(
        select(
            Task.assigned_to,
            func.count(case((Task.status == TaskStatus.approved, 1))).label("approved"),
            func.count(case((Task.status.in_([TaskStatus.pending, TaskStatus.in_progress, TaskStatus.submitted]), 1))).label("pending"),
            func.count(case((Task.status == TaskStatus.declined, 1))).label("declined")
        )
        .where(Task.assigned_to.is_not(None))
        .group_by(Task.assigned_to)
    )
    tasks_map = {
        row.assigned_to: {
            "approved": int(row.approved or 0),
            "pending": int(row.pending or 0),
            "declined": int(row.declined or 0)
        }
        for row in tasks_res.all()
    }

    rankings = []
    for f in faculty_members:
        t_counts = tasks_map.get(f.id, {"approved": 0, "pending": 0, "declined": 0})
        rankings.append({
            "faculty_id": f.id,
            "name": f.name,
            "department": f.department or "DSW",
            "designation": f.designation or "Faculty",
            "total_score": scores_map.get(f.id, 0),
            "tasks_approved": t_counts["approved"],
            "tasks_pending": t_counts["pending"],
            "tasks_declined": t_counts["declined"]
        })

    # Sort descending by total_score, tie breaker by tasks_approved
    rankings.sort(key=lambda r: (r["total_score"], r["tasks_approved"]), reverse=True)

    result = []
    for idx, r in enumerate(rankings):
        r["rank"] = idx + 1
        result.append(StaffRankingOut(**r))

    return result

