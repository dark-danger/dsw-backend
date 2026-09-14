import uuid
from datetime import datetime, timezone
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.core.deps import get_current_user, require_role
from app.core.security import get_password_hash
from app.models.all_models import User, UserRole, Club, ClubTask
from app.schemas.schemas import (
    ClubCreate, ClubUpdate, ClubOut, ClubMemberSchema,
    ClubTaskCreate, ClubTaskSubmissionPayload, ClubTaskReviewPayload,
    ClubTaskOut, ClubRankingOut, UserOut
)
from app.core.cache import ttl_cache

router = APIRouter(prefix="/api/clubs", tags=["Student Clubs & Leaderboard"])

def utc_now():
    return datetime.now(timezone.utc)

def build_club_out(c: Club) -> ClubOut:
    tasks = c.tasks if hasattr(c, "tasks") and c.tasks else []
    total = len(tasks)
    completed = sum(1 for t in tasks if t.status == "approved")

    coordinator_out = None
    if c.faculty_coordinator:
        coordinator_out = UserOut.model_validate(c.faculty_coordinator)

    return ClubOut(
        id=c.id,
        name=c.name,
        description=c.description,
        category=c.category or "Technical",
        faculty_id=c.faculty_id,
        faculty_coordinator=coordinator_out,
        kras=c.kras,
        roles_schema=c.roles_schema or [],
        student_members=c.student_members or [],
        total_points=c.total_points or 0,
        is_active=c.is_active,
        created_by=c.created_by,
        created_at=c.created_at,
        tasks_count=total,
        completed_tasks_count=completed
    )

def build_club_task_out(t: ClubTask) -> ClubTaskOut:
    submitter_name = t.submitter.name if t.submitter else None
    club_name = t.club.name if t.club else None
    return ClubTaskOut(
        id=t.id,
        club_id=t.club_id,
        club_name=club_name,
        title=t.title,
        description=t.description,
        points_reward=t.points_reward,
        start_date=t.start_date if hasattr(t, "start_date") else None,
        due_date=t.due_date,
        status=t.status,
        submission_text=t.submission_text,
        file_url=t.file_url,
        submitted_at=t.submitted_at,
        submitted_by=t.submitted_by,
        submitter_name=submitter_name,
        reviewed_by=t.reviewed_by,
        review_remarks=t.review_remarks,
        reviewed_at=t.reviewed_at,
        created_at=t.created_at
    )


