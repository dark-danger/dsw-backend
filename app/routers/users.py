from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, delete, update
from typing import List, Optional
from datetime import datetime, timezone, timedelta

from app.database import get_db
from app.core.security import get_password_hash
from app.core.deps import require_role, get_current_user
from app.models.all_models import (
    User,
    UserRole,
    Task,
    Event,
    QueryItem,
    FacultyPerformanceLedger,
    StudentPointsLedger,
    LeaderboardTaskSubmission,
    AnnouncementReaction,
    Notification,
    EmailConnection,
)
from app.schemas.schemas import (
    UserOut,
    FacultyCreate,
    FacultyUpdate,
    StudentCreate,
    StudentImportRow,
    FacultyStatsOut,
    PeriodStats,
)
from app.services.notification_service import log_audit

router = APIRouter(prefix="/api/users", tags=["Users & Faculty"])


# --- FACULTY MANAGEMENT ---
@router.post("/faculty", response_model=UserOut)
async def create_faculty(
    payload: FacultyCreate,
    current_user: User = Depends(require_role([UserRole.super_admin])),
    db: AsyncSession = Depends(get_db),
):
    clean_email = payload.email.strip().lower()
    clean_emp_id = (payload.employee_id or "").strip()
    pwd = payload.password or "Faculty@123"

    # Check for existing user with this email (case-insensitive)
    existing_res = await db.execute(
        select(User).where(func.lower(User.email) == clean_email)
    )
    existing = existing_res.scalar_one_or_none()

    if existing:
        if existing.is_active:
            raise HTTPException(status_code=400, detail="User with this email already exists")
        else:
            # Reactivate and update previously deleted / deactivated user record
            existing.name = payload.name.strip()
            existing.email = clean_email
            existing.phone = payload.phone
            existing.department = payload.department
            existing.designation = payload.designation
            if clean_emp_id:
                existing.employee_id = clean_emp_id
            existing.role = UserRole.faculty
            existing.password_hash = get_password_hash(pwd)
            existing.must_change_password = True
            existing.is_active = True

            await db.commit()
            await db.refresh(existing)

            await log_audit(
                db,
                action="REACTIVATE_FACULTY",
                entity_type="user",
                actor_id=current_user.id,
                entity_id=existing.id,
                meta={"name": existing.name, "email": existing.email},
            )
            await db.commit()
            return UserOut.model_validate(existing)

    # Check if employee_id is taken by another active user
    if clean_emp_id:
        emp_res = await db.execute(
            select(User).where(User.employee_id == clean_emp_id, User.is_active == True)
        )
        if emp_res.scalar_one_or_none():
            raise HTTPException(
                status_code=400,
                detail=f"Employee ID '{clean_emp_id}' is already assigned to another faculty member",
            )

    faculty = User(
        name=payload.name.strip(),
        email=clean_email,
        phone=payload.phone,
        department=payload.department,
        designation=payload.designation,
        employee_id=clean_emp_id or f"GU-{Date_stamp()}",
        role=UserRole.faculty,
        password_hash=get_password_hash(pwd),
        must_change_password=True,
        is_active=True,
    )
    db.add(faculty)
    await db.commit()
    await db.refresh(faculty)

    await log_audit(
        db,
        action="CREATE_FACULTY",
        entity_type="user",
        actor_id=current_user.id,
        entity_id=faculty.id,
        meta={"name": faculty.name, "email": faculty.email},
    )
    await db.commit()

    return UserOut.model_validate(faculty)


def Date_stamp() -> str:
    return str(int(datetime.now(timezone.utc).timestamp()))[-4:]


