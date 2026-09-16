from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, inspect
from sqlalchemy.orm import selectinload
from typing import List, Optional
from datetime import datetime, timezone
from app.database import get_db
from app.core.deps import get_current_user, require_role
from app.models.all_models import User, UserRole, Task, TaskSubmission, TaskStatus, FacultyPerformanceLedger, Event
from app.schemas.schemas import TaskCreate, TaskUpdate, TaskOut, TaskSubmissionCreate, TaskReviewPayload
from app.core.scoring_rules import calculate_faculty_task_score, FACULTY_SCORE_DECLINED
from app.services.notification_service import create_notification, log_audit
from app.core.cache import ttl_cache

router = APIRouter(prefix="/api/tasks", tags=["Tasks"])

def build_task_out(t: Task) -> TaskOut:
    state = inspect(t)
    
    submissions_out = []
    if "submissions" not in state.unloaded and t.submissions:
        for s in t.submissions:
            s_state = inspect(s)
            submitter_val = s.submitter if "submitter" not in s_state.unloaded else None
            submissions_out.append({
                "id": s.id,
                "task_id": s.task_id,
                "submitted_by": s.submitted_by,
                "submitter": submitter_val,
                "description": s.description,
                "file_url": s.file_url,
                "file_type": s.file_type,
                "file_name": s.file_name,
                "file_size": s.file_size,
                "submitted_at": s.submitted_at,
                "review_status": s.review_status,
                "reviewed_by": s.reviewed_by,
                "review_remarks": s.review_remarks,
                "reviewed_at": s.reviewed_at
            })

    subtasks_out = []
    if "subtasks" not in state.unloaded and hasattr(t, "subtasks") and t.subtasks:
        for st in t.subtasks:
            subtasks_out.append(build_task_out(st))

    event_title = None
    if "event" not in state.unloaded and t.event:
        event_title = t.event.title

    assignee_val = None
    if "assignee" not in state.unloaded and t.assignee:
        assignee_val = t.assignee

    return TaskOut(
        id=t.id,
        title=t.title,
        description=t.description,
        task_type=t.task_type,
        event_id=t.event_id,
        event_title=event_title,
        parent_task_id=t.parent_task_id,
        assigned_to=t.assigned_to,
        assignee=assignee_val,
        assigned_by=t.assigned_by,
        start_date=t.start_date if hasattr(t, "start_date") else None,
        due_date=t.due_date,
        priority=t.priority,
        status=t.status,
        created_at=t.created_at,
        submissions=submissions_out,
        subtasks=subtasks_out
    )

