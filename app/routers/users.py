from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import List, Optional
from app.database import get_db
from app.core.security import get_password_hash
from app.core.deps import require_role, get_current_user
from app.models.all_models import User, UserRole, Task, TaskStatus, FacultyPerformanceLedger
from app.schemas.schemas import UserOut, FacultyCreate, FacultyUpdate, StudentImportRow, FacultyStatsOut
from app.services.notification_service import log_audit

router = APIRouter(prefix="/api/users", tags=["Users & Faculty"])

# --- FACULTY MANAGEMENT ---
@router.post("/faculty", response_model=UserOut)
async def create_faculty(
    payload: FacultyCreate,
    current_user: User = Depends(require_role([UserRole.super_admin])),
    db: AsyncSession = Depends(get_db)
):
    existing = await db.execute(select(User).where(User.email == payload.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="User with this email already exists")

    pwd = payload.password or "Faculty@123"
    faculty = User(
        name=payload.name,
        email=payload.email,
        phone=payload.phone,
        department=payload.department,
        designation=payload.designation,
        employee_id=payload.employee_id,
        role=UserRole.faculty,
        password_hash=get_password_hash(pwd),
        must_change_password=True
    )
    db.add(faculty)
    await db.commit()
    await db.refresh(faculty)

    await log_audit(db, action="CREATE_FACULTY", entity_type="user", actor_id=current_user.id, entity_id=faculty.id, meta={"name": faculty.name})
    await db.commit()

    return UserOut.model_validate(faculty)

@router.get("/faculty", response_model=List[UserOut])
async def list_faculty(
    search: Optional[str] = None,
    department: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    query = select(User).where(User.role == UserRole.faculty, User.is_active == True)
    if search:
        query = query.where((User.name.ilike(f"%{search}%")) | (User.email.ilike(f"%{search}%")))
    if department:
        query = query.where(User.department == department)
        
    result = await db.execute(query.order_by(User.name))
    faculty_list = result.scalars().all()
    return [UserOut.model_validate(f) for f in faculty_list]

@router.get("/faculty/{faculty_id}", response_model=UserOut)
async def get_faculty(
    faculty_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(User).where(User.id == faculty_id, User.role == UserRole.faculty))
    faculty = result.scalar_one_or_none()
    if not faculty:
        raise HTTPException(status_code=404, detail="Faculty member not found")
    return UserOut.model_validate(faculty)

@router.patch("/faculty/{faculty_id}", response_model=UserOut)
async def update_faculty(
    faculty_id: int,
    payload: FacultyUpdate,
    current_user: User = Depends(require_role([UserRole.super_admin])),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(User).where(User.id == faculty_id))
    faculty = result.scalar_one_or_none()
    if not faculty:
        raise HTTPException(status_code=404, detail="Faculty member not found")
        
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(faculty, k, v)
        
    await db.commit()
    await db.refresh(faculty)
    return UserOut.model_validate(faculty)

@router.delete("/faculty/{faculty_id}")
async def soft_delete_faculty(
    faculty_id: int,
    current_user: User = Depends(require_role([UserRole.super_admin])),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(User).where(User.id == faculty_id))
    faculty = result.scalar_one_or_none()
    if not faculty:
        raise HTTPException(status_code=404, detail="Faculty member not found")
        
    faculty.is_active = False
    await db.commit()
    return {"message": "Faculty deactivated"}

def _get_status_str(status_val) -> str:
    if hasattr(status_val, "value"):
        return str(status_val.value)
    return str(status_val)

@router.get("/faculty/{faculty_id}/stats", response_model=FacultyStatsOut)
async def get_faculty_stats(
    faculty_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(User).where(User.id == faculty_id))
    faculty = result.scalar_one_or_none()
    if not faculty:
        raise HTTPException(status_code=404, detail="Faculty member not found")

    tasks_res = await db.execute(select(Task).where(Task.assigned_to == faculty_id))
    all_tasks = tasks_res.scalars().all()
    
    total_assigned = len(all_tasks)
    approved = sum(1 for t in all_tasks if _get_status_str(t.status) == "approved")
    pending = sum(1 for t in all_tasks if _get_status_str(t.status) in ["pending", "in_progress", "submitted"])
    declined = sum(1 for t in all_tasks if _get_status_str(t.status) == "declined")
    rate = round((approved / total_assigned * 100), 1) if total_assigned > 0 else 0.0

    score_res = await db.execute(
        select(func.coalesce(func.sum(FacultyPerformanceLedger.score_delta), 0)).where(FacultyPerformanceLedger.faculty_id == faculty_id)
    )
    score = score_res.scalar_one()

    return FacultyStatsOut(
        faculty_id=faculty.id,
        faculty_name=faculty.name,
        total_assigned=total_assigned,
        completed_approved=approved,
        pending_count=pending,
        declined_count=declined,
        completion_rate_percentage=rate,
        performance_score=score
    )

# --- STUDENT MANAGEMENT ---
@router.post("/students/bulk-import")
async def bulk_import_students(
    rows: List[StudentImportRow],
    current_user: User = Depends(require_role([UserRole.super_admin])),
    db: AsyncSession = Depends(get_db)
):
    imported_count = 0
    for row in rows:
        existing = await db.execute(select(User).where((User.email == row.email) | (User.roll_number == row.roll_number)))
        if existing.scalar_one_or_none():
            continue
            
        student = User(
            name=row.name,
            email=row.email,
            roll_number=row.roll_number,
            course_branch=row.course_branch,
            year=row.year,
            phone=row.phone,
            role=UserRole.student,
            password_hash=get_password_hash("Student@123"),
            must_change_password=True
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
    db: AsyncSession = Depends(get_db)
):
    query = select(User).where(User.role == UserRole.student, User.is_active == True)
    if search:
        query = query.where(
            (User.name.ilike(f"%{search}%")) |
            (User.email.ilike(f"%{search}%")) |
            (User.roll_number.ilike(f"%{search}%"))
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
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(User).where(User.id == student_id, User.role == UserRole.student))
    student = result.scalar_one_or_none()
    if not student:
        raise HTTPException(status_code=404, detail="Student record not found")
        
    student.is_active = False
    await db.commit()
    return {"message": "Student deactivated"}

