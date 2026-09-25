from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, desc
from sqlalchemy.orm import selectinload
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone, timedelta

from app.database import get_db
from app.core.deps import get_current_user, require_role
from app.models.all_models import (
    User, UserRole, Task, TaskStatus,
    DailyProgressReport, DPRTaskUpdate,
    Notification
)
from app.schemas.schemas import (
    DPRCreateRequest, DPRAcknowledgeRequest,
    DPROut, DPRTaskUpdateOut, DPRTodayStatusOut,
    DPRAdminOverviewOut, MissingEmployeeOut, TaskOut
)
from app.services.notification_service import create_notification, log_audit
from app.services.dpr_document_service import (
    generate_dpr_html, save_dpr_document_to_archive, sync_dpr_to_google_drive
)
from app.routers.tasks import build_task_out

router = APIRouter(prefix="/api/dpr", tags=["Daily Progress Report (DPR)"])

# IST timezone for India / Geeta University (UTC + 5:30)
IST = timezone(timedelta(hours=5, minutes=30))

def get_today_date_str() -> str:
    now_ist = datetime.now(timezone.utc).astimezone(IST)
    return now_ist.strftime("%Y-%m-%d")

def build_dpr_out(report: DailyProgressReport) -> DPROut:
    task_updates_out = []
    if report.task_updates:
        for tu in report.task_updates:
            task_updates_out.append(DPRTaskUpdateOut(
                id=tu.id,
                task_id=tu.task_id,
                task_title=tu.task_title,
                today_work_summary=tu.today_work_summary,
                status_update=tu.status_update,
                progress_percentage=tu.progress_percentage or 0,
                hours_spent=tu.hours_spent or 0.0,
                remarks=tu.remarks,
                created_at=tu.created_at
            ))

    user_name = report.user.name if report.user else None
    user_email = report.user.email if report.user else None
    user_dept = report.user.department if report.user else None
    user_desig = report.user.designation if report.user else None
    user_emp_id = report.user.employee_id if report.user else None
    user_role = report.user.role.value if report.user else None
    ack_name = report.acknowledger.name if report.acknowledger else None

    return DPROut(
        id=report.id,
        user_id=report.user_id,
        user_name=user_name,
        user_email=user_email,
        user_department=user_dept,
        user_designation=user_desig,
        user_employee_id=user_emp_id,
        user_role=user_role,
        report_date=report.report_date,
        total_hours=report.total_hours or 0.0,
        summary=report.summary,
        challenges=report.challenges,
        plan_for_tomorrow=report.plan_for_tomorrow,
        other_tasks=report.other_tasks or [],
        task_updates=task_updates_out,
        status=report.status,
        admin_remarks=report.admin_remarks,
        acknowledged_by=report.acknowledged_by,
        acknowledged_by_name=ack_name,
        acknowledged_at=report.acknowledged_at,
        document_url=report.document_url,
        drive_file_id=report.drive_file_id,
        drive_file_url=report.drive_file_url,
        drive_folder_url=report.drive_folder_url,
        created_at=report.created_at,
        updated_at=report.updated_at
    )