@router.post("", response_model=TaskOut)
async def create_task(
    payload: TaskCreate,
    current_user: User = Depends(require_role([UserRole.super_admin, UserRole.faculty])),
    db: AsyncSession = Depends(get_db)
):
    parent_task = None
    if payload.parent_task_id:
        p_res = await db.execute(select(Task).where(Task.id == payload.parent_task_id))
        parent_task = p_res.scalar_one_or_none()
        if not parent_task:
            raise HTTPException(status_code=404, detail="Parent task not found")

    if current_user.role == UserRole.faculty:
        # Faculty creating their own task proposal/duty or subtask
        if parent_task:
            if parent_task.assigned_to != current_user.id:
                raise HTTPException(status_code=403, detail="You can only add subtasks to tasks assigned to you")
            assigned_to = parent_task.assigned_to
            event_id = payload.event_id if payload.event_id is not None else parent_task.event_id
            task_type = "subtask"
        else:
            assigned_to = current_user.id
            event_id = payload.event_id
            task_type = payload.task_type or "self_created"

        assigned_by = current_user.id
        initial_status = TaskStatus.submitted # Self-created tasks/subtasks require admin approval

        task = Task(
            title=payload.title,
            description=payload.description,
            task_type=task_type,
            event_id=event_id,
            parent_task_id=payload.parent_task_id,
            assigned_to=assigned_to,
            assigned_by=assigned_by,
            start_date=payload.start_date,
            due_date=payload.due_date,
            priority=payload.priority,
            status=initial_status
        )
        db.add(task)
        await db.flush() # obtain task.id

        # Attach initial submission record if file or description is provided
        submission = TaskSubmission(
            task_id=task.id,
            submitted_by=current_user.id,
            description=payload.description or ("Faculty subtask submission" if parent_task else "Faculty self-created task submission"),
            file_url=payload.file_url,
            file_name=payload.file_name,
            file_type=payload.file_type,
            file_size=payload.file_size,
            review_status="pending"
        )
        db.add(submission)
        await db.commit()

        # Re-query task with relations
        res = await db.execute(
            select(Task)
            .options(
                selectinload(Task.assignee),
                selectinload(Task.event),
                selectinload(Task.submissions).selectinload(TaskSubmission.submitter),
                selectinload(Task.subtasks).selectinload(Task.assignee),
                selectinload(Task.subtasks).selectinload(Task.event),
                selectinload(Task.subtasks).selectinload(Task.submissions)
            )
            .where(Task.id == task.id)
        )
        created_task = res.scalar_one()

        # Notify Super Admins
        item_kind = "Subtask" if parent_task else "Faculty Task"
        admin_res = await db.execute(select(User).where(User.role == UserRole.super_admin))
        admins = admin_res.scalars().all()
        for admin in admins:
            await create_notification(
                db,
                title=f"New {item_kind} Request 📋",
                body=f"Faculty {current_user.name} submitted {item_kind.lower()}: '{task.title}' for approval",
                type="task_request",
                user_id=admin.id,
                link="/admin/requests"
            )

        await log_audit(db, action="CREATE_FACULTY_TASK_REQUEST", entity_type="task", actor_id=current_user.id, entity_id=task.id, meta={"title": task.title, "faculty": current_user.name, "parent_task_id": payload.parent_task_id})
        await db.commit()

        ttl_cache.invalidate("dashboard_")
        ttl_cache.invalidate("lb_staff_")

        return build_task_out(created_task)

    # Admin creating task or subtask assigned to faculty
    if parent_task:
        # Strict Rule: Subtask is strictly locked to the parent task assignee
        assigned_to = parent_task.assigned_to
        event_id = payload.event_id if payload.event_id is not None else parent_task.event_id
        task_type = "subtask"
    else:
        if not payload.assigned_to:
            raise HTTPException(status_code=400, detail="Assigned faculty member must be specified")
        assigned_to = payload.assigned_to
        event_id = payload.event_id
        task_type = payload.task_type or "standalone"

    fac_res = await db.execute(select(User).where(User.id == assigned_to, User.role == UserRole.faculty))
    faculty = fac_res.scalar_one_or_none()
    if not faculty:
        raise HTTPException(status_code=400, detail="Assigned user must be a registered faculty member")

    task = Task(
        title=payload.title,
        description=payload.description,
        task_type=task_type,
        event_id=event_id,
        parent_task_id=payload.parent_task_id,
        assigned_to=assigned_to,
        assigned_by=current_user.id,
        start_date=payload.start_date,
        due_date=payload.due_date,
        priority=payload.priority,
        status=TaskStatus.pending
    )
    db.add(task)
    await db.commit()

    # Re-query task with relations
    res = await db.execute(
        select(Task)
        .options(
            selectinload(Task.assignee),
            selectinload(Task.event),
            selectinload(Task.submissions),
            selectinload(Task.subtasks).selectinload(Task.assignee),
            selectinload(Task.subtasks).selectinload(Task.event),
            selectinload(Task.subtasks).selectinload(Task.submissions)
        )
        .where(Task.id == task.id)
    )
    created_task = res.scalar_one()

    # Send Notification to faculty
    item_name = "subtask" if payload.parent_task_id else "task"
    await create_notification(
        db,
        title=f"New {item_name.title()} Assigned",
        body=f"You have been assigned {item_name}: '{task.title}'",
        type="task_assigned",
        user_id=faculty.id,
        link="/faculty/tasks"
    )
    await log_audit(db, action="CREATE_TASK", entity_type="task", actor_id=current_user.id, entity_id=task.id, meta={"title": task.title, "assignee": faculty.name, "parent_task_id": payload.parent_task_id})
    await db.commit()

    ttl_cache.invalidate("dashboard_")
    ttl_cache.invalidate("lb_staff_")

    return build_task_out(created_task)