@router.get("/faculty", response_model=List[UserOut])
async def list_faculty(
    search: Optional[str] = None,
    department: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(User).where(User.role == UserRole.faculty, User.is_active == True)
    if search:
        s = search.strip()
        query = query.where(
            (User.name.ilike(f"%{s}%"))
            | (User.email.ilike(f"%{s}%"))
            | (User.employee_id.ilike(f"%{s}%"))
        )
    if department:
        query = query.where(User.department == department)

    result = await db.execute(query.order_by(User.name))
    faculty_list = result.scalars().all()
    return [UserOut.model_validate(f) for f in faculty_list]


@router.get("/faculty/{faculty_id}", response_model=UserOut)
async def get_faculty(
    faculty_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(User).where(
            User.id == faculty_id,
            User.role == UserRole.faculty,
            User.is_active == True,
        )
    )
    faculty = result.scalar_one_or_none()
    if not faculty:
        raise HTTPException(status_code=404, detail="Faculty member not found")
    return UserOut.model_validate(faculty)


@router.put("/faculty/{faculty_id}", response_model=UserOut)
async def update_faculty(
    faculty_id: int,
    payload: FacultyUpdate,
    current_user: User = Depends(require_role([UserRole.super_admin])),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(User).where(User.id == faculty_id, User.role == UserRole.faculty)
    )
    faculty = result.scalar_one_or_none()
    if not faculty:
        raise HTTPException(status_code=404, detail="Faculty member not found")

    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(faculty, k, v)

    await db.commit()
    await db.refresh(faculty)
    return UserOut.model_validate(faculty)


@router.delete("/faculty/{faculty_id}")
async def delete_faculty(
    faculty_id: int,
    current_user: User = Depends(require_role([UserRole.super_admin])),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(User).where(User.id == faculty_id, User.role == UserRole.faculty)
    )
    faculty = result.scalar_one_or_none()
    if not faculty:
        raise HTTPException(status_code=404, detail="Faculty member not found")

    fac_name = faculty.name
    fac_email = faculty.email

    try:
        # 1. Nullify / detach non-critical relations
        await db.execute(
            update(Event)
            .where(Event.coordinator_id == faculty_id)
            .values(coordinator_id=None)
        )
        await db.execute(
            update(QueryItem)
            .where(QueryItem.target_faculty_id == faculty_id)
            .values(target_faculty_id=None, target_faculty_name=None)
        )
        await db.execute(
            update(Task)
            .where(Task.assigned_to == faculty_id)
            .values(assigned_to=current_user.id)
        )
        await db.execute(
            update(Task)
            .where(Task.assigned_by == faculty_id)
            .values(assigned_by=current_user.id)
        )

        # 2. Clean up user-specific personal records
        await db.execute(
            delete(FacultyPerformanceLedger).where(
                FacultyPerformanceLedger.faculty_id == faculty_id
            )
        )
        await db.execute(
            delete(EmailConnection).where(EmailConnection.user_id == faculty_id)
        )
        await db.execute(delete(Notification).where(Notification.user_id == faculty_id))
        await db.execute(
            delete(AnnouncementReaction).where(
                AnnouncementReaction.user_id == faculty_id
            )
        )

        # 3. Permanently delete the user row
        await db.delete(faculty)
        await db.commit()

        await log_audit(
            db,
            action="DELETE_FACULTY",
            entity_type="user",
            actor_id=current_user.id,
            entity_id=faculty_id,
            meta={"name": fac_name, "email": fac_email},
        )
        await db.commit()
        return {"message": "Faculty member deleted successfully"}
    except Exception as e:
        print(f"[Delete Faculty Exception] {e}. Falling back to clean deactivation.")
        await db.rollback()

        # Fallback: soft deactivate & free up unique email/employee_id constraints
        res = await db.execute(select(User).where(User.id == faculty_id))
        fac = res.scalar_one_or_none()
        if fac:
            fac.is_active = False
            stamp = int(datetime.now(timezone.utc).timestamp())
            fac.email = f"deleted_{stamp}_{fac.email}"
            if fac.employee_id:
                fac.employee_id = f"del_{stamp}_{fac.employee_id}"
            await db.commit()
        return {"message": "Faculty member removed and deactivated"}


def _get_status_str(status_val) -> str:
    if hasattr(status_val, "value"):
        return str(status_val.value)
    return str(status_val)


def _calc_stats(tasks):
    total = len(tasks)
    approved = sum(1 for t in tasks if _get_status_str(t.status) == "approved")
    pending = sum(
        1 for t in tasks if _get_status_str(t.status) in ["pending", "in_progress", "submitted"]
    )
    declined = sum(1 for t in tasks if _get_status_str(t.status) == "declined")
    rate = round((approved / total * 100), 1) if total > 0 else 0.0
    return total, approved, pending, declined, rate


@router.get("/faculty/{faculty_id}/stats", response_model=FacultyStatsOut)
async def get_faculty_stats(
    faculty_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.id == faculty_id))
    faculty = result.scalar_one_or_none()
    if not faculty:
        raise HTTPException(status_code=404, detail="Faculty member not found")

    tasks_res = await db.execute(select(Task).where(Task.assigned_to == faculty_id))
    all_tasks = tasks_res.scalars().all()

    now = datetime.now(timezone.utc)

    # 1. Weekly Window (Last 7 days)
    week_start = now - timedelta(days=7)
    weekly_tasks = [
        t
        for t in all_tasks
        if t.created_at
        and (
            t.created_at.replace(tzinfo=timezone.utc)
            if t.created_at.tzinfo is None
            else t.created_at
        )
        >= week_start
    ]
    w_tot, w_app, w_pen, w_dec, w_rate = _calc_stats(weekly_tasks)

    w_score_res = await db.execute(
        select(func.coalesce(func.sum(FacultyPerformanceLedger.score_delta), 0)).where(
            FacultyPerformanceLedger.faculty_id == faculty_id,
            FacultyPerformanceLedger.created_at >= week_start,
        )
    )
    w_score = w_score_res.scalar_one()

    # 2. Monthly Window (Resets on the 9th of every month)
    if now.day >= 9:
        month_start = datetime(now.year, now.month, 9, 0, 0, 0, tzinfo=timezone.utc)
        if now.month == 12:
            next_reset = datetime(now.year + 1, 1, 9, 0, 0, 0, tzinfo=timezone.utc)
        else:
            next_reset = datetime(now.year, now.month + 1, 9, 0, 0, 0, tzinfo=timezone.utc)
    else:
        if now.month == 1:
            month_start = datetime(now.year - 1, 12, 9, 0, 0, 0, tzinfo=timezone.utc)
        else:
            month_start = datetime(now.year, now.month - 1, 9, 0, 0, 0, tzinfo=timezone.utc)
        next_reset = datetime(now.year, now.month, 9, 0, 0, 0, tzinfo=timezone.utc)

    monthly_tasks = [
        t
        for t in all_tasks
        if t.created_at
        and (
            t.created_at.replace(tzinfo=timezone.utc)
            if t.created_at.tzinfo is None
            else t.created_at
        )
        >= month_start
        and (
            t.created_at.replace(tzinfo=timezone.utc)
            if t.created_at.tzinfo is None
            else t.created_at
        )
        < next_reset
    ]
    m_tot, m_app, m_pen, m_dec, m_rate = _calc_stats(monthly_tasks)

    m_score_res = await db.execute(
        select(func.coalesce(func.sum(FacultyPerformanceLedger.score_delta), 0)).where(
            FacultyPerformanceLedger.faculty_id == faculty_id,
            FacultyPerformanceLedger.created_at >= month_start,
            FacultyPerformanceLedger.created_at < next_reset,
        )
    )
    m_score = m_score_res.scalar_one()

    # 3. All-time stats
    tot, app, pen, dec, rate = _calc_stats(all_tasks)
    score_res = await db.execute(
        select(func.coalesce(func.sum(FacultyPerformanceLedger.score_delta), 0)).where(
            FacultyPerformanceLedger.faculty_id == faculty_id
        )
    )
    all_time_score = score_res.scalar_one()

    weekly_stats = PeriodStats(
        total_assigned=w_tot,
        completed_approved=w_app,
        pending_count=w_pen,
        declined_count=w_dec,
        completion_rate_percentage=w_rate,
        performance_score=w_score,
        period_label=f"Weekly ({week_start.strftime('%d %b')} – {now.strftime('%d %b')})",
    )

    monthly_stats = PeriodStats(
        total_assigned=m_tot,
        completed_approved=m_app,
        pending_count=m_pen,
        declined_count=m_dec,
        completion_rate_percentage=m_rate,
        performance_score=m_score,
        period_label=f"Monthly Cycle ({month_start.strftime('%d %b')} – {next_reset.strftime('%d %b')})",
        reset_date=next_reset.strftime("%d %b %Y"),
    )

    all_time_stats = PeriodStats(
        total_assigned=tot,
        completed_approved=app,
        pending_count=pen,
        declined_count=dec,
        completion_rate_percentage=rate,
        performance_score=all_time_score,
        period_label="All-Time Record",
    )

    return FacultyStatsOut(
        faculty_id=faculty.id,
        faculty_name=faculty.name,
        total_assigned=tot,
        completed_approved=app,
        pending_count=pen,
        declined_count=dec,
        completion_rate_percentage=rate,
        performance_score=all_time_score,
        weekly=weekly_stats,
        monthly=monthly_stats,
        all_time=all_time_stats,
    )