@router.get("/today-status", response_model=DPRTodayStatusOut)
async def get_today_dpr_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Check if the current user has submitted today's DPR.
    Also calculates submission streak and count of active tasks.
    """
    today_str = get_today_date_str()

    # Query today's DPR for current user
    res = await db.execute(
        select(DailyProgressReport)
        .options(
            selectinload(DailyProgressReport.user),
            selectinload(DailyProgressReport.acknowledger),
            selectinload(DailyProgressReport.task_updates)
        )
        .where(
            and_(
                DailyProgressReport.user_id == current_user.id,
                DailyProgressReport.report_date == today_str
            )
        )
    )
    today_dpr = res.scalar_one_or_none()

    # Query active/pending assigned tasks
    tasks_res = await db.execute(
        select(func.count(Task.id))
        .where(
            and_(
                Task.assigned_to == current_user.id,
                Task.status.in_([TaskStatus.pending, TaskStatus.in_progress])
            )
        )
    )
    pending_tasks_count = tasks_res.scalar() or 0

    all_tasks_res = await db.execute(
        select(func.count(Task.id))
        .where(
            and_(
                Task.assigned_to == current_user.id,
                Task.status != TaskStatus.declined
            )
        )
    )
    assigned_tasks_count = all_tasks_res.scalar() or 0

    # Compute submission streak
    history_res = await db.execute(
        select(DailyProgressReport.report_date)
        .where(DailyProgressReport.user_id == current_user.id)
        .order_by(desc(DailyProgressReport.report_date))
        .limit(30)
    )
    past_dates = [r[0] for r in history_res.all()]
    
    streak = 0
    check_date = datetime.now(timezone.utc).astimezone(IST).date()
    if today_dpr:
        # Include today
        streak += 1
        check_date -= timedelta(days=1)
    else:
        # Check starting from yesterday
        check_date -= timedelta(days=1)

    while True:
        d_str = check_date.strftime("%Y-%m-%d")
        if d_str in past_dates:
            streak += 1
            check_date -= timedelta(days=1)
        else:
            break

    return DPRTodayStatusOut(
        is_submitted=today_dpr is not None,
        report_id=today_dpr.id if today_dpr else None,
        report_date=today_str,
        submitted_at=today_dpr.created_at if today_dpr else None,
        assigned_tasks_count=assigned_tasks_count,
        pending_tasks_count=pending_tasks_count,
        streak_count=streak,
        dpr=build_dpr_out(today_dpr) if today_dpr else None
    )


@router.get("/my-active-tasks", response_model=List[TaskOut])
async def get_my_active_tasks_for_dpr(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get all active/pending/in-progress tasks assigned to the current user
    for filling in the DPR form.
    """
    stmt = (
        select(Task)
        .options(
            selectinload(Task.submissions),
            selectinload(Task.event),
            selectinload(Task.assignee),
            selectinload(Task.subtasks)
        )
        .where(
            and_(
                Task.assigned_to == current_user.id,
                Task.status != TaskStatus.declined
            )
        )
        .order_by(Task.status == TaskStatus.pending, Task.due_date.asc())
    )
    res = await db.execute(stmt)
    tasks = res.scalars().all()
    return [build_task_out(t) for t in tasks]