@router.get("/requests", response_model=List[TaskOut])
async def list_task_requests(
    status_filter: Optional[str] = None,
    type_filter: Optional[str] = None,
    faculty_id: Optional[int] = None,
    faculty_name: Optional[str] = None,
    event_id: Optional[int] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    priority: Optional[str] = None,
    search: Optional[str] = None,
    current_user: User = Depends(require_role([UserRole.super_admin])),
    db: AsyncSession = Depends(get_db)
):
    query = select(Task).options(
        selectinload(Task.assignee),
        selectinload(Task.event),
        selectinload(Task.submissions).selectinload(TaskSubmission.submitter),
        selectinload(Task.subtasks).selectinload(Task.assignee),
        selectinload(Task.subtasks).selectinload(Task.event),
        selectinload(Task.subtasks).selectinload(Task.submissions).selectinload(TaskSubmission.submitter)
    )

    if faculty_id:
        query = query.where(Task.assigned_to == faculty_id)

    if event_id:
        query = query.where(Task.event_id == event_id)

    if type_filter == "self_created":
        query = query.where(Task.assigned_by == Task.assigned_to)
    elif type_filter == "assigned_duty":
        query = query.where(Task.assigned_by != Task.assigned_to)

    if priority:
        query = query.where(Task.priority == priority)

    if from_date:
        try:
            from_dt = datetime.fromisoformat(from_date.replace("Z", "+00:00"))
            query = query.where((Task.due_date >= from_dt) | (Task.start_date >= from_dt) | (Task.created_at >= from_dt))
        except Exception:
            pass

    if to_date:
        try:
            to_dt = datetime.fromisoformat(to_date.replace("Z", "+00:00"))
            query = query.where((Task.due_date <= to_dt) | (Task.start_date <= to_dt) | (Task.created_at <= to_dt))
        except Exception:
            pass

    if status_filter and status_filter != "all":
        if status_filter == "pending":
            query = query.where(Task.status.in_([TaskStatus.pending, TaskStatus.submitted]))
        elif status_filter == "submitted":
            query = query.where(Task.status == TaskStatus.submitted)
        elif status_filter == "approved":
            query = query.where(Task.status == TaskStatus.approved)
        elif status_filter == "declined":
            query = query.where(Task.status == TaskStatus.declined)
        else:
            query = query.where(Task.status == status_filter)

    if faculty_name:
        query = query.join(Task.assignee).where(User.name.ilike(f"%{faculty_name}%"))

    if search:
        query = query.where(Task.title.ilike(f"%{search}%") | Task.description.ilike(f"%{search}%"))

    result = await db.execute(query.order_by(Task.created_at.desc()))
    tasks = result.scalars().all()
    return [build_task_out(t) for t in tasks]


