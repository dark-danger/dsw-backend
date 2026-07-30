from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import List
from app.database import get_db
from app.core.deps import get_current_user
from app.models.all_models import User, UserRole, Task, TaskStatus, FacultyPerformanceLedger
from app.schemas.schemas import StaffRankingOut

router = APIRouter(prefix="/api/leaderboard/staff", tags=["Staff Leaderboard"])

def _get_status_str(status_val) -> str:
    if hasattr(status_val, "value"):
        return str(status_val.value)
    return str(status_val)

@router.get("/rankings", response_model=List[StaffRankingOut])
async def get_staff_rankings(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    faculty_res = await db.execute(select(User).where(User.role == UserRole.faculty, User.is_active == True))
    faculty_members = faculty_res.scalars().all()

    rankings = []
    for f in faculty_members:
        # SUM score_delta from ledger
        score_res = await db.execute(
            select(func.coalesce(func.sum(FacultyPerformanceLedger.score_delta), 0)).where(
                FacultyPerformanceLedger.faculty_id == f.id
            )
        )
        total_score = score_res.scalar_one()

        # Task counts
        tasks_res = await db.execute(select(Task).where(Task.assigned_to == f.id))
        f_tasks = tasks_res.scalars().all()

        approved = sum(1 for t in f_tasks if _get_status_str(t.status) == "approved")
        pending = sum(1 for t in f_tasks if _get_status_str(t.status) in ["pending", "in_progress", "submitted"])
        declined = sum(1 for t in f_tasks if _get_status_str(t.status) == "declined")

        rankings.append({
            "faculty_id": f.id,
            "name": f.name,
            "department": f.department or "DSW",
            "designation": f.designation or "Faculty",
            "total_score": total_score,
            "tasks_approved": approved,
            "tasks_pending": pending,
            "tasks_declined": declined
        })

    # Sort descending by total_score, tie breaker by tasks_approved
    rankings.sort(key=lambda r: (r["total_score"], r["tasks_approved"]), reverse=True)

    result = []
    for idx, r in enumerate(rankings):
        r["rank"] = idx + 1
        result.append(StaffRankingOut(**r))

    return result