@router.post("/submit", response_model=DPROut)
async def submit_daily_progress_report(
    payload: DPRCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Submit or update today's DPR.
    Also syncs task status if marked as completed.
    """
    report_date = payload.report_date or get_today_date_str()

    # Check if a DPR already exists for this date
    res = await db.execute(
        select(DailyProgressReport)
        .options(
            selectinload(DailyProgressReport.task_updates)
        )
        .where(
            and_(
                DailyProgressReport.user_id == current_user.id,
                DailyProgressReport.report_date == report_date
            )
        )
    )
    existing_dpr = res.scalar_one_or_none()

    other_tasks_json = [ot.model_dump() for ot in payload.other_tasks]

    # Calculate total hours if not provided or sum from components
    total_hours = payload.total_hours
    if total_hours <= 0:
        tasks_hours = sum(tu.hours_spent for tu in payload.task_updates)
        others_hours = sum(ot.hours_spent for ot in payload.other_tasks)
        total_hours = round(tasks_hours + others_hours, 2)

    if existing_dpr:
        # Update existing report
        existing_dpr.total_hours = total_hours
        existing_dpr.summary = payload.summary
        existing_dpr.challenges = payload.challenges
        existing_dpr.plan_for_tomorrow = payload.plan_for_tomorrow
        existing_dpr.other_tasks = other_tasks_json
        existing_dpr.status = "submitted"
        existing_dpr.updated_at = datetime.now(timezone.utc)

        # Clear previous task updates and re-insert
        existing_dpr.task_updates.clear()
        dpr_obj = existing_dpr
    else:
        # Create new DPR
        dpr_obj = DailyProgressReport(
            user_id=current_user.id,
            report_date=report_date,
            total_hours=total_hours,
            summary=payload.summary,
            challenges=payload.challenges,
            plan_for_tomorrow=payload.plan_for_tomorrow,
            other_tasks=other_tasks_json,
            status="submitted",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        db.add(dpr_obj)
        await db.flush()

    # Add task updates
    for item in payload.task_updates:
        update_obj = DPRTaskUpdate(
            dpr_id=dpr_obj.id,
            task_id=item.task_id,
            task_title=item.task_title,
            today_work_summary=item.today_work_summary,
            status_update=item.status_update,
            progress_percentage=item.progress_percentage,
            hours_spent=item.hours_spent,
            remarks=item.remarks,
            created_at=datetime.now(timezone.utc)
        )
        db.add(update_obj)

        # Update underlying task status if marked completed and still pending
        if item.status_update == "completed":
            task_res = await db.execute(select(Task).where(Task.id == item.task_id))
            target_task = task_res.scalar_one_or_none()
            if target_task and target_task.status in [TaskStatus.pending, TaskStatus.in_progress]:
                target_task.status = TaskStatus.submitted

    await db.commit()

    # Re-fetch full DPR with relationships
    final_res = await db.execute(
        select(DailyProgressReport)
        .options(
            selectinload(DailyProgressReport.user),
            selectinload(DailyProgressReport.acknowledger),
            selectinload(DailyProgressReport.task_updates)
        )
        .where(DailyProgressReport.id == dpr_obj.id)
    )
    final_dpr = final_res.scalar_one()

    # Generate official document and archive to DSW/DPR/{report_date}/
    try:
        doc_url = save_dpr_document_to_archive(final_dpr, current_user)
        final_dpr.document_url = doc_url

        # Sync to Google Drive in DSW > DPR > {report_date}
        html_content = generate_dpr_html(final_dpr, current_user)
        drive_sync_res = await sync_dpr_to_google_drive(final_dpr, current_user, html_content)
        final_dpr.drive_file_id = drive_sync_res.get("drive_file_id")
        final_dpr.drive_file_url = drive_sync_res.get("drive_file_url")
        final_dpr.drive_folder_url = drive_sync_res.get("drive_folder_url")

        await db.commit()
    except Exception as e:
        print(f"[DPR Document/Drive Sync Note]: {e}")

    # Log audit
    await log_audit(
        db,
        actor_id=current_user.id,
        action="DPR_SUBMITTED",
        entity_type="daily_progress_report",
        entity_id=final_dpr.id,
        meta={
            "date": report_date,
            "total_hours": total_hours,
            "tasks_count": len(payload.task_updates),
            "drive_folder": f"DSW/DPR/{report_date}"
        }
    )

    return build_dpr_out(final_dpr)


@router.get("/my-history", response_model=List[DPROut])
async def get_my_dpr_history(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get all past DPR submissions for the logged in user.
    """
    res = await db.execute(
        select(DailyProgressReport)
        .options(
            selectinload(DailyProgressReport.user),
            selectinload(DailyProgressReport.acknowledger),
            selectinload(DailyProgressReport.task_updates)
        )
        .where(DailyProgressReport.user_id == current_user.id)
        .order_by(desc(DailyProgressReport.report_date))
    )
    reports = res.scalars().all()
    return [build_dpr_out(r) for r in reports]


@router.get("/{dpr_id}", response_model=DPROut)
async def get_dpr_by_id(
    dpr_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get detailed DPR by ID.
    Accessible by the report owner or super admin.
    """
    res = await db.execute(
        select(DailyProgressReport)
        .options(
            selectinload(DailyProgressReport.user),
            selectinload(DailyProgressReport.acknowledger),
            selectinload(DailyProgressReport.task_updates)
        )
        .where(DailyProgressReport.id == dpr_id)
    )
    report = res.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="Daily progress report not found")

    if report.user_id != current_user.id and current_user.role != UserRole.super_admin:
        raise HTTPException(status_code=403, detail="Not authorized to view this report")

    return build_dpr_out(report)


@router.get("/{dpr_id}/document", response_class=HTMLResponse)
async def get_dpr_html_document(
    dpr_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Renders official Geeta University DSW Daily Progress Report document
    suitable for instant browser viewing, printing, and PDF export.
    """
    res = await db.execute(
        select(DailyProgressReport)
        .options(
            selectinload(DailyProgressReport.user),
            selectinload(DailyProgressReport.acknowledger),
            selectinload(DailyProgressReport.task_updates)
        )
        .where(DailyProgressReport.id == dpr_id)
    )
    report = res.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="Daily progress report not found")

    if report.user_id != current_user.id and current_user.role != UserRole.super_admin:
        raise HTTPException(status_code=403, detail="Not authorized to view this document")

    employee = report.user
    html_content = generate_dpr_html(report, employee)
    return HTMLResponse(content=html_content, status_code=200)


# =========================================================================
# ADMIN DPR MONITORING & MANAGEMENT ENDPOINTS
# =========================================================================


@router.get("/admin/daily-overview", response_model=DPRAdminOverviewOut)
async def get_admin_daily_dpr_overview(
    date: Optional[str] = None,
    department: Optional[str] = None,
    current_user: User = Depends(require_role([UserRole.super_admin])),
    db: AsyncSession = Depends(get_db)
):
    """
    (Super Admin only) Get comprehensive DPR submission status for a specific date (default today).
    Includes:
    - Submission metrics (Total employees, Submitted, Missing, Hours logged)
    - List of employees who haven't submitted
    - Full list of submitted reports with details
    """
    target_date = date or get_today_date_str()

    # Query all active faculty and relevant staff members
    emp_query = select(User).where(
        and_(
            User.is_active == True,
            User.role == UserRole.faculty
        )
    )
    if department:
        emp_query = emp_query.where(User.department == department)

    emp_res = await db.execute(emp_query)
    all_employees = emp_res.scalars().all()
    total_employees_count = len(all_employees)

    # Query all DPR submissions for this date
    dpr_query = (
        select(DailyProgressReport)
        .options(
            selectinload(DailyProgressReport.user),
            selectinload(DailyProgressReport.acknowledger),
            selectinload(DailyProgressReport.task_updates)
        )
        .where(DailyProgressReport.report_date == target_date)
        .order_by(desc(DailyProgressReport.created_at))
    )
    dpr_res = await db.execute(dpr_query)
    submitted_reports = dpr_res.scalars().all()

    # If department filter applied, filter submissions
    if department:
        submitted_reports = [r for r in submitted_reports if r.user and r.user.department == department]

    submitted_user_ids = {r.user_id for r in submitted_reports}
    submitted_count = len(submitted_reports)
    pending_count = max(0, total_employees_count - submitted_count)
    submission_rate = round((submitted_count / total_employees_count * 100), 1) if total_employees_count > 0 else 0.0
    total_hours = sum(r.total_hours or 0.0 for r in submitted_reports)

    # Build missing employees list
    missing_employees: List[MissingEmployeeOut] = []
    for emp in all_employees:
        if emp.id not in submitted_user_ids:
            # Check active tasks count for this employee
            task_cnt_res = await db.execute(
                select(func.count(Task.id)).where(
                    and_(
                        Task.assigned_to == emp.id,
                        Task.status.in_([TaskStatus.pending, TaskStatus.in_progress])
                    )
                )
            )
            active_cnt = task_cnt_res.scalar() or 0

            # Check last DPR date
            last_dpr_res = await db.execute(
                select(DailyProgressReport.report_date)
                .where(DailyProgressReport.user_id == emp.id)
                .order_by(desc(DailyProgressReport.report_date))
                .limit(1)
            )
            last_date_row = last_dpr_res.first()
            last_dpr_date = last_date_row[0] if last_date_row else None

            missing_employees.append(MissingEmployeeOut(
                id=emp.id,
                name=emp.name,
                email=emp.email,
                department=emp.department,
                designation=emp.designation,
                employee_id=emp.employee_id,
                role=emp.role.value,
                active_tasks_count=active_cnt,
                last_dpr_date=last_dpr_date
            ))

    return DPRAdminOverviewOut(
        date=target_date,
        total_employees=total_employees_count,
        submitted_count=submitted_count,
        pending_count=pending_count,
        submission_rate_percentage=submission_rate,
        total_hours_logged=round(total_hours, 2),
        missing_employees=missing_employees,
        submissions=[build_dpr_out(r) for r in submitted_reports]
    )


@router.get("/admin/all", response_model=List[DPROut])
async def get_all_dprs_admin(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    department: Optional[str] = None,
    user_id: Optional[int] = None,
    current_user: User = Depends(require_role([UserRole.super_admin])),
    db: AsyncSession = Depends(get_db)
):
    """
    (Super Admin only) Query all historical DPR submissions with advanced filters.
    """
    stmt = (
        select(DailyProgressReport)
        .options(
            selectinload(DailyProgressReport.user),
            selectinload(DailyProgressReport.acknowledger),
            selectinload(DailyProgressReport.task_updates)
        )
        .order_by(desc(DailyProgressReport.report_date), desc(DailyProgressReport.created_at))
    )

    if date_from:
        stmt = stmt.where(DailyProgressReport.report_date >= date_from)
    if date_to:
        stmt = stmt.where(DailyProgressReport.report_date <= date_to)
    if user_id:
        stmt = stmt.where(DailyProgressReport.user_id == user_id)

    res = await db.execute(stmt)
    reports = res.scalars().all()

    if department:
        reports = [r for r in reports if r.user and r.user.department == department]

    return [build_dpr_out(r) for r in reports]


@router.post("/admin/{dpr_id}/acknowledge", response_model=DPROut)
async def acknowledge_dpr(
    dpr_id: int,
    payload: DPRAcknowledgeRequest,
    current_user: User = Depends(require_role([UserRole.super_admin])),
    db: AsyncSession = Depends(get_db)
):
    """
    (Super Admin only) Acknowledge employee DPR and provide feedback or remarks.
    """
    res = await db.execute(
        select(DailyProgressReport)
        .options(
            selectinload(DailyProgressReport.user),
            selectinload(DailyProgressReport.acknowledger),
            selectinload(DailyProgressReport.task_updates)
        )
        .where(DailyProgressReport.id == dpr_id)
    )
    report = res.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="Daily progress report not found")

    report.status = payload.status or "acknowledged"
    report.admin_remarks = payload.admin_remarks
    report.acknowledged_by = current_user.id
    report.acknowledged_at = datetime.now(timezone.utc)
    report.updated_at = datetime.now(timezone.utc)

    await db.commit()

    # Send in-app notification to employee
    remarks_suffix = f" Remarks: '{payload.admin_remarks}'" if payload.admin_remarks else ""
    await create_notification(
        db,
        user_id=report.user_id,
        title="DPR Acknowledged by DSW Office",
        body=f"Your Daily Progress Report for {report.report_date} has been acknowledged.{remarks_suffix}",
        type="dpr_acknowledged",
        link="/faculty/dpr"
    )

    await log_audit(
        db,
        actor_id=current_user.id,
        action="DPR_ACKNOWLEDGED",
        entity_type="daily_progress_report",
        entity_id=report.id,
        meta={"report_date": report.report_date, "faculty_id": report.user_id}
    )

    return build_dpr_out(report)


