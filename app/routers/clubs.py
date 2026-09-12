from datetime import datetime, timezone
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_, desc

from app.database import get_db
from app.core.deps import get_current_user, require_role
from app.models.all_models import (
    User, UserRole, Club, ClubTask, ClubTaskSubmission,
    ClubPointsLedger, Notification, AuditLog
)
from app.schemas.schemas import (
    ClubCreate, ClubUpdate, ClubOut, ClubTaskCreate, ClubTaskOut,
    ClubTaskSubmissionCreate, ClubTaskSubmissionOut, ClubTaskReviewPayload,
    ClubRankingOut, ClubManualPointsPayload
)

router = APIRouter(prefix="/api/clubs", tags=["University Clubs"])


def _format_club_out(club: Club, tasks_count: int = 0, completed_tasks_count: int = 0) -> ClubOut:
    fac = club.faculty_coordinator
    return ClubOut(
        id=club.id,
        title=club.title,
        description=club.description,
        category=club.category or "Technical",
        kras=club.kras,
        faculty_coordinator_id=club.faculty_coordinator_id,
        faculty_coordinator_name=fac.name if fac else None,
        faculty_coordinator_dept=fac.department if fac else None,
        faculty_coordinator_email=fac.email if fac else None,
        faculty_coordinator_phone=fac.phone if fac else None,
        student_roles=club.student_roles or [],
        members=club.members or [],
        logo_url=club.logo_url,
        total_points=club.total_points or 0,
        is_active=club.is_active,
        created_by=club.created_by,
        creator_name=club.creator.name if club.creator else None,
        created_at=club.created_at,
        tasks_count=tasks_count,
        completed_tasks_count=completed_tasks_count
    )


# --- 1. CLUBS CRUD ---
@router.get("", response_model=List[ClubOut])
async def get_all_clubs(
    search: Optional[str] = None,
    category: Optional[str] = None,
    faculty_id: Optional[int] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    query = select(Club).where(Club.is_active == True)
    if search:
        query = query.where(or_(Club.title.ilike(f"%{search}%"), Club.description.ilike(f"%{search}%")))
    if category:
        query = query.where(Club.category == category)
    if faculty_id:
        query = query.where(Club.faculty_coordinator_id == faculty_id)

    query = query.order_by(desc(Club.total_points), Club.title)
    result = await db.execute(query)
    clubs = result.scalars().all()

    # Get task statistics
    out_list = []
    for c in clubs:
        tasks_res = await db.execute(select(ClubTask).where(ClubTask.club_id == c.id))
        all_tasks = tasks_res.scalars().all()
        t_cnt = len(all_tasks)
        comp_cnt = sum(1 for t in all_tasks if t.status == "completed")
        out_list.append(_format_club_out(c, tasks_count=t_cnt, completed_tasks_count=comp_cnt))

    return out_list


@router.post("", response_model=ClubOut)
async def create_club(
    payload: ClubCreate,
    current_user: User = Depends(require_role([UserRole.super_admin])),
    db: AsyncSession = Depends(get_db)
):
    # Verify faculty
    fac_res = await db.execute(select(User).where(User.id == payload.faculty_coordinator_id))
    fac = fac_res.scalar_one_or_none()
    if not fac:
        raise HTTPException(status_code=400, detail="Invalid faculty coordinator ID")

    new_club = Club(
        title=payload.title,
        description=payload.description,
        category=payload.category or "Technical",
        kras=payload.kras,
        faculty_coordinator_id=payload.faculty_coordinator_id,
        student_roles=payload.student_roles or [],
        members=payload.members or [],
        logo_url=payload.logo_url,
        total_points=0,
        is_active=True,
        created_by=current_user.id
    )
    db.add(new_club)
    await db.commit()
    await db.refresh(new_club)

    # Notify faculty
    notif = Notification(
        user_id=fac.id,
        title=f"Assigned as Faculty Coordinator: {new_club.title}",
        body=f"You have been appointed as the official Faculty Coordinator for '{new_club.title}'. You can now allocate student roles and manage the club roster.",
        type="club_assigned",
        link="/faculty/clubs"
    )
    db.add(notif)
    await db.commit()

    return _format_club_out(new_club)


@router.get("/{club_id}", response_model=ClubOut)
async def get_club_by_id(
    club_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Club).where(Club.id == club_id))
    club = result.scalar_one_or_none()
    if not club:
        raise HTTPException(status_code=404, detail="Club not found")

    tasks_res = await db.execute(select(ClubTask).where(ClubTask.club_id == club.id))
    all_tasks = tasks_res.scalars().all()
    t_cnt = len(all_tasks)
    comp_cnt = sum(1 for t in all_tasks if t.status == "completed")

    return _format_club_out(club, tasks_count=t_cnt, completed_tasks_count=comp_cnt)


