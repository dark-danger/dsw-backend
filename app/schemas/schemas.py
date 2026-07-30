from pydantic import BaseModel, EmailStr, Field
from typing import List, Optional, Any, Dict
from datetime import datetime
from app.models.all_models import UserRole, EventStatus, TaskPriority, TaskStatus, AnnouncementAudience, QueryStatus, SubmissionMode

# --- AUTH & USER SCHEMAS ---
class LoginRequest(BaseModel):
    email: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: "UserOut"

class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str

class UserOut(BaseModel):
    id: int
    name: str
    email: str
    phone: Optional[str] = None
    role: UserRole
    department: Optional[str] = None
    designation: Optional[str] = None
    employee_id: Optional[str] = None
    roll_number: Optional[str] = None
    course_branch: Optional[str] = None
    year: Optional[str] = None
    profile_photo_url: Optional[str] = None
    is_active: bool
    must_change_password: bool
    created_at: datetime

    class Config:
        from_attributes = True

class FacultyCreate(BaseModel):
    name: str
    email: EmailStr
    phone: Optional[str] = None
    department: str
    designation: str
    employee_id: str
    password: Optional[str] = "Faculty@123"

class FacultyUpdate(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    department: Optional[str] = None
    designation: Optional[str] = None
    is_active: Optional[bool] = None

class StudentImportRow(BaseModel):
    name: str
    email: EmailStr
    roll_number: str
    course_branch: str
    year: str
    phone: Optional[str] = None

class FacultyStatsOut(BaseModel):
    faculty_id: int
    faculty_name: str
    total_assigned: int
    completed_approved: int
    pending_count: int
    declined_count: int
    completion_rate_percentage: float
    performance_score: int


# --- TASK SCHEMAS ---
class TaskCreate(BaseModel):
    title: str
    description: Optional[str] = None
    task_type: str = "standalone" # standalone / event_linked
    event_id: Optional[int] = None
    parent_task_id: Optional[int] = None
    assigned_to: int
    due_date: Optional[datetime] = None
    priority: TaskPriority = TaskPriority.medium

class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    assigned_to: Optional[int] = None
    event_id: Optional[int] = None
    due_date: Optional[datetime] = None
    priority: Optional[TaskPriority] = None

class TaskSubmissionOut(BaseModel):
    id: int
    task_id: int
    submitted_by: int
    submitter: Optional[UserOut] = None
    description: Optional[str] = None
    file_url: Optional[str] = None
    file_type: Optional[str] = None
    file_name: Optional[str] = None
    file_size: Optional[int] = None
    submitted_at: datetime
    review_status: str
    reviewed_by: Optional[int] = None
    review_remarks: Optional[str] = None
    reviewed_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class TaskOut(BaseModel):
    id: int
    title: str
    description: Optional[str] = None
    task_type: str
    event_id: Optional[int] = None
    event_title: Optional[str] = None
    parent_task_id: Optional[int] = None
    assigned_to: int
    assignee: Optional[UserOut] = None
    assigned_by: int
    due_date: Optional[datetime] = None
    priority: TaskPriority
    status: TaskStatus
    created_at: datetime
    submissions: List[TaskSubmissionOut] = []
    subtasks: List["TaskOut"] = []

    class Config:
        from_attributes = True

class TaskSubmissionCreate(BaseModel):
    description: Optional[str] = None
    file_url: Optional[str] = None
    file_type: Optional[str] = None
    file_name: Optional[str] = None
    file_size: Optional[int] = None

class TaskReviewPayload(BaseModel):
    review_remarks: Optional[str] = None


# --- EVENT SCHEMAS ---
class EventCreate(BaseModel):
    title: str
    description: Optional[str] = None
    event_type: Optional[str] = "Seminar"
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    venue: Optional[str] = None
    coordinator_id: Optional[int] = None
    status: EventStatus = EventStatus.planned

class EventUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    event_type: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    venue: Optional[str] = None
    coordinator_id: Optional[int] = None
    status: Optional[EventStatus] = None

class EventOut(BaseModel):
    id: int
    title: str
    description: Optional[str] = None
    event_type: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    venue: Optional[str] = None
    coordinator_id: Optional[int] = None
    coordinator: Optional[UserOut] = None
    status: EventStatus
    created_by: int
    created_at: datetime
    tasks_count: int = 0
    completed_tasks_count: int = 0
    completion_percentage: float = 0.0

    class Config:
        from_attributes = True


# --- ANNOUNCEMENT SCHEMAS ---
class AnnouncementCreate(BaseModel):
    title: str
    body: str
    audience: AnnouncementAudience = AnnouncementAudience.both
    pinned: bool = False
    attachment_url: Optional[str] = None
    expiry_date: Optional[datetime] = None

class AnnouncementReactionOut(BaseModel):
    id: int
    announcement_id: int
    user_id: int
    user_name: Optional[str] = None
    reaction_type: str
    created_at: datetime

    class Config:
        from_attributes = True

class AnnouncementOut(BaseModel):
    id: int
    title: str
    body: str
    audience: AnnouncementAudience
    created_by: int
    author: Optional[UserOut] = None
    pinned: bool
    attachment_url: Optional[str] = None
    expiry_date: Optional[datetime] = None
    created_at: datetime
    reaction_counts: Dict[str, int] = {}
    user_reaction: Optional[str] = None

    class Config:
        from_attributes = True

class ReactionPayload(BaseModel):
    reaction_type: str = "like"


# --- QUERY SCHEMAS ---
class QueryCreate(BaseModel):
    subject: str
    category: str = "General"
    description: str

class QueryClosePayload(BaseModel):
    admin_remarks: str

class QueryOut(BaseModel):
    id: int
    raised_by: int
    raiser: Optional[UserOut] = None
    raiser_role: str
    subject: str
    category: str
    description: str
    status: QueryStatus
    admin_remarks: Optional[str] = None
    closed_by: Optional[int] = None
    closer: Optional[UserOut] = None
    closed_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


# --- DYNAMIC FORM SCHEMAS ---
class FormFieldSchema(BaseModel):
    field_id: str
    label: str
    type: str # text, email, phone, number, date, dropdown, radio, checkbox, file
    required: bool = False
    options: List[str] = []

class DynamicFormCreate(BaseModel):
    title: str
    purpose_label: str = "Custom Form"
    description: Optional[str] = None
    fields: List[FormFieldSchema]
    google_sheet_id: Optional[str] = None
    google_sheet_tab_name: Optional[str] = None

class DynamicFormOut(BaseModel):
    id: int
    title: str
    purpose_label: str
    description: Optional[str] = None
    form_schema: List[FormFieldSchema]
    google_sheet_id: Optional[str] = None
    google_sheet_tab_name: Optional[str] = None
    is_active: bool
    public_slug: str
    created_by: int
    created_at: datetime
    response_count: int = 0

    class Config:
        from_attributes = True

class DynamicFormResponseOut(BaseModel):
    id: int
    form_id: int
    response_data: Dict[str, Any]
    sync_status: str
    submitted_at: datetime
    ip_address: Optional[str] = None

    class Config:
        from_attributes = True


# --- FEEDBACK SCHEMAS ---
class FeedbackQuestionCreate(BaseModel):
    question_text: str
    question_type: str = "single_choice" # single_choice, multi_choice
    options: List[str]
    required: bool = True

class FeedbackFormCreate(BaseModel):
    title: str
    description: Optional[str] = None
    require_identification: bool = False
    questions: List[FeedbackQuestionCreate]

class FeedbackQuestionOut(BaseModel):
    id: int
    question_text: str
    question_type: str
    options: List[str]
    order_index: int
    required: bool

    class Config:
        from_attributes = True

class FeedbackFormOut(BaseModel):
    id: int
    title: str
    description: Optional[str] = None
    require_identification: bool
    is_active: bool
    created_by: int
    created_at: datetime
    questions: List[FeedbackQuestionOut] = []
    response_count: int = 0

    class Config:
        from_attributes = True

class FeedbackSubmissionPayload(BaseModel):
    respondent_type: str = "anonymous"
    respondent_identifier: Optional[str] = None
    answers: Dict[int, List[str]] # question_id -> list of selected option strings


# --- LEADERBOARD SCHEMAS ---
class LeaderboardTaskCreate(BaseModel):
    title: str
    description: Optional[str] = None
    points_value: int = 10
    submission_mode: SubmissionMode = SubmissionMode.single
    due_date: Optional[datetime] = None

class LeaderboardTaskOut(BaseModel):
    id: int
    title: str
    description: Optional[str] = None
    points_value: int
    submission_mode: SubmissionMode
    due_date: Optional[datetime] = None
    is_active: bool
    created_by: int
    created_at: datetime
    my_submission_count: int = 0
    my_has_submitted: bool = False

    class Config:
        from_attributes = True

class LeaderboardSubmissionCreate(BaseModel):
    submission_text: Optional[str] = None
    file_url: Optional[str] = None

class LeaderboardSubmissionOut(BaseModel):
    id: int
    leaderboard_task_id: int
    task_title: Optional[str] = None
    student_id: int
    student: Optional[UserOut] = None
    submission_text: Optional[str] = None
    file_url: Optional[str] = None
    submitted_at: datetime
    status: str
    points_awarded: Optional[int] = None
    reviewed_by: Optional[int] = None
    reviewed_at: Optional[datetime] = None
    rejection_reason: Optional[str] = None

    class Config:
        from_attributes = True

class ManualPointAwardPayload(BaseModel):
    student_id: int
    points: int
    reason_note: str

class StudentRankingOut(BaseModel):
    rank: int
    student_id: int
    name: str
    roll_number: Optional[str] = None
    course_branch: Optional[str] = None
    year: Optional[str] = None
    total_points: int
    task_points: int
    manual_points: int

class StaffRankingOut(BaseModel):
    rank: int
    faculty_id: int
    name: str
    department: str
    designation: Optional[str] = None
    total_score: int
    tasks_approved: int
    tasks_pending: int
    tasks_declined: int


# --- DASHBOARD & UTILITY SCHEMAS ---
class DashboardSummaryOut(BaseModel):
    total_faculty: int
    total_students: int
    total_events: int
    events_breakdown: Dict[str, int]
    total_tasks: int
    tasks_breakdown: Dict[str, int]
    total_queries: int
    queries_breakdown: Dict[str, int]
    total_announcements: int
    total_dynamic_forms: int
    total_form_responses: int
    total_feedback_forms: int
    total_feedback_responses: int
    total_student_points_awarded: int

class NotificationOut(BaseModel):
    id: int
    user_id: Optional[int] = None
    title: str
    body: str
    type: str
    is_read: bool
    link: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True

class AuditLogOut(BaseModel):
    id: int
    actor_id: Optional[int] = None
    actor_name: Optional[str] = None
    action: str
    entity_type: str
    entity_id: Optional[int] = None
    meta: Optional[Dict[str, Any]] = None
    created_at: datetime

    class Config:
        from_attributes = True

# --- DUTY CHART SCHEMAS ---
class DutyItemSchema(BaseModel):
    duty_name: str
    assigned_to_id: int
    assigned_to_name: Optional[str] = None
    role_description: Optional[str] = None
    venue: Optional[str] = None
    time_slot: Optional[str] = None

class DutyChartCreate(BaseModel):
    title: str
    event_id: int
    notes: Optional[str] = None
    duty_items: List[DutyItemSchema]

class DutyChartOut(BaseModel):
    id: int
    title: str
    event_id: int
    event_title: Optional[str] = None
    notes: Optional[str] = None
    duty_items: List[Dict[str, Any]]
    created_by: int
    creator_name: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True

# --- CORE COMMITTEE SCHEMAS ---
class CommitteeRoleSchema(BaseModel):
    role_name: str
    student_id: int
    responsibilities: Optional[str] = None

class CoreCommitteeCreate(BaseModel):
    title: str
    event_id: int
    event_date: Optional[str] = None
    faculty_id: int
    description: Optional[str] = None
    student_roles: List[CommitteeRoleSchema]

class CoreCommitteeOut(BaseModel):
    id: int
    title: str
    event_id: int
    event_title: Optional[str] = None
    event_date: Optional[str] = None
    faculty_id: int
    faculty_name: Optional[str] = None
    description: Optional[str] = None
    student_roles: List[Dict[str, Any]]
    created_by: int
    creator_name: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True