@router.post("/admin/send-reminders")
async def send_dpr_reminders(
    current_user: User = Depends(require_role([UserRole.super_admin])),
    db: AsyncSession = Depends(get_db)
):
    """
    (Super Admin only) Send instant notification reminder to all active employees
    who have not submitted today's DPR.
    """
    today_str = get_today_date_str()

    # Query all active faculty
    emp_res = await db.execute(
        select(User).where(
            and_(
                User.is_active == True,
                User.role == UserRole.faculty
            )
        )
    )
    all_employees = emp_res.scalars().all()

    # Query submitted user ids today
    dpr_res = await db.execute(
        select(DailyProgressReport.user_id).where(DailyProgressReport.report_date == today_str)
    )
    submitted_ids = {r[0] for r in dpr_res.all()}

    reminded_count = 0
    for emp in all_employees:
        if emp.id not in submitted_ids:
            await create_notification(
                db,
                user_id=emp.id,
                title="⚠️ Daily Progress Report (DPR) Pending",
                body=f"Dear {emp.name}, your DPR for today ({today_str}) is pending. Please log in and submit your daily task updates before end of day.",
                type="dpr_reminder",
                link="/faculty/dpr"
            )
            reminded_count += 1

    await log_audit(
        db,
        actor_id=current_user.id,
        action="DPR_REMINDERS_BROADCAST",
        entity_type="daily_progress_report",
        entity_id=None,
        meta={"date": today_str, "reminders_sent": reminded_count}
    )

    return {
        "success": True,
        "message": f"DPR reminders successfully sent to {reminded_count} faculty/staff members.",
        "reminders_sent": reminded_count,
        "date": today_str
    }