# 1. LIST CLUBS
@router.get("", response_model=List[ClubOut])
async def list_clubs(
    category: Optional[str] = None,
    search: Optional[str] = None,
    faculty_id: Optional[int] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    query = select(Club).options(
        selectinload(Club.faculty_coordinator),
        selectinload(Club.tasks)
    ).where(Club.is_active == True)

    if category and category != "All":
        query = query.where(Club.category == category)
    if search:
        query = query.where(Club.name.ilike(f"%{search}%"))
    if faculty_id:
        query = query.where(Club.faculty_id == faculty_id)

    result = await db.execute(query.order_by(Club.name.asc()))
    clubs = result.scalars().all()
    return [build_club_out(c) for c in clubs]


# 2. CLUB LEADERBOARD RANKINGS (Must be defined before /{club_id} route to avoid path collision)
@router.get("/leaderboard/rankings", response_model=List[ClubRankingOut])
async def get_club_leaderboard(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    cached_rankings = ttl_cache.get("lb_clubs_rankings")
    if cached_rankings:
        return cached_rankings

    query = select(Club).options(
        selectinload(Club.faculty_coordinator),
        selectinload(Club.tasks)
    ).where(Club.is_active == True)

    result = await db.execute(query)
    clubs = result.scalars().all()

    items = []
    for c in clubs:
        tasks = c.tasks if hasattr(c, "tasks") and c.tasks else []
        completed = sum(1 for t in tasks if t.status == "approved")
        members = c.student_members if isinstance(c.student_members, list) else []
        items.append({
            "club_id": c.id,
            "name": c.name,
            "category": c.category or "General",
            "faculty_name": c.faculty_coordinator.name if c.faculty_coordinator else "Unassigned",
            "total_points": c.total_points or 0,
            "tasks_completed": completed,
            "member_count": len(members)
        })

    # Sort descending by total_points, tie-breaker tasks_completed
    items.sort(key=lambda x: (x["total_points"], x["tasks_completed"]), reverse=True)

    rankings = []
    for idx, item in enumerate(items):
        item["rank"] = idx + 1
        rankings.append(ClubRankingOut(**item))

    ttl_cache.set("lb_clubs_rankings", rankings, ttl=60)
    return rankings


# 3. CREATE CLUB (Admin only)
@router.post("", response_model=ClubOut)
async def create_club(
    payload: ClubCreate,
    current_user: User = Depends(require_role([UserRole.super_admin])),
    db: AsyncSession = Depends(get_db)
):
    # Verify faculty coordinator exists if provided
    if payload.faculty_id:
        f_res = await db.execute(select(User).where(User.id == payload.faculty_id))
        faculty = f_res.scalar_one_or_none()
        if not faculty:
            raise HTTPException(status_code=404, detail="Faculty coordinator not found")

    club = Club(
        name=payload.name,
        description=payload.description,
        category=payload.category or "Technical",
        faculty_id=payload.faculty_id,
        kras=payload.kras,
        roles_schema=payload.roles_schema or [
            "President", "Vice President", "General Secretary", "Technical Lead", "Events Lead", "PR & Outreach Head"
        ],
        student_members=[],
        total_points=0,
        is_active=True,
        created_by=current_user.id
    )
    db.add(club)
    await db.commit()

    res = await db.execute(
        select(Club).options(selectinload(Club.faculty_coordinator), selectinload(Club.tasks)).where(Club.id == club.id)
    )
    created = res.scalar_one()
    return build_club_out(created)


# 4. GET CLUB DETAIL
@router.get("/{club_id}", response_model=ClubOut)
async def get_club_detail(
    club_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(Club).options(
            selectinload(Club.faculty_coordinator),
            selectinload(Club.tasks)
        ).where(Club.id == club_id)
    )
    club = result.scalar_one_or_none()
    if not club:
        raise HTTPException(status_code=404, detail="Club not found")
    return build_club_out(club)


# 5. UPDATE CLUB (Admin or assigned Faculty Coordinator)
@router.patch("/{club_id}", response_model=ClubOut)
async def update_club(
    club_id: int,
    payload: ClubUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(Club).options(
            selectinload(Club.faculty_coordinator),
            selectinload(Club.tasks)
        ).where(Club.id == club_id)
    )
    club = result.scalar_one_or_none()
    if not club:
        raise HTTPException(status_code=404, detail="Club not found")

    # Authorization: Super Admin or assigned Faculty Coordinator
    if current_user.role != UserRole.super_admin and club.faculty_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to update this club")

    for k, v in payload.model_dump(exclude_unset=True).items():
        if k == "student_members" and v is not None:
            # Convert models to dicts
            setattr(club, k, [m if isinstance(m, dict) else m.model_dump() for m in v])
        else:
            setattr(club, k, v)

    await db.commit()
    await db.refresh(club)
    return build_club_out(club)


# 6. DELETE CLUB (Admin only)
@router.delete("/{club_id}")
async def delete_club(
    club_id: int,
    current_user: User = Depends(require_role([UserRole.super_admin])),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Club).where(Club.id == club_id))
    club = result.scalar_one_or_none()
    if not club:
        raise HTTPException(status_code=404, detail="Club not found")

    await db.delete(club)
    await db.commit()
    return {"message": "Club deleted successfully"}


# 7. ADD STUDENT MEMBER & AUTO-PROVISION LOGIN (Admin or assigned Faculty Coordinator)
@router.post("/{club_id}/members", response_model=ClubOut)
async def add_club_member(
    club_id: int,
    payload: ClubMemberSchema,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(Club).options(
            selectinload(Club.faculty_coordinator),
            selectinload(Club.tasks)
        ).where(Club.id == club_id)
    )
    club = result.scalar_one_or_none()
    if not club:
        raise HTTPException(status_code=404, detail="Club not found")

    # Only assigned Faculty Coordinator or Super Admin can assign members & roles
    if current_user.role != UserRole.super_admin and club.faculty_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to manage members of this club")

    # 1. Auto-provision or link Student Portal User account
    clean_email = payload.email.strip().lower()
    s_res = await db.execute(select(User).where(User.email == clean_email))
    student_user = s_res.scalar_one_or_none()

    if not student_user and payload.roll_number:
        clean_roll = payload.roll_number.strip()
        s_res2 = await db.execute(select(User).where(User.roll_number == clean_roll))
        student_user = s_res2.scalar_one_or_none()

    raw_password = (payload.password or "President@123").strip()
    if not student_user:
        # Create student user account
        student_user = User(
            name=payload.name.strip(),
            email=clean_email,
            phone=payload.phone,
            roll_number=payload.roll_number,
            course_branch=payload.branch,
            year=payload.semester,
            role=UserRole.student,
            password_hash=get_password_hash(raw_password),
            is_active=True,
            must_change_password=False
        )
        db.add(student_user)
        await db.flush()
    else:
        # Update details if not present
        if payload.roll_number and not student_user.roll_number:
            student_user.roll_number = payload.roll_number
        if payload.branch and not student_user.course_branch:
            student_user.course_branch = payload.branch
        if payload.semester and not student_user.year:
            student_user.year = payload.semester
        if payload.phone and not student_user.phone:
            student_user.phone = payload.phone
        if payload.password and payload.password.strip():
            student_user.password_hash = get_password_hash(payload.password.strip())

    # 2. Append to club student_members JSON
    members = list(club.student_members or [])
    new_mem = payload.model_dump()
    if not new_mem.get("id"):
        new_mem["id"] = f"mem_{uuid.uuid4().hex[:8]}"
    new_mem["student_id"] = student_user.id

    # Avoid duplicate additions of same student email in this club
    members = [m for m in members if m.get("email", "").lower() != clean_email]
    members.append(new_mem)
    club.student_members = members

    await db.commit()
    await db.refresh(club)
    return build_club_out(club)


# 8. REMOVE STUDENT MEMBER (Admin or assigned Faculty Coordinator)
@router.delete("/{club_id}/members/{member_id}", response_model=ClubOut)
async def remove_club_member(
    club_id: int,
    member_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(Club).options(
            selectinload(Club.faculty_coordinator),
            selectinload(Club.tasks)
        ).where(Club.id == club_id)
    )
    club = result.scalar_one_or_none()
    if not club:
        raise HTTPException(status_code=404, detail="Club not found")

    if current_user.role != UserRole.super_admin and club.faculty_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to manage members of this club")

    members = list(club.student_members or [])
    updated_members = [m for m in members if str(m.get("id")) != str(member_id)]
    club.student_members = updated_members

    await db.commit()
    await db.refresh(club)
    return build_club_out(club)


# 9. GET CLUB TASKS
@router.get("/{club_id}/tasks", response_model=List[ClubTaskOut])
async def get_club_tasks(
    club_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(ClubTask)
        .options(selectinload(ClubTask.submitter), selectinload(ClubTask.club))
        .where(ClubTask.club_id == club_id)
        .order_by(ClubTask.created_at.desc())
    )
    tasks = result.scalars().all()
    return [build_club_task_out(t) for t in tasks]


# 10. CREATE CLUB TASK (Admin or assigned Faculty Coordinator)
@router.post("/{club_id}/tasks", response_model=ClubTaskOut)
async def create_club_task(
    club_id: int,
    payload: ClubTaskCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    c_res = await db.execute(select(Club).where(Club.id == club_id))
    club = c_res.scalar_one_or_none()
    if not club:
        raise HTTPException(status_code=404, detail="Club not found")

    # Only super admin or the assigned faculty coordinator can assign tasks to the club
    if current_user.role != UserRole.super_admin and club.faculty_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to assign tasks for this club")

    task = ClubTask(
        club_id=club_id,
        title=payload.title,
        description=payload.description,
        points_reward=payload.points_reward or 20,
        start_date=payload.start_date,
        due_date=payload.due_date,
        status="pending",
        created_by=current_user.id
    )
    db.add(task)
    await db.commit()

    res = await db.execute(
        select(ClubTask).options(selectinload(ClubTask.submitter), selectinload(ClubTask.club)).where(ClubTask.id == task.id)
    )
    created = res.scalar_one()
    return build_club_task_out(created)


# 11. SUBMIT CLUB TASK PROOF (Students / Club Officers)
@router.post("/tasks/{task_id}/submit", response_model=ClubTaskOut)
async def submit_club_task(
    task_id: int,
    payload: ClubTaskSubmissionPayload,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(ClubTask).options(selectinload(ClubTask.submitter), selectinload(ClubTask.club)).where(ClubTask.id == task_id)
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Club task not found")

    task.submission_text = payload.submission_text
    task.file_url = payload.file_url
    task.submitted_at = utc_now()
    task.submitted_by = current_user.id
    task.status = "submitted"

    await db.commit()
    await db.refresh(task)
    return build_club_task_out(task)


# 12. APPROVE CLUB TASK (Admin or assigned Faculty Coordinator) -> Awards Points to Club!
@router.post("/tasks/{task_id}/approve", response_model=ClubTaskOut)
async def approve_club_task(
    task_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(ClubTask).options(selectinload(ClubTask.submitter), selectinload(ClubTask.club)).where(ClubTask.id == task_id)
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Club task not found")

    c_res = await db.execute(select(Club).where(Club.id == task.club_id))
    club = c_res.scalar_one_or_none()
    if not club:
        raise HTTPException(status_code=404, detail="Associated club not found")

    # Super admin or assigned faculty coordinator can approve
    if current_user.role != UserRole.super_admin and club.faculty_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to approve tasks for this club")

    task.status = "approved"
    task.reviewed_by = current_user.id
    task.reviewed_at = utc_now()

    # Award points to the club
    club.total_points = (club.total_points or 0) + (task.points_reward or 20)

    await db.commit()
    await db.refresh(task)
    return build_club_task_out(task)


# 13. DECLINE CLUB TASK (Admin or assigned Faculty Coordinator)
@router.post("/tasks/{task_id}/decline", response_model=ClubTaskOut)
async def decline_club_task(
    task_id: int,
    payload: ClubTaskReviewPayload,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(ClubTask).options(selectinload(ClubTask.submitter), selectinload(ClubTask.club)).where(ClubTask.id == task_id)
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Club task not found")

    c_res = await db.execute(select(Club).where(Club.id == task.club_id))
    club = c_res.scalar_one_or_none()
    if not club:
        raise HTTPException(status_code=404, detail="Associated club not found")

    # Super admin or assigned faculty coordinator can decline
    if current_user.role != UserRole.super_admin and club.faculty_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to decline tasks for this club")

    task.status = "declined"
    task.reviewed_by = current_user.id
    task.review_remarks = payload.review_remarks or "Submission does not meet criteria"
    task.reviewed_at = utc_now()

    await db.commit()
    await db.refresh(task)
    return build_club_task_out(task)
