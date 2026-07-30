from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from typing import List, Optional
from datetime import datetime, timezone
from app.database import get_db
from app.core.deps import get_current_user, require_role
from app.models.all_models import (
    User, UserRole, LeaderboardTask, LeaderboardTaskSubmission, StudentPointsLedger, SubmissionMode
)
from app.schemas.schemas import (
    LeaderboardTaskCreate, LeaderboardTaskOut, LeaderboardSubmissionCreate,
    LeaderboardSubmissionOut, ManualPointAwardPayload, StudentRankingOut, UserOut
)
from app.services.notification_service import create_notification, log_audit

router = APIRouter(prefix="/api/leaderboard/students", tags=["Student Leaderboard"])

def build_leaderboard_task_out(t: LeaderboardTask, student_id: Optional[int]) -> LeaderboardTaskOut:
    submissions = t.submissions if hasattr(t, "submissions") and t.submissions else []
    my_subs = [s for s in submissions if s.student_id == student_id] if student_id else []
    
    return LeaderboardTaskOut(
        id=t.id,
        title=t.title,
        description=t.description,
        points_value=t.points_value,
        submission_mode=t.submission_mode,
        due_date=t.due_date,
        is_active=t.is_active,
        created_by=t.created_by,
        created_at=t.created_at,
        my_submission_count=len(my_subs),
        my_has_submitted=len(my_subs) > 0
    )

@router.post("/tasks", response_model=LeaderboardTaskOut)
async def create_leaderboard_task(
    payload: LeaderboardTaskCreate,
    current_user: User = Depends(require_role([UserRole.super_admin])),
    db: AsyncSession = Depends(get_db)
):
    task = LeaderboardTask(
        title=payload.title,
        description=payload.description,
        points_value=payload.points_value,
        submission_mode=payload.submission_mode,
        due_date=payload.due_date,
        created_by=current_user.id
    )
    db.add(task)
    await db.commit()

    res = await db.execute(
        select(LeaderboardTask).options(selectinload(LeaderboardTask.submissions)).where(LeaderboardTask.id == task.id)
    )
    created = res.scalar_one()

    await log_audit(db, action="CREATE_LEADERBOARD_TASK", entity_type="leaderboard_task", actor_id=current_user.id, entity_id=task.id)
    await db.commit()

    return build_leaderboard_task_out(created, current_user.id)

@router.get("/tasks", response_model=List[LeaderboardTaskOut])
async def list_leaderboard_tasks(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(LeaderboardTask).options(selectinload(LeaderboardTask.submissions)).where(LeaderboardTask.is_active == True).order_by(LeaderboardTask.created_at.desc())
    )
    tasks = result.scalars().all()
    return [build_leaderboard_task_out(t, current_user.id) for t in tasks]

