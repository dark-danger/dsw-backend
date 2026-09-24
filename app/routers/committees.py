import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from typing import List, Optional
from app.database import get_db
from app.core.deps import get_current_user, require_role
from app.core.security import get_password_hash
from app.models.all_models import User, UserRole, Event, CoreCommittee
from app.schemas.schemas import CoreCommitteeCreate, CoreCommitteeOut
from app.services.notification_service import create_notification, log_audit

router = APIRouter(prefix="/api/committees", tags=["Core Committees"])

@router.post("", response_model=CoreCommitteeOut)
async def create_core_committee(
    payload: CoreCommitteeCreate,
    current_user: User = Depends(require_role([UserRole.super_admin, UserRole.faculty])),
    db: AsyncSession = Depends(get_db)
):
    # Verify Event
    ev_res = await db.execute(select(Event).where(Event.id == payload.event_id))
    event = ev_res.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=400, detail="Linked Event not found")

    # Verify Faculty In-charge
    fac_res = await db.execute(select(User).where(User.id == payload.faculty_id, User.role == UserRole.faculty))
    faculty_mentor = fac_res.scalar_one_or_none()
    if not faculty_mentor:
        raise HTTPException(status_code=400, detail="Selected Faculty Coordinator not found")

    enriched_student_roles = []
    
    for item in payload.student_roles:
        is_president = (
            (item.role_name and "president" in item.role_name.lower()) or 
            bool(getattr(item, "is_president", False)) or 
            bool(item.password and item.password.strip())
        )

        student_user = None

        # If existing student_id passed, check database
        if item.student_id:
            stu_res = await db.execute(select(User).where(User.id == item.student_id))
            student_user = stu_res.scalar_one_or_none()

        clean_email = (item.email or "").strip().lower()
        clean_roll = (item.student_roll_no or "").strip()

        # ONLY For President: Provision or update Portal User Login Account
        if is_president:
            if not clean_email and not clean_roll:
                clean_email = f"president_{uuid.uuid4().hex[:6]}@geeta.edu.in"

            if not student_user and clean_email:
                s_res = await db.execute(select(User).where(User.email == clean_email))
                student_user = s_res.scalar_one_or_none()

            if not student_user and clean_roll:
                s_res2 = await db.execute(select(User).where(User.roll_number == clean_roll))
                student_user = s_res2.scalar_one_or_none()

            raw_password = (item.password or "President@123").strip()

            if not student_user:
                # Create President Login Account on Portal
                student_user = User(
                    name=(item.student_name or "Club President").strip(),
                    email=clean_email,
                    phone=item.phone,
                    roll_number=item.student_roll_no,
                    department=item.department,
                    course_branch=item.department,
                    year=item.semester,
                    role=UserRole.student,
                    password_hash=get_password_hash(raw_password),
                    is_active=True,
                    must_change_password=False
                )
                db.add(student_user)
                await db.flush()
            else:
                # Update details if provided
                if item.student_roll_no:
                    student_user.roll_number = item.student_roll_no
                if item.department:
                    student_user.department = item.department
                    student_user.course_branch = item.department
                if item.semester:
                    student_user.year = item.semester
                if item.phone:
                    student_user.phone = item.phone
                if item.password and item.password.strip():
                    student_user.password_hash = get_password_hash(item.password.strip())
                await db.flush()

        # For regular student roles: NO user login account is created, only details are saved
        stu_name = item.student_name or (student_user.name if student_user else "Student Member")
        stu_roll = item.student_roll_no or (student_user.roll_number if student_user else "N/A")
        stu_dept = item.department or (student_user.course_branch or student_user.department if student_user else "General")
        stu_sem = getattr(item, "semester", None) or (student_user.year if student_user else "")
        stu_email = item.email or (student_user.email if student_user else "")
        stu_phone = item.phone or (student_user.phone if student_user else "")

        enriched_item = {
            "role_name": item.role_name,
            "student_id": student_user.id if student_user else None,
            "student_name": stu_name,
            "student_roll_no": stu_roll,
            "department": stu_dept,
            "semester": stu_sem,
            "email": stu_email,
            "phone": stu_phone,
            "is_president": is_president,
            "has_account": bool(student_user is not None),
            "responsibilities": item.responsibilities or ""
        }
        enriched_student_roles.append(enriched_item)

        # Notify student if portal user account exists
        if student_user:
            await create_notification(
                db,
                title="Appointed to Core Committee 🎉",
                body=f"Congratulations! You have been appointed as '{item.role_name}' in the Core Committee for '{event.title}'.",
                type="committee_appointment",
                user_id=student_user.id,
                link="/student/committees"
            )

    committee = CoreCommittee(
        title=payload.title,
        event_id=payload.event_id,
        event_date=payload.event_date or (event.start_date.strftime("%Y-%m-%d") if event.start_date else "TBA"),
        faculty_id=payload.faculty_id,
        description=payload.description,
        student_roles=enriched_student_roles,
        created_by=current_user.id
    )
    db.add(committee)
    await db.commit()
    await db.refresh(committee)

    await log_audit(db, action="CREATE_CORE_COMMITTEE", entity_type="core_committee", actor_id=current_user.id, entity_id=committee.id, meta={"title": committee.title, "event": event.title})
    await db.commit()

    return CoreCommitteeOut(
        id=committee.id,
        title=committee.title,
        event_id=committee.event_id,
        event_title=event.title,
        event_date=committee.event_date,
        faculty_id=committee.faculty_id,
        faculty_name=faculty_mentor.name,
        description=committee.description,
        student_roles=committee.student_roles,
        created_by=committee.created_by,
        creator_name=current_user.name,
        created_at=committee.created_at
    )