@router.get("", response_model=List[TaskOut])
async def list_tasks(
    assigned_to: Optional[int] = None,
    status_filter: Optional[str] = None,
    event_id: Optional[int] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    priority: Optional[str] = None,
    search: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    query = select(Task).options(
        selectinload(Task.assignee),
        selectinload(Task.event),
        selectinload(Task.submissions).selectinload(TaskSubmission.submitter),
        selectinload(Task.subtasks).selectinload(Task.assignee),
        selectinload(Task.subtasks).selectinload(Task.event),
        selectinload(Task.subtasks).selectinload(Task.submissions).selectinload(TaskSubmission.submitter)
    )

    if current_user.role == UserRole.faculty:
        query = query.where(Task.assigned_to == current_user.id)
    elif assigned_to:
        query = query.where(Task.assigned_to == assigned_to)

    if status_filter:
        query = query.where(Task.status == status_filter)
    if event_id:
        query = query.where(Task.event_id == event_id)
    if priority:
        query = query.where(Task.priority == priority)

    if from_date:
        try:
            from_dt = datetime.fromisoformat(from_date.replace("Z", "+00:00"))
            query = query.where((Task.due_date >= from_dt) | (Task.start_date >= from_dt) | (Task.created_at >= from_dt))
        except Exception:
            pass

    if to_date:
        try:
            to_dt = datetime.fromisoformat(to_date.replace("Z", "+00:00"))
            query = query.where((Task.due_date <= to_dt) | (Task.start_date <= to_dt) | (Task.created_at <= to_dt))
        except Exception:
            pass

    if search:
        query = query.where(Task.title.ilike(f"%{search}%"))

    result = await db.execute(query.order_by(Task.created_at.desc()))
    tasks = result.scalars().all()

    # Filter top-level tasks if viewing list, subtasks attached inside
    top_tasks = [t for t in tasks if t.parent_task_id is None] if not search else tasks
    return [build_task_out(t) for t in top_tasks]


@router.get("/mine", response_model=List[TaskOut])
async def get_my_tasks(
    current_user: User = Depends(require_role([UserRole.faculty])),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(Task)
        .options(
            selectinload(Task.assignee), 
            selectinload(Task.event), 
            selectinload(Task.submissions).selectinload(TaskSubmission.submitter),
            selectinload(Task.subtasks).selectinload(Task.assignee),
            selectinload(Task.subtasks).selectinload(Task.event),
            selectinload(Task.subtasks).selectinload(Task.submissions).selectinload(TaskSubmission.submitter)
        )
        .where(Task.assigned_to == current_user.id, Task.parent_task_id.is_(None))
        .order_by(Task.created_at.desc())
    )
    tasks = result.scalars().all()
    return [build_task_out(t) for t in tasks]


@router.get("/{task_id}", response_model=TaskOut)
async def get_task_detail(
    task_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(Task)
        .options(
            selectinload(Task.assignee),
            selectinload(Task.event),
            selectinload(Task.submissions).selectinload(TaskSubmission.submitter),
            selectinload(Task.subtasks).selectinload(Task.assignee),
            selectinload(Task.subtasks).selectinload(Task.event),
            selectinload(Task.subtasks).selectinload(Task.submissions)
        )
        .where(Task.id == task_id)
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if current_user.role == UserRole.faculty and task.assigned_to != current_user.id:
        raise HTTPException(status_code=403, detail="You do not have access to this task")

    return build_task_out(task)

@router.post("/{task_id}/submit", response_model=TaskOut)
async def submit_task(
    task_id: int,
    payload: TaskSubmissionCreate,
    current_user: User = Depends(require_role([UserRole.faculty])),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.assigned_to != current_user.id:
        raise HTTPException(status_code=403, detail="You are not assigned to this task")

    submission = TaskSubmission(
        task_id=task.id,
        submitted_by=current_user.id,
        description=payload.description,
        file_url=payload.file_url,
        file_type=payload.file_type,
        file_name=payload.file_name,
        file_size=payload.file_size,
        review_status="pending"
    )
    db.add(submission)

    task.status = TaskStatus.submitted
    await db.commit()

    # Notify admin
    admin_res = await db.execute(select(User).where(User.role == UserRole.super_admin))
    admins = admin_res.scalars().all()
    item_type = "Subtask" if task.parent_task_id else "Task"
    for admin in admins:
        await create_notification(
            db,
            title=f"{item_type} Submitted for Review 📋",
            body=f"Faculty {current_user.name} submitted {item_type.lower()}: '{task.title}'",
            type="task_submitted",
            user_id=admin.id,
            link="/admin/requests"
        )

    await log_audit(db, action="SUBMIT_TASK", entity_type="task", actor_id=current_user.id, entity_id=task.id)
    await db.commit()

    return await get_task_detail(task_id, current_user, db)

@router.post("/{task_id}/approve", response_model=TaskOut)
async def approve_task(
    task_id: int,
    payload: Optional[TaskReviewPayload] = None,
    current_user: User = Depends(require_role([UserRole.super_admin])),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(Task).options(selectinload(Task.submissions)).where(Task.id == task_id)
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    now = datetime.now(timezone.utc)
    is_late = bool(task.due_date and task.due_date.tzinfo is None and task.due_date < now.replace(tzinfo=None)) or \
              bool(task.due_date and task.due_date.tzinfo is not None and task.due_date < now)

    already_approved = (str(task.status.value if hasattr(task.status, 'value') else task.status) == "approved")

    task.status = TaskStatus.approved

    # Update latest submission review or create one if none exists
    if task.submissions:
        sub = sorted(task.submissions, key=lambda s: s.id)[-1]
        sub.review_status = "approved"
        sub.reviewed_by = current_user.id
        sub.reviewed_at = now
        sub.review_remarks = payload.review_remarks if payload else "Approved by Admin"
    else:
        sub = TaskSubmission(
            task_id=task.id,
            submitted_by=task.assigned_to,
            description=task.description or "Approved by Admin",
            review_status="approved",
            reviewed_by=current_user.id,
            reviewed_at=now,
            review_remarks=payload.review_remarks if payload else "Approved by Admin"
        )
        db.add(sub)

    is_subtask = (task.parent_task_id is not None)
    score_delta = 0 if is_subtask else calculate_faculty_task_score(is_late)

    # Faculty Performance Ledger Entry (+10 for on-time, +5 for late ONLY on main tasks; subtasks award +0)
    if not already_approved and not is_subtask:
        ledger_entry = FacultyPerformanceLedger(
            faculty_id=task.assigned_to,
            score_delta=score_delta,
            source_type="task_approved",
            source_id=task.id,
            note=f"Approved on-time (+10)" if not is_late else "Approved late (+5)"
        )
        db.add(ledger_entry)
        await db.commit()

    # Notify faculty member
    if is_subtask:
        notif_title = "Subtask Approved! 🎉"
        notif_body = f"Your subtask '{task.title}' has been approved by DSW."
    else:
        notif_title = "Task Approved! 🎉"
        notif_body = f"Your task submission for '{task.title}' has been approved by DSW (+{score_delta} leaderboard pts)."

    await create_notification(
        db,
        title=notif_title,
        body=notif_body,
        type="task_approved",
        user_id=task.assigned_to,
        link=f"/faculty/tasks"
    )
    await log_audit(db, action="APPROVE_SUBTASK" if is_subtask else "APPROVE_TASK", entity_type="task", actor_id=current_user.id, entity_id=task.id, meta={"score_delta": score_delta, "is_subtask": is_subtask})
    await db.commit()

    ttl_cache.invalidate("dashboard_")
    ttl_cache.invalidate("lb_staff_")

    return await get_task_detail(task_id, current_user, db)

@router.post("/{task_id}/decline", response_model=TaskOut)
async def decline_task(
    task_id: int,
    payload: TaskReviewPayload,
    current_user: User = Depends(require_role([UserRole.super_admin])),
    db: AsyncSession = Depends(get_db)
):
    if not payload.review_remarks or not payload.review_remarks.strip():
        raise HTTPException(status_code=400, detail="Mandatory review remarks explaining the rejection must be provided.")

    result = await db.execute(
        select(Task).options(selectinload(Task.submissions)).where(Task.id == task_id)
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    now = datetime.now(timezone.utc)
    task.status = TaskStatus.declined

    if task.submissions:
        sub = sorted(task.submissions, key=lambda s: s.id)[-1]
        sub.review_status = "declined"
        sub.reviewed_by = current_user.id
        sub.reviewed_at = now
        sub.review_remarks = payload.review_remarks
    else:
        sub = TaskSubmission(
            task_id=task.id,
            submitted_by=task.assigned_to,
            description=task.description or "Task proposal",
            review_status="declined",
            reviewed_by=current_user.id,
            reviewed_at=now,
            review_remarks=payload.review_remarks
        )
        db.add(sub)

    is_subtask = (task.parent_task_id is not None)

    # Faculty Performance Ledger Entry (-3 for decline on both tasks & subtasks)
    ledger_entry = FacultyPerformanceLedger(
        faculty_id=task.assigned_to,
        score_delta=FACULTY_SCORE_DECLINED, # -3
        source_type="subtask_declined" if is_subtask else "task_declined",
        source_id=task.id,
        note=f"Subtask declined by admin ({FACULTY_SCORE_DECLINED})" if is_subtask else f"Declined by admin ({FACULTY_SCORE_DECLINED})"
    )
    db.add(ledger_entry)
    await db.commit()

    item_label = "subtask" if is_subtask else "task"
    await create_notification(
        db,
        title=f"{item_label.title()} Declined (-3 pts)",
        body=f"Your {item_label} '{task.title}' was declined by DSW (-3 pts penalty). Remark: '{payload.review_remarks}'",
        type="task_declined",
        user_id=task.assigned_to,
        link="/faculty/tasks"
    )
    await log_audit(db, action="DECLINE_SUBTASK" if is_subtask else "DECLINE_TASK", entity_type="task", actor_id=current_user.id, entity_id=task.id, meta={"remarks": payload.review_remarks, "score_delta": FACULTY_SCORE_DECLINED, "is_subtask": is_subtask})
    await db.commit()

    ttl_cache.invalidate("dashboard_")
    ttl_cache.invalidate("lb_staff_")

    return await get_task_detail(task_id, current_user, db)

@router.patch("/{task_id}", response_model=TaskOut)
async def update_task(
    task_id: int,
    payload: TaskUpdate,
    current_user: User = Depends(require_role([UserRole.super_admin])),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    old_assignee = task.assigned_to
    data = payload.model_dump(exclude_unset=True)

    if task.parent_task_id is not None and "assigned_to" in data and data["assigned_to"] is not None:
        p_res = await db.execute(select(Task).where(Task.id == task.parent_task_id))
        parent_task = p_res.scalar_one_or_none()
        if parent_task and data["assigned_to"] != parent_task.assigned_to:
            raise HTTPException(status_code=400, detail="Subtask assignee is locked to the parent task assignee and cannot be changed independently.")

    if "assigned_to" in data and data["assigned_to"] is not None:
        fac_res = await db.execute(select(User).where(User.id == data["assigned_to"], User.role == UserRole.faculty))
        faculty = fac_res.scalar_one_or_none()
        if not faculty:
            raise HTTPException(status_code=400, detail="Assigned user must be a registered faculty member")

    for key, value in data.items():
        setattr(task, key, value)

    await db.commit()

    # If top-level task assignee was changed, cascade to all child subtasks
    if task.parent_task_id is None and "assigned_to" in data and data["assigned_to"] != old_assignee:
        from sqlalchemy import update
        await db.execute(
            update(Task).where(Task.parent_task_id == task.id).values(assigned_to=data["assigned_to"])
        )
        await db.commit()

    if "assigned_to" in data and data["assigned_to"] != old_assignee:
        await create_notification(
            db,
            title="Task Re-assigned to You",
            body=f"You have been assigned task: '{task.title}'",
            type="task_assigned",
            user_id=task.assigned_to,
            link="/faculty/tasks"
        )
        await db.commit()

    await log_audit(db, action="UPDATE_TASK", entity_type="task", actor_id=current_user.id, entity_id=task.id)
    await db.commit()

    ttl_cache.invalidate("dashboard_")
    ttl_cache.invalidate("lb_staff_")

    return await get_task_detail(task_id, current_user, db)

@router.delete("/{task_id}")
async def delete_task(
    task_id: int,
    current_user: User = Depends(require_role([UserRole.super_admin])),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
        
    await db.delete(task)
    await db.commit()

    ttl_cache.invalidate("dashboard_")
    ttl_cache.invalidate("lb_staff_")

    return {"message": "Task deleted successfully"}