@router.delete("/tasks/{task_id}")
async def delete_leaderboard_task(
    task_id: int,
    current_user: User = Depends(require_role([UserRole.super_admin])),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(LeaderboardTask).where(LeaderboardTask.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Leaderboard task not found")
        
    await db.delete(task)
    await db.commit()
    return {"message": "Leaderboard task deleted successfully"}


@router.post("/tasks/{task_id}/submit")
async def submit_leaderboard_task(
    task_id: int,
    payload: LeaderboardSubmissionCreate,
    current_user: User = Depends(require_role([UserRole.student])),
    db: AsyncSession = Depends(get_db)
):
    res = await db.execute(
        select(LeaderboardTask).options(selectinload(LeaderboardTask.submissions)).where(LeaderboardTask.id == task_id)
    )
    task = res.scalar_one_or_none()
    if not task or not task.is_active:
        raise HTTPException(status_code=404, detail="Leaderboard task not active or not found")

    # Single submission check
    if task.submission_mode == SubmissionMode.single:
        existing = [s for s in task.submissions if s.student_id == current_user.id]
        if existing:
            raise HTTPException(status_code=400, detail="Single-submission task: You have already submitted for this task.")

    sub = LeaderboardTaskSubmission(
        leaderboard_task_id=task.id,
        student_id=current_user.id,
        submission_text=payload.submission_text,
        file_url=payload.file_url,
        status="pending"
    )
    db.add(sub)
    await db.commit()

    await log_audit(db, action="SUBMIT_LEADERBOARD_TASK", entity_type="leaderboard_task", actor_id=current_user.id, entity_id=task.id)
    await db.commit()

    return {"message": "Leaderboard task proof submitted successfully. Pending DSW review."}

@router.get("/tasks/{task_id}/submissions", response_model=List[LeaderboardSubmissionOut])
async def list_task_submissions(
    task_id: int,
    current_user: User = Depends(require_role([UserRole.super_admin])),
    db: AsyncSession = Depends(get_db)
):
    res = await db.execute(
        select(LeaderboardTaskSubmission)
        .options(selectinload(LeaderboardTaskSubmission.student), selectinload(LeaderboardTaskSubmission.task))
        .where(LeaderboardTaskSubmission.leaderboard_task_id == task_id)
        .order_by(LeaderboardTaskSubmission.submitted_at.desc())
    )
    subs = res.scalars().all()
    out = []
    for s in subs:
        out.append(LeaderboardSubmissionOut(
            id=s.id,
            leaderboard_task_id=s.leaderboard_task_id,
            task_title=s.task.title if s.task else None,
            student_id=s.student_id,
            student=UserOut.model_validate(s.student) if s.student else None,
            submission_text=s.submission_text,
            file_url=s.file_url,
            submitted_at=s.submitted_at,
            status=s.status,
            points_awarded=s.points_awarded,
            reviewed_by=s.reviewed_by,
            reviewed_at=s.reviewed_at,
            rejection_reason=s.rejection_reason
        ))
    return out

@router.get("/submissions/pending", response_model=List[LeaderboardSubmissionOut])
async def list_all_pending_submissions(
    current_user: User = Depends(require_role([UserRole.super_admin])),
    db: AsyncSession = Depends(get_db)
):
    res = await db.execute(
        select(LeaderboardTaskSubmission)
        .options(selectinload(LeaderboardTaskSubmission.student), selectinload(LeaderboardTaskSubmission.task))
        .where(LeaderboardTaskSubmission.status == "pending")
        .order_by(LeaderboardTaskSubmission.submitted_at.desc())
    )
    subs = res.scalars().all()
    out = []
    for s in subs:
        out.append(LeaderboardSubmissionOut(
            id=s.id,
            leaderboard_task_id=s.leaderboard_task_id,
            task_title=s.task.title if s.task else None,
            student_id=s.student_id,
            student=UserOut.model_validate(s.student) if s.student else None,
            submission_text=s.submission_text,
            file_url=s.file_url,
            submitted_at=s.submitted_at,
            status=s.status,
            points_awarded=s.points_awarded,
            reviewed_by=s.reviewed_by,
            reviewed_at=s.reviewed_at,
            rejection_reason=s.rejection_reason
        ))
    return out

@router.post("/submissions/{submission_id}/approve")
async def approve_student_submission(
    submission_id: int,
    custom_points: Optional[int] = None,
    current_user: User = Depends(require_role([UserRole.super_admin])),
    db: AsyncSession = Depends(get_db)
):
    res = await db.execute(
        select(LeaderboardTaskSubmission).options(selectinload(LeaderboardTaskSubmission.task)).where(LeaderboardTaskSubmission.id == submission_id)
    )
    sub = res.scalar_one_or_none()
    if not sub:
        raise HTTPException(status_code=404, detail="Submission not found")

    pts = custom_points if custom_points is not None else sub.task.points_value
    sub.status = "approved"
    sub.points_awarded = pts
    sub.reviewed_by = current_user.id
    sub.reviewed_at = datetime.now(timezone.utc)

    # Insert into StudentPointsLedger
    ledger = StudentPointsLedger(
        student_id=sub.student_id,
        points=pts,
        source_type="task_submission",
        source_id=sub.id,
        reason_note=f"Approved task submission: {sub.task.title}",
        awarded_by=current_user.id
    )
    db.add(ledger)
    await db.commit()

    await create_notification(
        db,
        title="Points Awarded! 🏆",
        body=f"You earned +{pts} points for completing leaderboard task '{sub.task.title}'!",
        type="points_awarded",
        user_id=sub.student_id,
        link="/student/leaderboard"
    )
    await log_audit(db, action="APPROVE_STUDENT_TASK", entity_type="leaderboard_submission", actor_id=current_user.id, entity_id=sub.id, meta={"points": pts})
    await db.commit()

    return {"message": f"Approved and awarded {pts} points to student"}

@router.post("/submissions/{submission_id}/reject")
async def reject_student_submission(
    submission_id: int,
    reason: Optional[str] = "Submission did not meet requirements",
    current_user: User = Depends(require_role([UserRole.super_admin])),
    db: AsyncSession = Depends(get_db)
):
    res = await db.execute(select(LeaderboardTaskSubmission).where(LeaderboardTaskSubmission.id == submission_id))
    sub = res.scalar_one_or_none()
    if not sub:
        raise HTTPException(status_code=404, detail="Submission not found")

    sub.status = "rejected"
    sub.rejection_reason = reason
    sub.reviewed_by = current_user.id
    sub.reviewed_at = datetime.now(timezone.utc)

    await db.commit()
    return {"message": "Submission rejected"}

@router.post("/points/manual-award")
async def manual_award_points(
    payload: ManualPointAwardPayload,
    current_user: User = Depends(require_role([UserRole.super_admin])),
    db: AsyncSession = Depends(get_db)
):
    stu_res = await db.execute(select(User).where(User.id == payload.student_id, User.role == UserRole.student))
    student = stu_res.scalar_one_or_none()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    ledger = StudentPointsLedger(
        student_id=payload.student_id,
        points=payload.points,
        source_type="manual_award",
        reason_note=payload.reason_note,
        awarded_by=current_user.id
    )
    db.add(ledger)
    await db.commit()

    action_word = "awarded" if payload.points >= 0 else "deducted"
    await create_notification(
        db,
        title="Leaderboard Points Update",
        body=f"DSW Admin {action_word} {abs(payload.points)} points. Reason: {payload.reason_note}",
        type="points_awarded",
        user_id=student.id,
        link="/student/leaderboard"
    )
    await log_audit(db, action="MANUAL_AWARD_POINTS", entity_type="student_points", actor_id=current_user.id, entity_id=student.id, meta={"points": payload.points, "reason": payload.reason_note})
    await db.commit()

    return {"message": f"Successfully updated student points by {payload.points}"}

from app.core.deps import get_current_user, get_current_user_optional, require_role

@router.get("/rankings", response_model=List[StudentRankingOut])
async def get_student_rankings(
    current_user: Optional[User] = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db)
):
    # Fetch all active students
    students_res = await db.execute(select(User).where(User.role == UserRole.student, User.is_active == True))
    students = students_res.scalars().all()

    rankings = []
    for s in students:
        # Task points
        t_pts_res = await db.execute(
            select(func.coalesce(func.sum(StudentPointsLedger.points), 0)).where(
                StudentPointsLedger.student_id == s.id,
                StudentPointsLedger.source_type == "task_submission"
            )
        )
        task_pts = t_pts_res.scalar_one()

        # Manual points
        m_pts_res = await db.execute(
            select(func.coalesce(func.sum(StudentPointsLedger.points), 0)).where(
                StudentPointsLedger.student_id == s.id,
                StudentPointsLedger.source_type == "manual_award"
            )
        )
        manual_pts = m_pts_res.scalar_one()

        total = task_pts + manual_pts
        rankings.append({
            "student_id": s.id,
            "name": s.name,
            "roll_number": s.roll_number,
            "course_branch": s.course_branch,
            "year": s.year,
            "total_points": total,
            "task_points": task_pts,
            "manual_points": manual_pts
        })

    # Sort descending by total_points
    rankings.sort(key=lambda r: r["total_points"], reverse=True)

    # Assign ranks
    result = []
    for idx, r in enumerate(rankings):
        r["rank"] = idx + 1
        result.append(StudentRankingOut(**r))

    return result