@router.get("", response_model=List[CoreCommitteeOut])
async def list_core_committees(
    event_id: Optional[int] = None,
    faculty_id: Optional[int] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    query = select(CoreCommittee).options(selectinload(CoreCommittee.event), selectinload(CoreCommittee.faculty_mentor), selectinload(CoreCommittee.creator))
    if event_id:
        query = query.where(CoreCommittee.event_id == event_id)
    if faculty_id:
        query = query.where(CoreCommittee.faculty_id == faculty_id)

    result = await db.execute(query.order_by(CoreCommittee.created_at.desc()))
    committees = result.scalars().all()

    out = []
    for c in committees:
        out.append(CoreCommitteeOut(
            id=c.id,
            title=c.title,
            event_id=c.event_id,
            event_title=c.event.title if c.event else "N/A",
            event_date=c.event_date,
            faculty_id=c.faculty_id,
            faculty_name=c.faculty_mentor.name if c.faculty_mentor else "N/A",
            description=c.description,
            student_roles=c.student_roles,
            created_by=c.created_by,
            creator_name=c.creator.name if c.creator else "DSW Office",
            created_at=c.created_at
        ))
    return out

@router.get("/{committee_id}", response_model=CoreCommitteeOut)
async def get_core_committee(
    committee_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(CoreCommittee)
        .options(selectinload(CoreCommittee.event), selectinload(CoreCommittee.faculty_mentor), selectinload(CoreCommittee.creator))
        .where(CoreCommittee.id == committee_id)
    )
    c = result.scalar_one_or_none()
    if not c:
        raise HTTPException(status_code=404, detail="Core Committee not found")

    return CoreCommitteeOut(
        id=c.id,
        title=c.title,
        event_id=c.event_id,
        event_title=c.event.title if c.event else "N/A",
        event_date=c.event_date,
        faculty_id=c.faculty_id,
        faculty_name=c.faculty_mentor.name if c.faculty_mentor else "N/A",
        description=c.description,
        student_roles=c.student_roles,
        created_by=c.created_by,
        creator_name=c.creator.name if c.creator else "DSW Office",
        created_at=c.created_at
    )

@router.delete("/{committee_id}")
async def delete_core_committee(
    committee_id: int,
    current_user: User = Depends(require_role([UserRole.super_admin, UserRole.faculty])),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(CoreCommittee).where(CoreCommittee.id == committee_id))
    c = result.scalar_one_or_none()
    if not c:
        raise HTTPException(status_code=404, detail="Core Committee not found")

    if current_user.role == UserRole.faculty and c.created_by != current_user.id:
        raise HTTPException(status_code=403, detail="You can only delete committees created by you")

    await db.delete(c)
    await db.commit()
    return {"message": "Core Committee deleted successfully"}