# --- STUDENT MANAGEMENT ---
@router.post("/students", response_model=UserOut)
async def create_student(
    payload: StudentCreate,
    current_user: User = Depends(require_role([UserRole.super_admin])),
    db: AsyncSession = Depends(get_db),
):
    clean_email = payload.email.strip().lower()
    clean_roll = (payload.roll_number or "").strip()
    pwd = payload.password or "Student@123"

    existing_res = await db.execute(
        select(User).where(func.lower(User.email) == clean_email)
    )
    existing = existing_res.scalar_one_or_none()

    if not existing and clean_roll:
        existing_res2 = await db.execute(
            select(User).where(User.roll_number == clean_roll)
        )
        existing = existing_res2.scalar_one_or_none()

    if existing:
        if existing.is_active:
            raise HTTPException(
                status_code=400,
                detail="Student with this email or roll number already exists",
            )
        else:
            # Reactivate
            existing.name = payload.name.strip()
            existing.email = clean_email
            existing.roll_number = clean_roll or existing.roll_number
            existing.course_branch = payload.course_branch
            existing.year = payload.year
            existing.phone = payload.phone
            existing.role = UserRole.student
            existing.password_hash = get_password_hash(pwd)
            existing.must_change_password = True
            existing.is_active = True

            await db.commit()
            await db.refresh(existing)
            return UserOut.model_validate(existing)

    student = User(
        name=payload.name.strip(),
        email=clean_email,
        roll_number=clean_roll or None,
        course_branch=payload.course_branch,
        year=payload.year,
        phone=payload.phone,
        role=UserRole.student,
        password_hash=get_password_hash(pwd),
        must_change_password=True,
        is_active=True,
    )
    db.add(student)
    await db.commit()
    await db.refresh(student)
    return UserOut.model_validate(student)


