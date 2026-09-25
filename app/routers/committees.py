import uuid
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_, and_, desc
from sqlalchemy.orm import selectinload
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone

from app.database import get_db
from app.core.deps import get_current_user, require_role
from app.core.security import get_password_hash
from app.models.all_models import (
    User, UserRole, Event, CoreCommittee, CommitteeTask, CommitteeReport,
    StudentPointsLedger, Notification, utc_now
)
from app.schemas.schemas import (
    CoreCommitteeCreate, CoreCommitteeUpdate, CoreCommitteeOut,
    CommitteeRoleSchema, CommitteeTaskCreate, CommitteeTaskSubmit,
    CommitteeTaskReview, CommitteeTaskOut, CommitteeReportCreate,
    CommitteeReportOut, CommitteeLeaderboardEntry
)
from app.services.notification_service import create_notification, log_audit

router = APIRouter(prefix="/api/committees", tags=["Core Committees"])


async def build_committee_out(c: CoreCommittee, db: AsyncSession) -> CoreCommitteeOut:
    """Helper to assemble a rich CoreCommitteeOut object with counts and coordinator/president names."""
    # Count tasks
    t_cnt_res = await db.execute(
        select(func.count(CommitteeTask.id)).where(CommitteeTask.committee_id == c.id)
    )
    tasks_count = t_cnt_res.scalar_one() or 0

    p_cnt_res = await db.execute(
        select(func.count(CommitteeTask.id)).where(
            CommitteeTask.committee_id == c.id,
            CommitteeTask.status.in_(["pending", "in_progress", "submitted"])
        )
    )
    pending_tasks_count = p_cnt_res.scalar_one() or 0

    r_cnt_res = await db.execute(
        select(func.count(CommitteeReport.id)).where(CommitteeReport.committee_id == c.id)
    )
    reports_count = r_cnt_res.scalar_one() or 0

    return CoreCommitteeOut(
        id=c.id,
        title=c.title,
        category=c.category or "General",
        event_id=c.event_id,
        event_title=c.event.title if c.event else None,
        event_date=c.event_date,
        faculty_id=c.faculty_id,
        faculty_name=c.faculty_mentor.name if c.faculty_mentor else None,
        faculty_email=c.faculty_mentor.email if c.faculty_mentor else None,
        faculty_phone=c.faculty_mentor.phone if c.faculty_mentor else None,
        president_id=c.president_id,
        president_name=c.president.name if c.president else None,
        president_email=c.president.email if c.president else None,
        description=c.description,
        student_roles=c.student_roles or [],
        total_points=c.total_points or 0,
        tasks_count=tasks_count,
        pending_tasks_count=pending_tasks_count,
        reports_count=reports_count,
        is_active=c.is_active,
        created_by=c.created_by,
        creator_name=c.creator.name if c.creator else "DSW Office",
        created_at=c.created_at
    )


def build_task_out(t: CommitteeTask) -> CommitteeTaskOut:
    return CommitteeTaskOut(
        id=t.id,
        committee_id=t.committee_id,
        committee_title=t.committee.title if t.committee else None,
        title=t.title,
        description=t.description,
        assigned_to=t.assigned_to,
        assignee_name=t.assignee.name if t.assignee else None,
        assignee_roll=t.assignee.roll_number if t.assignee else None,
        assigned_by=t.assigned_by,
        assigner_name=t.assigner.name if t.assigner else "Coordinator",
        points_reward=t.points_reward or 20,
        priority=t.priority or "medium",
        start_date=t.start_date,
        due_date=t.due_date,
        status=t.status or "pending",
        submission_text=t.submission_text,
        file_url=t.file_url,
        file_name=t.file_name,
        submitted_by=t.submitted_by,
        submitter_name=t.submitter.name if t.submitter else None,
        submitted_at=t.submitted_at,
        reviewed_by=t.reviewed_by,
        reviewer_name=t.reviewer.name if t.reviewer else None,
        review_remarks=t.review_remarks,
        reviewed_at=t.reviewed_at,
        created_at=t.created_at
    )