@router.put("/{club_id}", response_model=ClubOut)
async def update_club(
    club_id: int,
    payload: ClubUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Club).where(Club.id == club_id))
    club = result.scalar_one_or_none()
    if not club:
        raise HTTPException(status_code=404, detail="Club not found")

    # Authorization: super_admin or assigned faculty
    if current_user.role != UserRole.super_admin and club.faculty_coordinator_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to edit this club")

    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(club, k, v)

    await db.commit()
    await db.refresh(club)

    return _format_club_out(club)


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

    club.is_active = False
    await db.commit()
    return {"message": "Club deactivated successfully"}


# --- 2. MEMBER & ROSTER MANAGEMENT ---
@router.post("/{club_id}/members", response_model=ClubOut)
async def add_or_update_club_members(
    club_id: int,
    payload: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Club).where(Club.id == club_id))
    club = result.scalar_one_or_none()
    if not club:
        raise HTTPException(status_code=404, detail="Club not found")

    if current_user.role != UserRole.super_admin and club.faculty_coordinator_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to manage members of this club")

    if "student_roles" in payload:
        club.student_roles = payload["student_roles"]
    if "members" in payload:
        club.members = payload["members"]

    await db.commit()
    await db.refresh(club)
    return _format_club_out(club)


# --- 3. PRINTABLE OFFICIAL CLUB PDF / HTML REPORT ---
@router.get("/{club_id}/report-html", response_class=HTMLResponse)
async def get_club_report_html(
    club_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Club).where(Club.id == club_id))
    club = result.scalar_one_or_none()
    if not club:
        raise HTTPException(status_code=404, detail="Club not found")

    fac = club.faculty_coordinator
    fac_name = fac.name if fac else "Unassigned"
    fac_dept = fac.department if fac else "Geeta University"
    fac_email = fac.email if fac else "N/A"
    fac_phone = fac.phone if fac else "N/A"
    fac_emp = fac.employee_id if fac else "N/A"

    roles = club.student_roles or []
    members = club.members or []

    # Format Executive Board Rows
    role_rows = ""
    for idx, r in enumerate(roles):
        role_name = r.get("role_name", f"Executive #{idx+1}")
        stu_name = r.get("student_name", "Vacant")
        roll = r.get("roll_number", "-")
        branch = r.get("branch", "-")
        sem = r.get("semester", "-")
        email = r.get("email", "-")
        phone = r.get("phone", "-")
        role_rows += f"""
        <tr>
            <td style="padding: 8px; border: 1px solid #cbd5e1; text-align: center; font-weight: bold;">{idx+1}</td>
            <td style="padding: 8px; border: 1px solid #cbd5e1; font-weight: bold; color: #064e3b;">{role_name}</td>
            <td style="padding: 8px; border: 1px solid #cbd5e1; font-weight: 600;">{stu_name}</td>
            <td style="padding: 8px; border: 1px solid #cbd5e1; font-family: monospace;">{roll}</td>
            <td style="padding: 8px; border: 1px solid #cbd5e1;">{branch}</td>
            <td style="padding: 8px; border: 1px solid #cbd5e1; text-align: center;">{sem}</td>
            <td style="padding: 8px; border: 1px solid #cbd5e1;">{email}<br><small style="color: #64748b;">{phone}</small></td>
        </tr>
        """

    if not role_rows:
        role_rows = "<tr><td colspan='7' style='padding: 12px; text-align: center; color: #64748b;'>No executive committee roles registered yet.</td></tr>"

    # Format General Members Rows
    member_rows = ""
    for idx, m in enumerate(members):
        m_name = m.get("name", "Student Member")
        m_roll = m.get("roll_number", "-")
        m_branch = m.get("branch", "-")
        m_sem = m.get("semester", "-")
        m_email = m.get("email", "-")
        m_phone = m.get("phone", "-")
        member_rows += f"""
        <tr>
            <td style="padding: 6px 8px; border: 1px solid #cbd5e1; text-align: center;">{idx+1}</td>
            <td style="padding: 6px 8px; border: 1px solid #cbd5e1; font-weight: 600;">{m_name}</td>
            <td style="padding: 6px 8px; border: 1px solid #cbd5e1; font-family: monospace;">{m_roll}</td>
            <td style="padding: 6px 8px; border: 1px solid #cbd5e1;">{m_branch}</td>
            <td style="padding: 6px 8px; border: 1px solid #cbd5e1; text-align: center;">{m_sem}</td>
            <td style="padding: 6px 8px; border: 1px solid #cbd5e1;">{m_email} • {m_phone}</td>
        </tr>
        """

    if not member_rows:
        member_rows = "<tr><td colspan='6' style='padding: 10px; text-align: center; color: #64748b;'>No general members registered yet.</td></tr>"

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>Club Charter & Official Roster - {club.title}</title>
        <style>
            @page {{ size: A4; margin: 15mm; }}
            body {{ font-family: 'Segoe UI', Arial, sans-serif; color: #0f172a; line-height: 1.5; margin: 0; padding: 20px; background: #ffffff; }}
            .header {{ text-align: center; border-bottom: 2px solid #064e3b; padding-bottom: 12px; margin-bottom: 20px; }}
            .header h1 {{ margin: 0; font-size: 22px; color: #064e3b; text-transform: uppercase; letter-spacing: 1px; }}
            .header h2 {{ margin: 4px 0 0 0; font-size: 14px; font-weight: 600; color: #334155; text-transform: uppercase; }}
            .header p {{ margin: 4px 0 0 0; font-size: 12px; color: #64748b; }}
            .meta-box {{ background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 14px; margin-bottom: 18px; }}
            .section-title {{ font-size: 13px; font-weight: bold; text-transform: uppercase; color: #064e3b; margin: 18px 0 8px 0; border-bottom: 1.5px solid #064e3b; padding-bottom: 4px; }}
            table {{ width: 100%; border-collapse: collapse; font-size: 11px; margin-bottom: 15px; }}
            th {{ background: #eaf4f0; color: #064e3b; padding: 8px; border: 1px solid #cbd5e1; text-align: left; text-transform: uppercase; font-weight: bold; }}
            .signature-block {{ margin-top: 40px; display: flex; justify-content: space-between; page-break-inside: avoid; }}
            .sig {{ text-align: center; width: 220px; border-top: 1.5px solid #475569; padding-top: 6px; font-size: 12px; font-weight: bold; }}
            @media print {{
                body {{ padding: 0; }}
                .no-print {{ display: none; }}
            }}
        </style>
    </head>
    <body>
        <div class="header">
            <div style="font-weight: 900; font-size: 12px; letter-spacing: 2px; color: #64748b; margin-bottom: 2px;">GEETA UNIVERSITY, PANIPAT</div>
            <h1>OFFICE OF DEAN STUDENT WELFARE (DSW)</h1>
            <h2>Official Student Club Charter & Leadership Directory</h2>
            <p>Affiliated under DSW Student Activity Council • Date of Issue: {datetime.now().strftime('%d %B %Y')}</p>
        </div>

        <div class="meta-box">
            <table style="margin: 0; border: none; font-size: 12px;">
                <tr style="background: transparent;">
                    <td style="border: none; width: 60%;">
                        <strong style="font-size: 16px; color: #064e3b;">{club.title}</strong><br>
                        <span style="color: #475569;">Category: <strong>{club.category}</strong> • Lifetime Points: <strong style="color: #059669;">{club.total_points} pts</strong></span>
                    </td>
                    <td style="border: none; text-align: right;">
                        <span style="display: inline-block; padding: 4px 10px; background: #eaf4f0; color: #064e3b; border-radius: 6px; font-weight: bold; font-size: 11px;">
                            STATUS: ACTIVE CLUB
                        </span>
                    </td>
                </tr>
            </table>
            <div style="margin-top: 10px; font-size: 11.5px; color: #334155;">
                <strong>Club Overview:</strong> {club.description or 'Official student activity club recognized by Geeta University.'}
            </div>
            {f'<div style="margin-top: 8px; font-size: 11.5px; color: #064e3b; background: #ecfdf5; padding: 8px; border-radius: 6px;"><strong>Key Result Areas (KRAs) & Directives:</strong><br>{club.kras}</div>' if club.kras else ''}
        </div>

        <div class="section-title">Faculty Coordinator In-Charge</div>
        <table style="font-size: 12px;">
            <tr>
                <th style="width: 25%;">Faculty Name</th>
                <th style="width: 30%;">Department & Employee ID</th>
                <th style="width: 25%;">Email Address</th>
                <th style="width: 20%;">Contact Number</th>
            </tr>
            <tr>
                <td style="padding: 8px; border: 1px solid #cbd5e1; font-weight: bold;">{fac_name}</td>
                <td style="padding: 8px; border: 1px solid #cbd5e1;">{fac_dept} (ID: {fac_emp})</td>
                <td style="padding: 8px; border: 1px solid #cbd5e1;">{fac_email}</td>
                <td style="padding: 8px; border: 1px solid #cbd5e1;">{fac_phone}</td>
            </tr>
        </table>

        <div class="section-title">Core Executive Student Committee ({len(roles)} Appointed Roles)</div>
        <table>
            <thead>
                <tr>
                    <th style="width: 4%;">#</th>
                    <th style="width: 18%;">Designation / Role</th>
                    <th style="width: 20%;">Student Name</th>
                    <th style="width: 14%;">Roll Number</th>
                    <th style="width: 14%;">Branch / Course</th>
                    <th style="width: 8%; text-align: center;">Sem</th>
                    <th style="width: 22%;">Contact & Email</th>
                </tr>
            </thead>
            <tbody>
                {role_rows}
            </tbody>
        </table>

        <div class="section-title">General Club Members Roster ({len(members)} Registered Members)</div>
        <table>
            <thead>
                <tr>
                    <th style="width: 5%;">#</th>
                    <th style="width: 25%;">Member Name</th>
                    <th style="width: 18%;">Roll Number</th>
                    <th style="width: 20%;">Branch / Specialization</th>
                    <th style="width: 10%; text-align: center;">Sem</th>
                    <th style="width: 22%;">Contact Details</th>
                </tr>
            </thead>
            <tbody>
                {member_rows}
            </tbody>
        </table>

        <div class="signature-block">
            <div class="sig">
                <div>{fac_name}</div>
                <div style="font-size: 10px; font-weight: normal; color: #64748b;">Faculty Coordinator, {club.title}</div>
            </div>
            <div class="sig">
                <div>Dean of Student Welfare</div>
                <div style="font-size: 10px; font-weight: normal; color: #64748b;">DSW Office, Geeta University</div>
            </div>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)


# --- 4. CLUB TASKS & SUBMISSIONS ---
@router.get("/{club_id}/tasks", response_model=List[ClubTaskOut])
async def get_club_tasks(
    club_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Club).where(Club.id == club_id))
    club = result.scalar_one_or_none()
    if not club:
        raise HTTPException(status_code=404, detail="Club not found")

    tasks_res = await db.execute(
        select(ClubTask).where(ClubTask.club_id == club_id).order_by(desc(ClubTask.created_at))
    )
    tasks = tasks_res.scalars().all()

    out = []
    for t in tasks:
        sub_cnt_res = await db.execute(select(func.count(ClubTaskSubmission.id)).where(ClubTaskSubmission.club_task_id == t.id))
        sub_cnt = sub_cnt_res.scalar_one()
        out.append(ClubTaskOut(
            id=t.id,
            club_id=t.club_id,
            club_title=club.title,
            title=t.title,
            description=t.description,
            points_value=t.points_value,
            due_date=t.due_date,
            status=t.status,
            created_by=t.created_by,
            created_at=t.created_at,
            submissions_count=sub_cnt
        ))
    return out


@router.post("/{club_id}/tasks", response_model=ClubTaskOut)
async def create_club_task(
    club_id: int,
    payload: ClubTaskCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Club).where(Club.id == club_id))
    club = result.scalar_one_or_none()
    if not club:
        raise HTTPException(status_code=404, detail="Club not found")

    if current_user.role != UserRole.super_admin and club.faculty_coordinator_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to assign tasks to this club")

    new_task = ClubTask(
        club_id=club_id,
        title=payload.title,
        description=payload.description,
        points_value=payload.points_value or 20,
        due_date=payload.due_date,
        status="active",
        created_by=current_user.id
    )
    db.add(new_task)
    await db.commit()
    await db.refresh(new_task)

    return ClubTaskOut(
        id=new_task.id,
        club_id=new_task.club_id,
        club_title=club.title,
        title=new_task.title,
        description=new_task.description,
        points_value=new_task.points_value,
        due_date=new_task.due_date,
        status=new_task.status,
        created_by=new_task.created_by,
        created_at=new_task.created_at,
        submissions_count=0
    )


@router.post("/tasks/{task_id}/submit", response_model=ClubTaskSubmissionOut)
async def submit_club_task_proof(
    task_id: int,
    payload: ClubTaskSubmissionCreate,
    current_user: User = Depends(require_role([UserRole.student])),
    db: AsyncSession = Depends(get_db)
):
    task_res = await db.execute(select(ClubTask).where(ClubTask.id == task_id))
    task = task_res.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Club task not found")

    club_res = await db.execute(select(Club).where(Club.id == task.club_id))
    club = club_res.scalar_one_or_none()

    sub = ClubTaskSubmission(
        club_task_id=task.id,
        club_id=task.club_id,
        submitted_by=current_user.id,
        submission_text=payload.submission_text,
        file_url=payload.file_url,
        status="pending"
    )
    db.add(sub)
    await db.commit()
    await db.refresh(sub)

    return ClubTaskSubmissionOut(
        id=sub.id,
        club_task_id=sub.club_task_id,
        task_title=task.title,
        club_id=task.club_id,
        club_title=club.title if club else None,
        submitted_by=sub.submitted_by,
        submitter_name=current_user.name,
        submitter_roll=current_user.roll_number,
        submission_text=sub.submission_text,
        file_url=sub.file_url,
        submitted_at=sub.submitted_at,
        status=sub.status
    )


@router.get("/tasks/{task_id}/submissions", response_model=List[ClubTaskSubmissionOut])
async def get_task_submissions(
    task_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    task_res = await db.execute(select(ClubTask).where(ClubTask.id == task_id))
    task = task_res.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Club task not found")

    club_res = await db.execute(select(Club).where(Club.id == task.club_id))
    club = club_res.scalar_one_or_none()

    subs_res = await db.execute(
        select(ClubTaskSubmission).where(ClubTaskSubmission.club_task_id == task_id).order_by(desc(ClubTaskSubmission.submitted_at))
    )
    subs = subs_res.scalars().all()

    out = []
    for s in subs:
        stu_res = await db.execute(select(User).where(User.id == s.submitted_by))
        stu = stu_res.scalar_one_or_none()
        out.append(ClubTaskSubmissionOut(
            id=s.id,
            club_task_id=s.club_task_id,
            task_title=task.title,
            club_id=s.club_id,
            club_title=club.title if club else None,
            submitted_by=s.submitted_by,
            submitter_name=stu.name if stu else "Student",
            submitter_roll=stu.roll_number if stu else None,
            submission_text=s.submission_text,
            file_url=s.file_url,
            submitted_at=s.submitted_at,
            status=s.status,
            points_awarded=s.points_awarded,
            reviewed_by=s.reviewed_by,
            reviewed_at=s.reviewed_at,
            review_remarks=s.review_remarks
        ))
    return out


@router.post("/submissions/{sub_id}/approve")
async def approve_club_submission(
    sub_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    sub_res = await db.execute(select(ClubTaskSubmission).where(ClubTaskSubmission.id == sub_id))
    sub = sub_res.scalar_one_or_none()
    if not sub:
        raise HTTPException(status_code=404, detail="Submission not found")

    task_res = await db.execute(select(ClubTask).where(ClubTask.id == sub.club_task_id))
    task = task_res.scalar_one_or_none()

    club_res = await db.execute(select(Club).where(Club.id == sub.club_id))
    club = club_res.scalar_one_or_none()
    if not club:
        raise HTTPException(status_code=404, detail="Associated club not found")

    # Auth check
    if current_user.role != UserRole.super_admin and club.faculty_coordinator_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to approve this submission")

    points = task.points_value if task else 20
    sub.status = "approved"
    sub.points_awarded = points
    sub.reviewed_by = current_user.id
    sub.reviewed_at = datetime.now(timezone.utc)

    # Award points to Club Ledger
    ledger_entry = ClubPointsLedger(
        club_id=club.id,
        points=points,
        source_type="task_submission",
        source_id=sub.id,
        reason_note=f"Task Approved: {task.title if task else 'Challenge'}",
        awarded_by=current_user.id
    )
    db.add(ledger_entry)

    # Update club total_points
    club.total_points = (club.total_points or 0) + points
    if task:
        task.status = "completed"

    await db.commit()
    return {"message": "Submission approved and points awarded to club", "points_awarded": points, "club_total_points": club.total_points}


@router.post("/submissions/{sub_id}/reject")
async def reject_club_submission(
    sub_id: int,
    payload: ClubTaskReviewPayload,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    sub_res = await db.execute(select(ClubTaskSubmission).where(ClubTaskSubmission.id == sub_id))
    sub = sub_res.scalar_one_or_none()
    if not sub:
        raise HTTPException(status_code=404, detail="Submission not found")

    club_res = await db.execute(select(Club).where(Club.id == sub.club_id))
    club = club_res.scalar_one_or_none()

    if current_user.role != UserRole.super_admin and (club and club.faculty_coordinator_id != current_user.id):
        raise HTTPException(status_code=403, detail="Not authorized to reject this submission")

    sub.status = "declined"
    sub.reviewed_by = current_user.id
    sub.reviewed_at = datetime.now(timezone.utc)
    sub.review_remarks = payload.review_remarks

    await db.commit()
    return {"message": "Submission declined with remarks"}


# --- 5. CLUB LEADERBOARD & RANKINGS ---
@router.get("/leaderboard/rankings", response_model=List[ClubRankingOut])
async def get_club_rankings(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    clubs_res = await db.execute(select(Club).where(Club.is_active == True))
    clubs = clubs_res.scalars().all()

    rankings_data = []
    for c in clubs:
        fac = c.faculty_coordinator
        tasks_res = await db.execute(select(ClubTask).where(ClubTask.club_id == c.id, ClubTask.status == "completed"))
        tasks_completed = len(tasks_res.scalars().all())

        exec_count = len(c.student_roles or [])
        mem_count = len(c.members or [])

        rankings_data.append({
            "club_id": c.id,
            "title": c.title,
            "category": c.category or "General",
            "faculty_coordinator_name": fac.name if fac else "Unassigned",
            "executive_count": exec_count,
            "members_count": mem_count,
            "tasks_completed": tasks_completed,
            "total_points": c.total_points or 0
        })

    # Sort descending by total_points, tie-break by tasks_completed
    rankings_data.sort(key=lambda x: (x["total_points"], x["tasks_completed"]), reverse=True)

    result = []
    for idx, r in enumerate(rankings_data):
        r["rank"] = idx + 1
        result.append(ClubRankingOut(**r))

    return result


@router.post("/points/manual-award")
async def award_club_manual_points(
    payload: ClubManualPointsPayload,
    current_user: User = Depends(require_role([UserRole.super_admin])),
    db: AsyncSession = Depends(get_db)
):
    club_res = await db.execute(select(Club).where(Club.id == payload.club_id))
    club = club_res.scalar_one_or_none()
    if not club:
        raise HTTPException(status_code=404, detail="Club not found")

    ledger_entry = ClubPointsLedger(
        club_id=club.id,
        points=payload.points,
        source_type="manual_award",
        reason_note=payload.reason_note,
        awarded_by=current_user.id
    )
    db.add(ledger_entry)
    club.total_points = max(0, (club.total_points or 0) + payload.points)

    await db.commit()
    return {"message": f"Successfully updated {club.title} by {payload.points} points", "total_points": club.total_points}