@router.post("/students/bulk-import")
async def bulk_import_students(
    rows: List[StudentImportRow],
    current_user: User = Depends(require_role([UserRole.super_admin])),
    db: AsyncSession = Depends(get_db),
):
    imported_count = 0
    default_pwd_hash = get_password_hash("Student@123")
    for row in rows:
        clean_email = row.email.strip().lower()
        clean_roll = row.roll_number.strip()
        existing = await db.execute(
            select(User).where(
                (func.lower(User.email) == clean_email)
                | (User.roll_number == clean_roll)
            )
        )
        existing_user = existing.scalar_one_or_none()
        if existing_user:
            if not existing_user.is_active:
                existing_user.name = row.name.strip()
                existing_user.email = clean_email
                existing_user.roll_number = clean_roll
                existing_user.course_branch = row.course_branch
                existing_user.year = row.year
                existing_user.phone = row.phone
                existing_user.role = UserRole.student
                existing_user.is_active = True
                existing_user.password_hash = default_pwd_hash
                existing_user.must_change_password = True
                imported_count += 1
            continue

        student = User(
            name=row.name.strip(),
            email=clean_email,
            roll_number=clean_roll,
            course_branch=row.course_branch,
            year=row.year,
            phone=row.phone,
            role=UserRole.student,
            password_hash=default_pwd_hash,
            must_change_password=True,
            is_active=True,
        )
        db.add(student)
        imported_count += 1

    await db.commit()
    return {"message": f"Successfully imported {imported_count} new students"}