def build_report_out(r: CommitteeReport) -> CommitteeReportOut:
    return CommitteeReportOut(
        id=r.id,
        committee_id=r.committee_id,
        committee_title=r.committee.title if r.committee else None,
        title=r.title,
        report_type=r.report_type or "activity_report",
        report_date=r.report_date,
        venue=r.venue,
        attendees_count=r.attendees_count or 0,
        summary=r.summary,
        achievements=r.achievements,
        challenges=r.challenges,
        next_steps=r.next_steps,
        document_url=r.document_url,
        photos=r.photos or [],
        submitted_by=r.submitted_by,
        submitter_name=r.submitter.name if r.submitter else "Committee Member",
        status=r.status or "submitted",
        faculty_remarks=r.faculty_remarks,
        reviewed_by=r.reviewed_by,
        reviewer_name=r.reviewer.name if r.reviewer else None,
        reviewed_at=r.reviewed_at,
        created_at=r.created_at
    )


# -------------------------------------------------------------------------
# 1. CORE COMMITTEE CRUD & ALLOTMENT
# -------------------------------------------------------------------------

@router.get("", response_model=List[CoreCommitteeOut])
async def list_core_committees(
    category: Optional[str] = None,
    faculty_id: Optional[int] = None,
    event_id: Optional[int] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    query = (
        select(CoreCommittee)
        .options(
            selectinload(CoreCommittee.event),
            selectinload(CoreCommittee.faculty_mentor),
            selectinload(CoreCommittee.president),
            selectinload(CoreCommittee.creator)
        )
    )
    if category:
        query = query.where(CoreCommittee.category == category)
    if faculty_id:
        query = query.where(CoreCommittee.faculty_id == faculty_id)
    if event_id:
        query = query.where(CoreCommittee.event_id == event_id)

    result = await db.execute(query.order_by(desc(CoreCommittee.created_at)))
    committees = result.scalars().all()

    out = []
    for c in committees:
        out.append(await build_committee_out(c, db))
    return out


@router.get("/my-committees", response_model=List[CoreCommitteeOut])
async def get_my_committees(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Returns all committees where current_user is faculty coordinator, president, or listed member."""
    result = await db.execute(
        select(CoreCommittee)
        .options(
            selectinload(CoreCommittee.event),
            selectinload(CoreCommittee.faculty_mentor),
            selectinload(CoreCommittee.president),
            selectinload(CoreCommittee.creator)
        )
        .order_by(desc(CoreCommittee.created_at))
    )
    all_c = result.scalars().all()

    matched = []
    user_id = current_user.id
    user_email = (current_user.email or "").strip().lower()
    user_roll = (current_user.roll_number or "").strip().lower()

    for c in all_c:
        # Super admin sees all
        if current_user.role == UserRole.super_admin:
            matched.append(c)
            continue

        # Faculty coordinator
        if c.faculty_id == user_id:
            matched.append(c)
            continue

        # President
        if c.president_id == user_id:
            matched.append(c)
            continue

        # Member in student_roles
        is_member = False
        for m in (c.student_roles or []):
            if m.get("student_id") == user_id:
                is_member = True
                break
            if user_email and m.get("email") and m.get("email").strip().lower() == user_email:
                is_member = True
                break
            if user_roll and m.get("student_roll_no") and m.get("student_roll_no").strip().lower() == user_roll:
                is_member = True
                break

        if is_member:
            matched.append(c)

    out = []
    for c in matched:
        out.append(await build_committee_out(c, db))
    return out


@router.get("/{committee_id}", response_model=CoreCommitteeOut)
async def get_core_committee(
    committee_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(CoreCommittee)
        .options(
            selectinload(CoreCommittee.event),
            selectinload(CoreCommittee.faculty_mentor),
            selectinload(CoreCommittee.president),
            selectinload(CoreCommittee.creator)
        )
        .where(CoreCommittee.id == committee_id)
    )
    c = result.scalar_one_or_none()
    if not c:
        raise HTTPException(status_code=404, detail="Core Committee not found")

    return await build_committee_out(c, db)


@router.post("", response_model=CoreCommitteeOut)
async def create_core_committee(
    payload: CoreCommitteeCreate,
    current_user: User = Depends(require_role([UserRole.super_admin, UserRole.faculty])),
    db: AsyncSession = Depends(get_db)
):
    """
    Super Admin (or authorized Faculty) creates a Core Committee.
    - Admin can allot committee to any faculty coordinator (payload.faculty_id).
    - President is completely optional (payload.president_id or member marked is_president).
    - All student members are provisioned with portal login accounts so they can log in immediately.
    """
    # Verify Event if provided
    event = None
    if payload.event_id:
        ev_res = await db.execute(select(Event).where(Event.id == payload.event_id))
        event = ev_res.scalar_one_or_none()

    # Verify Faculty In-charge if provided
    faculty_mentor = None
    if payload.faculty_id:
        fac_res = await db.execute(select(User).where(User.id == payload.faculty_id))
        faculty_mentor = fac_res.scalar_one_or_none()

    # Process and enrich all student roles — ensure all student members have login access
    enriched_student_roles = []
    president_user_id = payload.president_id

    for item in payload.student_roles:
        is_pres = bool(
            item.is_president or 
            (item.role_name and "president" in item.role_name.lower())
        )

        student_user = None

        # 1. Match by student_id
        if item.student_id:
            s_res = await db.execute(select(User).where(User.id == item.student_id))
            student_user = s_res.scalar_one_or_none()

        clean_email = (item.email or "").strip().lower()
        clean_roll = (item.student_roll_no or "").strip()

        # 2. Match by email or roll
        if not student_user and clean_email:
            s_res = await db.execute(select(User).where(func.lower(User.email) == clean_email))
            student_user = s_res.scalar_one_or_none()

        if not student_user and clean_roll:
            s_res2 = await db.execute(select(User).where(User.roll_number == clean_roll))
            student_user = s_res2.scalar_one_or_none()

        # 3. If student user does not exist yet, provision an active portal login account!
        if not student_user:
            gen_email = clean_email or f"student_{uuid.uuid4().hex[:6]}@geeta.edu.in"
            raw_password = (item.password or "Geeta@123").strip()
            student_user = User(
                name=(item.student_name or "Committee Member").strip(),
                email=gen_email,
                phone=item.phone,
                roll_number=clean_roll or None,
                department=item.department or "Engineering & Technology",
                course_branch=item.department or "B.Tech CSE",
                year=item.semester or "3rd Year",
                role=UserRole.student,
                password_hash=get_password_hash(raw_password),
                is_active=True,
                must_change_password=False
            )
            db.add(student_user)
            await db.flush()

        # If this is president and president_user_id not set yet, record it
        if is_pres and not president_user_id:
            president_user_id = student_user.id

        stu_name = item.student_name or student_user.name
        stu_roll = clean_roll or student_user.roll_number or ""
        stu_dept = item.department or student_user.department or ""
        stu_sem = item.semester or student_user.year or ""
        stu_email = clean_email or student_user.email
        stu_phone = item.phone or student_user.phone or ""

        enriched_item = {
            "role_name": item.role_name,
            "student_id": student_user.id,
            "student_name": stu_name,
            "student_roll_no": stu_roll,
            "department": stu_dept,
            "semester": stu_sem,
            "email": stu_email,
            "phone": stu_phone,
            "is_president": is_pres,
            "has_account": True,
            "responsibilities": item.responsibilities or "",
            "points": item.points or 0
        }
        enriched_student_roles.append(enriched_item)

        # Notify student about appointment
        await create_notification(
            db,
            title=f"Appointed to {payload.title} 🎉",
            body=f"You have been appointed as '{item.role_name}' in the '{payload.title}'. Check your workspace to view tasks.",
            type="committee_appointment",
            user_id=student_user.id,
            link="/student/committees"
        )

    committee = CoreCommittee(
        title=payload.title,
        category=payload.category or "General",
        event_id=payload.event_id,
        event_date=payload.event_date or (event.start_date.strftime("%Y-%m-%d") if event and event.start_date else None),
        faculty_id=payload.faculty_id,
        president_id=president_user_id,
        description=payload.description,
        student_roles=enriched_student_roles,
        total_points=0,
        is_active=True,
        created_by=current_user.id
    )
    db.add(committee)
    await db.commit()
    await db.refresh(committee)

    # Notify faculty mentor if allotted
    if committee.faculty_id:
        await create_notification(
            db,
            title="Core Committee Allotted 🏛️",
            body=f"You have been assigned as Faculty Coordinator for '{committee.title}'. You can now assign tasks to members.",
            type="committee_allotment",
            user_id=committee.faculty_id,
            link="/faculty/committees"
        )

    await log_audit(
        db,
        action="CREATE_CORE_COMMITTEE",
        entity_type="core_committee",
        actor_id=current_user.id,
        entity_id=committee.id,
        meta={"title": committee.title, "faculty_id": committee.faculty_id}
    )
    await db.commit()

    # Reload with relationships
    res_rel = await db.execute(
        select(CoreCommittee)
        .options(
            selectinload(CoreCommittee.event),
            selectinload(CoreCommittee.faculty_mentor),
            selectinload(CoreCommittee.president),
            selectinload(CoreCommittee.creator)
        )
        .where(CoreCommittee.id == committee.id)
    )
    c_loaded = res_rel.scalar_one()
    return await build_committee_out(c_loaded, db)


@router.put("/{committee_id}", response_model=CoreCommitteeOut)
async def update_core_committee(
    committee_id: int,
    payload: CoreCommitteeUpdate,
    current_user: User = Depends(require_role([UserRole.super_admin, UserRole.faculty])),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(CoreCommittee)
        .options(
            selectinload(CoreCommittee.event),
            selectinload(CoreCommittee.faculty_mentor),
            selectinload(CoreCommittee.president),
            selectinload(CoreCommittee.creator)
        )
        .where(CoreCommittee.id == committee_id)
    )
    committee = result.scalar_one_or_none()
    if not committee:
        raise HTTPException(status_code=404, detail="Core Committee not found")

    # Faculty can only edit if allotted coordinator or creator
    if current_user.role == UserRole.faculty and committee.faculty_id != current_user.id and committee.created_by != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to modify this committee")

    old_faculty_id = committee.faculty_id

    if payload.title is not None:
        committee.title = payload.title
    if payload.category is not None:
        committee.category = payload.category
    if payload.event_id is not None:
        committee.event_id = payload.event_id
    if payload.event_date is not None:
        committee.event_date = payload.event_date
    if payload.faculty_id is not None:
        committee.faculty_id = payload.faculty_id
    if payload.president_id is not None:
        committee.president_id = payload.president_id
    if payload.description is not None:
        committee.description = payload.description
    if payload.is_active is not None:
        committee.is_active = payload.is_active

    if payload.student_roles is not None:
        # Re-enrich student roles
        new_roles = []
        for item in payload.student_roles:
            student_user = None
            if item.student_id:
                s_res = await db.execute(select(User).where(User.id == item.student_id))
                student_user = s_res.scalar_one_or_none()
            if not student_user and item.email:
                s_res = await db.execute(select(User).where(func.lower(User.email) == item.email.strip().lower()))
                student_user = s_res.scalar_one_or_none()
            if not student_user and item.student_roll_no:
                s_res = await db.execute(select(User).where(User.roll_number == item.student_roll_no.strip()))
                student_user = s_res.scalar_one_or_none()

            if not student_user:
                gen_email = item.email or f"student_{uuid.uuid4().hex[:6]}@geeta.edu.in"
                student_user = User(
                    name=(item.student_name or "Member").strip(),
                    email=gen_email,
                    phone=item.phone,
                    roll_number=item.student_roll_no or None,
                    department=item.department or "Engineering",
                    course_branch=item.department or "B.Tech CSE",
                    year=item.semester or "3rd Year",
                    role=UserRole.student,
                    password_hash=get_password_hash(item.password or "Geeta@123"),
                    is_active=True,
                    must_change_password=False
                )
                db.add(student_user)
                await db.flush()

            new_roles.append({
                "role_name": item.role_name,
                "student_id": student_user.id,
                "student_name": item.student_name or student_user.name,
                "student_roll_no": item.student_roll_no or student_user.roll_number or "",
                "department": item.department or student_user.department or "",
                "semester": item.semester or student_user.year or "",
                "email": item.email or student_user.email,
                "phone": item.phone or student_user.phone or "",
                "is_president": bool(item.is_president),
                "has_account": True,
                "responsibilities": item.responsibilities or "",
                "points": item.points or 0
            })
        committee.student_roles = new_roles

    await db.commit()

    # If faculty changed, notify new coordinator
    if payload.faculty_id and payload.faculty_id != old_faculty_id:
        await create_notification(
            db,
            title="Core Committee Allotted 🏛️",
            body=f"You have been assigned as Faculty Coordinator for '{committee.title}'.",
            type="committee_allotment",
            user_id=payload.faculty_id,
            link="/faculty/committees"
        )

    await db.refresh(committee)
    return await build_committee_out(committee, db)


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

    if current_user.role == UserRole.faculty and c.created_by != current_user.id and c.faculty_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only delete committees managed by you")

    await db.delete(c)
    await db.commit()
    return {"message": f"Core Committee '{c.title}' deleted successfully"}


# -------------------------------------------------------------------------
# 2. MEMBER MANAGEMENT (ADD / REMOVE MEMBER WITH LOGIN ACCESS)
# -------------------------------------------------------------------------

@router.post("/{committee_id}/members")
async def add_committee_member(
    committee_id: int,
    member: CommitteeRoleSchema,
    current_user: User = Depends(require_role([UserRole.super_admin, UserRole.faculty])),
    db: AsyncSession = Depends(get_db)
):
    """Admin or allotted Faculty adds a new member to the committee."""
    res = await db.execute(select(CoreCommittee).where(CoreCommittee.id == committee_id))
    c = res.scalar_one_or_none()
    if not c:
        raise HTTPException(status_code=404, detail="Core Committee not found")

    if current_user.role == UserRole.faculty and c.faculty_id != current_user.id and c.created_by != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to manage this committee")

    student_user = None
    if member.student_id:
        s_res = await db.execute(select(User).where(User.id == member.student_id))
        student_user = s_res.scalar_one_or_none()

    clean_email = (member.email or "").strip().lower()
    clean_roll = (member.student_roll_no or "").strip()

    if not student_user and clean_email:
        s_res = await db.execute(select(User).where(func.lower(User.email) == clean_email))
        student_user = s_res.scalar_one_or_none()

    if not student_user and clean_roll:
        s_res = await db.execute(select(User).where(User.roll_number == clean_roll))
        student_user = s_res.scalar_one_or_none()

    if not student_user:
        gen_email = clean_email or f"student_{uuid.uuid4().hex[:6]}@geeta.edu.in"
        student_user = User(
            name=(member.student_name or "Committee Member").strip(),
            email=gen_email,
            phone=member.phone,
            roll_number=clean_roll or None,
            department=member.department or "Engineering",
            course_branch=member.department or "B.Tech CSE",
            year=member.semester or "3rd Year",
            role=UserRole.student,
            password_hash=get_password_hash(member.password or "Geeta@123"),
            is_active=True,
            must_change_password=False
        )
        db.add(student_user)
        await db.flush()

    # Append to student_roles list
    existing_roles = list(c.student_roles or [])
    # Remove any duplicate entry for this student
    existing_roles = [r for r in existing_roles if r.get("student_id") != student_user.id and r.get("email") != student_user.email]

    is_pres = bool(member.is_president or (member.role_name and "president" in member.role_name.lower()))
    if is_pres:
        c.president_id = student_user.id

    existing_roles.append({
        "role_name": member.role_name,
        "student_id": student_user.id,
        "student_name": member.student_name or student_user.name,
        "student_roll_no": clean_roll or student_user.roll_number or "",
        "department": member.department or student_user.department or "",
        "semester": member.semester or student_user.year or "",
        "email": clean_email or student_user.email,
        "phone": member.phone or student_user.phone or "",
        "is_president": is_pres,
        "has_account": True,
        "responsibilities": member.responsibilities or "",
        "points": member.points or 0
    })

    c.student_roles = existing_roles
    await db.commit()

    await create_notification(
        db,
        title=f"Added to {c.title} 🎉",
        body=f"You have been added to '{c.title}' as '{member.role_name}'.",
        type="committee_appointment",
        user_id=student_user.id,
        link="/student/committees"
    )

    return {"message": "Member added successfully", "member_id": student_user.id}


@router.delete("/{committee_id}/members/{student_id}")
async def remove_committee_member(
    committee_id: int,
    student_id: int,
    current_user: User = Depends(require_role([UserRole.super_admin, UserRole.faculty])),
    db: AsyncSession = Depends(get_db)
):
    res = await db.execute(select(CoreCommittee).where(CoreCommittee.id == committee_id))
    c = res.scalar_one_or_none()
    if not c:
        raise HTTPException(status_code=404, detail="Core Committee not found")

    if current_user.role == UserRole.faculty and c.faculty_id != current_user.id and c.created_by != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    existing_roles = list(c.student_roles or [])
    c.student_roles = [r for r in existing_roles if r.get("student_id") != student_id]

    if c.president_id == student_id:
        c.president_id = None

    await db.commit()
    return {"message": "Member removed from committee"}


# -------------------------------------------------------------------------
# 3. COMMITTEE TASKS (ASSIGN, SUBMIT, REVIEW & AWARD POINTS)
# -------------------------------------------------------------------------

@router.get("/{committee_id}/tasks", response_model=List[CommitteeTaskOut])
async def list_committee_tasks(
    committee_id: int,
    status_filter: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    query = (
        select(CommitteeTask)
        .options(
            selectinload(CommitteeTask.committee),
            selectinload(CommitteeTask.assignee),
            selectinload(CommitteeTask.assigner),
            selectinload(CommitteeTask.submitter),
            selectinload(CommitteeTask.reviewer)
        )
        .where(CommitteeTask.committee_id == committee_id)
    )
    if status_filter:
        query = query.where(CommitteeTask.status == status_filter)

    result = await db.execute(query.order_by(desc(CommitteeTask.created_at)))
    tasks = result.scalars().all()

    return [build_task_out(t) for t in tasks]


@router.post("/{committee_id}/tasks", response_model=CommitteeTaskOut)
async def create_committee_task(
    committee_id: int,
    payload: CommitteeTaskCreate,
    current_user: User = Depends(require_role([UserRole.super_admin, UserRole.faculty])),
    db: AsyncSession = Depends(get_db)
):
    """
    Super Admin or Faculty Coordinator assigns a task to any committee member (or all members).
    """
    res = await db.execute(select(CoreCommittee).where(CoreCommittee.id == committee_id))
    committee = res.scalar_one_or_none()
    if not committee:
        raise HTTPException(status_code=404, detail="Core Committee not found")

    if current_user.role == UserRole.faculty and committee.faculty_id != current_user.id and committee.created_by != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to assign tasks for this committee")

    task = CommitteeTask(
        committee_id=committee_id,
        title=payload.title,
        description=payload.description,
        assigned_to=payload.assigned_to,
        assigned_by=current_user.id,
        points_reward=payload.points_reward or 20,
        priority=payload.priority or "medium",
        start_date=payload.start_date,
        due_date=payload.due_date,
        status="pending"
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)

    # Notify assignee if specific, or all members if open
    if payload.assigned_to:
        await create_notification(
            db,
            title="New Committee Task Assigned 📋",
            body=f"You have been assigned a task in '{committee.title}': {payload.title} ({payload.points_reward or 20} pts).",
            type="committee_task",
            user_id=payload.assigned_to,
            link=f"/student/committees?id={committee_id}"
        )
    else:
        # Broadcast to all committee members
        for m in (committee.student_roles or []):
            if m.get("student_id"):
                await create_notification(
                    db,
                    title=f"New Task in {committee.title} 📋",
                    body=f"Open task posted: {payload.title} ({payload.points_reward or 20} pts).",
                    type="committee_task",
                    user_id=m.get("student_id"),
                    link=f"/student/committees?id={committee_id}"
                )

    await log_audit(
        db,
        action="CREATE_COMMITTEE_TASK",
        entity_type="committee_task",
        actor_id=current_user.id,
        entity_id=task.id,
        meta={"title": task.title, "committee_id": committee_id}
    )
    await db.commit()

    # Load relationships
    res_rel = await db.execute(
        select(CommitteeTask)
        .options(
            selectinload(CommitteeTask.committee),
            selectinload(CommitteeTask.assignee),
            selectinload(CommitteeTask.assigner),
            selectinload(CommitteeTask.submitter),
            selectinload(CommitteeTask.reviewer)
        )
        .where(CommitteeTask.id == task.id)
    )
    t_loaded = res_rel.scalar_one()
    return build_task_out(t_loaded)


@router.post("/tasks/{task_id}/submit", response_model=CommitteeTaskOut)
async def submit_committee_task(
    task_id: int,
    payload: CommitteeTaskSubmit,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Committee member submits task proof/completion text/file.
    """
    res = await db.execute(
        select(CommitteeTask)
        .options(
            selectinload(CommitteeTask.committee),
            selectinload(CommitteeTask.assignee),
            selectinload(CommitteeTask.assigner),
            selectinload(CommitteeTask.submitter),
            selectinload(CommitteeTask.reviewer)
        )
        .where(CommitteeTask.id == task_id)
    )
    task = res.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    task.submission_text = payload.submission_text
    task.file_url = payload.file_url
    task.file_name = payload.file_name
    task.submitted_by = current_user.id
    task.submitted_at = utc_now()
    task.status = "submitted"

    await db.commit()

    # Notify Faculty coordinator and Admin
    if task.committee and task.committee.faculty_id:
        await create_notification(
            db,
            title="Committee Task Proof Submitted 📥",
            body=f"{current_user.name} submitted proof for task '{task.title}' in '{task.committee.title}'.",
            type="committee_task_submitted",
            user_id=task.committee.faculty_id,
            link=f"/faculty/committees?id={task.committee_id}"
        )

    await db.refresh(task)
    return build_task_out(task)


@router.post("/tasks/{task_id}/review", response_model=CommitteeTaskOut)
async def review_committee_task(
    task_id: int,
    payload: CommitteeTaskReview,
    current_user: User = Depends(require_role([UserRole.super_admin, UserRole.faculty])),
    db: AsyncSession = Depends(get_db)
):
    """
    Faculty Coordinator or Admin reviews task:
    - If approved: awards points to the student member, updates student ledger and committee total_points.
    - If declined: records remarks for revision.
    """
    res = await db.execute(
        select(CommitteeTask)
        .options(
            selectinload(CommitteeTask.committee),
            selectinload(CommitteeTask.assignee),
            selectinload(CommitteeTask.assigner),
            selectinload(CommitteeTask.submitter),
            selectinload(CommitteeTask.reviewer)
        )
        .where(CommitteeTask.id == task_id)
    )
    task = res.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    is_approved = payload.status.lower() in ["approved", "verified", "completed"]
    task.status = "approved" if is_approved else "declined"
    task.review_remarks = payload.review_remarks
    task.reviewed_by = current_user.id
    task.reviewed_at = utc_now()

    pts = payload.points_awarded if payload.points_awarded is not None else task.points_reward

    if is_approved and task.submitted_by:
        # 1. Add points to student points ledger
        ledger_entry = StudentPointsLedger(
            student_id=task.submitted_by,
            points=pts,
            source_type="committee_task",
            reason_note=f"Completed Committee Task: {task.title} ({task.committee.title if task.committee else 'Core Committee'})",
            awarded_by=current_user.id
        )
        db.add(ledger_entry)

        # 2. Update member points in committee JSON
        if task.committee:
            task.committee.total_points = (task.committee.total_points or 0) + pts
            roles = list(task.committee.student_roles or [])
            for r in roles:
                if r.get("student_id") == task.submitted_by:
                    r["points"] = (r.get("points") or 0) + pts
            task.committee.student_roles = roles

        # 3. Notify student
        await create_notification(
            db,
            title="Task Approved & Points Awarded 🌟",
            body=f"Your task '{task.title}' was approved! You earned +{pts} points.",
            type="points_awarded",
            user_id=task.submitted_by,
            link=f"/student/committees?id={task.committee_id}"
        )
    elif not is_approved and task.submitted_by:
        await create_notification(
            db,
            title="Task Needs Revision ⚠️",
            body=f"Your task '{task.title}' was declined: {payload.review_remarks or 'Please revise and resubmit.'}",
            type="task_declined",
            user_id=task.submitted_by,
            link=f"/student/committees?id={task.committee_id}"
        )

    await db.commit()
    await db.refresh(task)
    return build_task_out(task)


@router.delete("/tasks/{task_id}")
async def delete_committee_task(
    task_id: int,
    current_user: User = Depends(require_role([UserRole.super_admin, UserRole.faculty])),
    db: AsyncSession = Depends(get_db)
):
    res = await db.execute(select(CommitteeTask).where(CommitteeTask.id == task_id))
    task = res.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    await db.delete(task)
    await db.commit()
    return {"message": "Task deleted successfully"}


# -------------------------------------------------------------------------
# 4. COMMITTEE REPORTS & DAILY DPR SUBMISSION
# -------------------------------------------------------------------------

@router.get("/{committee_id}/reports", response_model=List[CommitteeReportOut])
async def list_committee_reports(
    committee_id: int,
    report_type: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    query = (
        select(CommitteeReport)
        .options(
            selectinload(CommitteeReport.committee),
            selectinload(CommitteeReport.submitter),
            selectinload(CommitteeReport.reviewer)
        )
        .where(CommitteeReport.committee_id == committee_id)
    )
    if report_type:
        query = query.where(CommitteeReport.report_type == report_type)

    result = await db.execute(query.order_by(desc(CommitteeReport.created_at)))
    reports = result.scalars().all()
    return [build_report_out(r) for r in reports]


@router.post("/{committee_id}/reports", response_model=CommitteeReportOut)
async def create_committee_report(
    committee_id: int,
    payload: CommitteeReportCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Committee member / student / faculty creates an activity report or daily work log (DPR).
    """
    res = await db.execute(select(CoreCommittee).where(CoreCommittee.id == committee_id))
    committee = res.scalar_one_or_none()
    if not committee:
        raise HTTPException(status_code=404, detail="Core Committee not found")

    report = CommitteeReport(
        committee_id=committee_id,
        title=payload.title,
        report_type=payload.report_type or "activity_report",
        report_date=payload.report_date,
        venue=payload.venue,
        attendees_count=payload.attendees_count or 0,
        summary=payload.summary,
        achievements=payload.achievements,
        challenges=payload.challenges,
        next_steps=payload.next_steps,
        document_url=payload.document_url,
        photos=payload.photos or [],
        submitted_by=current_user.id,
        status="submitted"
    )
    db.add(report)
    await db.commit()
    await db.refresh(report)

    # Notify coordinator
    if committee.faculty_id:
        await create_notification(
            db,
            title="New Committee Report Submitted 📝",
            body=f"{current_user.name} submitted a report: '{report.title}' for '{committee.title}'.",
            type="committee_report",
            user_id=committee.faculty_id,
            link=f"/faculty/committees?id={committee_id}"
        )

    await log_audit(
        db,
        action="CREATE_COMMITTEE_REPORT",
        entity_type="committee_report",
        actor_id=current_user.id,
        entity_id=report.id,
        meta={"title": report.title, "committee_id": committee_id}
    )
    await db.commit()

    res_rel = await db.execute(
        select(CommitteeReport)
        .options(
            selectinload(CommitteeReport.committee),
            selectinload(CommitteeReport.submitter),
            selectinload(CommitteeReport.reviewer)
        )
        .where(CommitteeReport.id == report.id)
    )
    r_loaded = res_rel.scalar_one()
    return build_report_out(r_loaded)


@router.post("/reports/{report_id}/review", response_model=CommitteeReportOut)
async def review_committee_report(
    report_id: int,
    status_update: str = Query("approved", description="approved or draft"),
    faculty_remarks: Optional[str] = Query(None),
    current_user: User = Depends(require_role([UserRole.super_admin, UserRole.faculty])),
    db: AsyncSession = Depends(get_db)
):
    res = await db.execute(
        select(CommitteeReport)
        .options(
            selectinload(CommitteeReport.committee),
            selectinload(CommitteeReport.submitter),
            selectinload(CommitteeReport.reviewer)
        )
        .where(CommitteeReport.id == report_id)
    )
    report = res.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    report.status = status_update
    report.faculty_remarks = faculty_remarks
    report.reviewed_by = current_user.id
    report.reviewed_at = utc_now()

    await db.commit()
    await db.refresh(report)
    return build_report_out(report)


# -------------------------------------------------------------------------
# 5. COMMITTEE LEADERBOARD & POINTS SYSTEM
# -------------------------------------------------------------------------

@router.get("/{committee_id}/leaderboard", response_model=List[CommitteeLeaderboardEntry])
async def get_committee_leaderboard(
    committee_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Computes committee member rankings based on points earned from verified tasks and reports.
    """
    res = await db.execute(select(CoreCommittee).where(CoreCommittee.id == committee_id))
    c = res.scalar_one_or_none()
    if not c:
        raise HTTPException(status_code=404, detail="Core Committee not found")

    # Fetch task completion stats per student in this committee
    task_res = await db.execute(
        select(
            CommitteeTask.submitted_by,
            func.count(CommitteeTask.id).label("completed_count"),
            func.sum(CommitteeTask.points_reward).label("earned_points")
        )
        .where(
            CommitteeTask.committee_id == committee_id,
            CommitteeTask.status == "approved"
        )
        .group_by(CommitteeTask.submitted_by)
    )
    task_stats = {row[0]: (row[1], row[2] or 0) for row in task_res.all()}

    # Fetch report counts per student
    rep_res = await db.execute(
        select(
            CommitteeReport.submitted_by,
            func.count(CommitteeReport.id).label("rep_count")
        )
        .where(
            CommitteeReport.committee_id == committee_id,
            CommitteeReport.status == "approved"
        )
        .group_by(CommitteeReport.submitted_by)
    )
    report_stats = {row[0]: row[1] for row in rep_res.all()}

    entries: List[CommitteeLeaderboardEntry] = []

    for m in (c.student_roles or []):
        sid = m.get("student_id")
        completed_tasks, task_points = task_stats.get(sid, (0, 0))
        reports_count = report_stats.get(sid, 0)
        base_points = m.get("points") or 0
        total_pts = base_points + task_points + (reports_count * 10)

        entries.append(CommitteeLeaderboardEntry(
            student_id=sid,
            student_name=m.get("student_name") or "Member",
            student_roll_no=m.get("student_roll_no"),
            department=m.get("department"),
            role_name=m.get("role_name") or "Member",
            is_president=bool(m.get("is_president")),
            total_points=total_pts,
            tasks_completed=completed_tasks,
            reports_submitted=reports_count,
            rank=1
        ))

    # Sort descending by total_points
    entries.sort(key=lambda x: (x.total_points, x.tasks_completed), reverse=True)

    # Assign ranks
    for idx, entry in enumerate(entries):
        entry.rank = idx + 1

    return entries