@router.get("/students", response_model=List[UserOut])
async def list_students(
    search: Optional[str] = None,
    course_branch: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(User).where(User.role == UserRole.student, User.is_active == True)
    if search:
        s = search.strip()
        query = query.where(
            (User.name.ilike(f"%{s}%"))
            | (User.email.ilike(f"%{s}%"))
            | (User.roll_number.ilike(f"%{s}%"))
        )
    if course_branch:
        query = query.where(User.course_branch == course_branch)

    result = await db.execute(query.order_by(User.name))
    students = result.scalars().all()
    return [UserOut.model_validate(s) for s in students]


@router.delete("/students/{student_id}")
async def delete_student(
    student_id: int,
    current_user: User = Depends(require_role([UserRole.super_admin])),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(User).where(User.id == student_id, User.role == UserRole.student)
    )
    student = result.scalar_one_or_none()
    if not student:
        raise HTTPException(status_code=404, detail="Student record not found")

    stu_name = student.name
    stu_email = student.email

    try:
        # 1. Clean up student-specific references
        await db.execute(
            delete(StudentPointsLedger).where(
                StudentPointsLedger.student_id == student_id
            )
        )
        await db.execute(
            delete(LeaderboardTaskSubmission).where(
                LeaderboardTaskSubmission.student_id == student_id
            )
        )
        await db.execute(delete(Notification).where(Notification.user_id == student_id))
        await db.execute(
            delete(AnnouncementReaction).where(
                AnnouncementReaction.user_id == student_id
            )
        )

        # 2. Permanently delete student user row
        await db.delete(student)
        await db.commit()

        await log_audit(
            db,
            action="DELETE_STUDENT",
            entity_type="user",
            actor_id=current_user.id,
            entity_id=student_id,
            meta={"name": stu_name, "email": stu_email},
        )
        await db.commit()
        return {"message": "Student record deleted successfully"}
    except Exception as e:
        print(f"[Delete Student Exception] {e}. Falling back to clean deactivation.")
        await db.rollback()
        res = await db.execute(select(User).where(User.id == student_id))
        stu = res.scalar_one_or_none()
        if stu:
            stu.is_active = False
            stamp = int(datetime.now(timezone.utc).timestamp())
            stu.email = f"deleted_{stamp}_{stu.email}"
            if stu.roll_number:
                stu.roll_number = f"del_{stamp}_{stu.roll_number}"
            await db.commit()
        return {"message": "Student record removed and deactivated"}


@router.delete("/purge/by-query")
async def purge_user_by_query(
    query: str,
    current_user: User = Depends(require_role([UserRole.super_admin])),
    db: AsyncSession = Depends(get_db),
):
    """
    Super Admin utility to permanently remove any user record matching a search term (e.g. 'monu'),
    cleaning up all foreign key references and freeing up the email/employee ID completely.
    """
    clean_q = query.strip().lower()
    if not clean_q or len(clean_q) < 2:
        raise HTTPException(status_code=400, detail="Query term must be at least 2 characters")

    res = await db.execute(
        select(User).where(
            (func.lower(User.name).ilike(f"%{clean_q}%"))
            | (func.lower(User.email).ilike(f"%{clean_q}%"))
            | (User.employee_id.ilike(f"%{clean_q}%"))
            | (User.roll_number.ilike(f"%{clean_q}%"))
        )
    )
    users_to_delete = res.scalars().all()
    if not users_to_delete:
        return {"message": f"No users found matching query '{query}'", "deleted_count": 0, "users": []}

    deleted_info = []
    for u in users_to_delete:
        u_id = u.id
        u_name = u.name
        u_email = u.email
        u_role = str(u.role)
        try:
            # 1. Nullify / detach references
            await db.execute(update(Event).where(Event.coordinator_id == u_id).values(coordinator_id=None))
            await db.execute(update(QueryItem).where(QueryItem.target_faculty_id == u_id).values(target_faculty_id=None, target_faculty_name=None))
            await db.execute(update(Task).where(Task.assigned_to == u_id).values(assigned_to=current_user.id))
            await db.execute(update(Task).where(Task.assigned_by == u_id).values(assigned_by=current_user.id))
            
            # 2. Delete user-specific rows
            await db.execute(delete(FacultyPerformanceLedger).where(FacultyPerformanceLedger.faculty_id == u_id))
            await db.execute(delete(StudentPointsLedger).where(StudentPointsLedger.student_id == u_id))
            await db.execute(delete(LeaderboardTaskSubmission).where(LeaderboardTaskSubmission.student_id == u_id))
            await db.execute(delete(EmailConnection).where(EmailConnection.user_id == u_id))
            await db.execute(delete(Notification).where(Notification.user_id == u_id))
            await db.execute(delete(AnnouncementReaction).where(AnnouncementReaction.user_id == u_id))
            
            # 3. Permanently delete user
            await db.delete(u)
            await db.commit()
            deleted_info.append({"id": u_id, "name": u_name, "email": u_email, "role": u_role, "status": "permanently_deleted"})
        except Exception as e:
            await db.rollback()
            # Fallback
            res2 = await db.execute(select(User).where(User.id == u_id))
            user_obj = res2.scalar_one_or_none()
            if user_obj:
                stamp = int(datetime.now(timezone.utc).timestamp())
                user_obj.is_active = False
                user_obj.email = f"purged_{stamp}_{user_obj.email}"
                if user_obj.employee_id:
                    user_obj.employee_id = f"purged_{stamp}_{user_obj.employee_id}"
                if user_obj.roll_number:
                    user_obj.roll_number = f"purged_{stamp}_{user_obj.roll_number}"
                await db.commit()
                deleted_info.append({"id": u_id, "name": u_name, "email": u_email, "role": u_role, "status": "deactivated_and_freed"})

    return {
        "message": f"Successfully deleted {len(deleted_info)} matching user(s)",
        "deleted_count": len(deleted_info),
        "users": deleted_info
    }

