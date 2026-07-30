from datetime import datetime, timezone
from sqlalchemy import String, Integer, Boolean, Text, DateTime, ForeignKey, Enum, Float, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base
import enum

def utc_now():
    return datetime.now(timezone.utc)

class UserRole(str, enum.Enum):
    super_admin = "super_admin"
    faculty = "faculty"
    student = "student"

class EventStatus(str, enum.Enum):
    planned = "planned"
    ongoing = "ongoing"
    completed = "completed"
    cancelled = "cancelled"

class TaskPriority(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"

class TaskStatus(str, enum.Enum):
    pending = "pending"
    in_progress = "in_progress"
    submitted = "submitted"
    approved = "approved"
    declined = "declined"

class AnnouncementAudience(str, enum.Enum):
    faculty = "faculty"
    students = "students"
    both = "both"

class QueryStatus(str, enum.Enum):
    open = "open"
    closed = "closed"

class SubmissionMode(str, enum.Enum):
    single = "single"
    multiple = "multiple"

class DynamicFormPurpose(str, enum.Enum):
    registration = "Registration Form"
    detailed = "Detailed Form"
    interview = "Interview / Selection Form"
    committee = "Committee Sign-up Form"
    custom = "Custom Form"


# 1. USER MODEL
class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    phone: Mapped[str] = mapped_column(String(30), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.student, nullable=False)
    
    # Faculty specific fields
    department: Mapped[str] = mapped_column(String(100), nullable=True)
    designation: Mapped[str] = mapped_column(String(100), nullable=True)
    employee_id: Mapped[str] = mapped_column(String(50), nullable=True)
    
    # Student specific fields
    roll_number: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=True)
    course_branch: Mapped[str] = mapped_column(String(100), nullable=True)
    year: Mapped[str] = mapped_column(String(20), nullable=True)
    
    profile_photo_url: Mapped[str] = mapped_column(String(500), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


# 2. EVENT MODEL
class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    event_type: Mapped[str] = mapped_column(String(50), nullable=True) # Seminar, Competition, Workshop, etc.
    start_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    end_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    venue: Mapped[str] = mapped_column(String(200), nullable=True)
    coordinator_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=True)
    status: Mapped[EventStatus] = mapped_column(Enum(EventStatus), default=EventStatus.planned)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    coordinator = relationship("User", foreign_keys=[coordinator_id])
    tasks = relationship("Task", back_populates="event", cascade="all, delete-orphan")


# 3. TASK & SUBMISSION MODELS
class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    task_type: Mapped[str] = mapped_column(String(50), default="standalone") # standalone / event_linked
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id", ondelete="SET NULL"), nullable=True)
    parent_task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), nullable=True)
    assigned_to: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    assigned_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    due_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    priority: Mapped[TaskPriority] = mapped_column(Enum(TaskPriority), default=TaskPriority.medium)
    status: Mapped[TaskStatus] = mapped_column(Enum(TaskStatus), default=TaskStatus.pending)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    event = relationship("Event", back_populates="tasks")
    assignee = relationship("User", foreign_keys=[assigned_to])
    assigner = relationship("User", foreign_keys=[assigned_by])
    parent = relationship("Task", remote_side=[id], backref="subtasks")
    submissions = relationship("TaskSubmission", back_populates="task", cascade="all, delete-orphan")


class TaskSubmission(Base):
    __tablename__ = "task_submissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False)
    submitted_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    file_url: Mapped[str] = mapped_column(String(500), nullable=True)
    file_type: Mapped[str] = mapped_column(String(50), nullable=True) # pdf, doc, jpg, png
    file_name: Mapped[str] = mapped_column(String(255), nullable=True)
    file_size: Mapped[int] = mapped_column(Integer, nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    review_status: Mapped[str] = mapped_column(String(50), default="pending") # pending, approved, declined
    reviewed_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=True)
    review_remarks: Mapped[str] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)

    task = relationship("Task", back_populates="submissions")
    submitter = relationship("User", foreign_keys=[submitted_by])
    reviewer = relationship("User", foreign_keys=[reviewed_by])


# 4. ANNOUNCEMENT MODELS
class Announcement(Base):
    __tablename__ = "announcements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    audience: Mapped[AnnouncementAudience] = mapped_column(Enum(AnnouncementAudience), default=AnnouncementAudience.both)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    attachment_url: Mapped[str] = mapped_column(String(500), nullable=True)
    expiry_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    author = relationship("User", foreign_keys=[created_by])
    reactions = relationship("AnnouncementReaction", back_populates="announcement", cascade="all, delete-orphan")


class AnnouncementReaction(Base):
    __tablename__ = "announcement_reactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    announcement_id: Mapped[int] = mapped_column(ForeignKey("announcements.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    reaction_type: Mapped[str] = mapped_column(String(30), default="like") # like, heart, celebrate, clap
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    announcement = relationship("Announcement", back_populates="reactions")
    user = relationship("User", foreign_keys=[user_id])


# 5. QUERY / GRIEVANCE MODEL
class QueryItem(Base):
    __tablename__ = "queries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    raised_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    raiser_role: Mapped[str] = mapped_column(String(30), nullable=False) # faculty, student
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(50), default="General") # Academic, Administrative, Technical, Other
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[QueryStatus] = mapped_column(Enum(QueryStatus), default=QueryStatus.open)
    admin_remarks: Mapped[str] = mapped_column(Text, nullable=True)
    closed_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=True)
    closed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    raiser = relationship("User", foreign_keys=[raised_by])
    closer = relationship("User", foreign_keys=[closed_by])


# 5.5. DUTY CHART MODEL
class DutyChart(Base):
    __tablename__ = "duty_charts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), nullable=False)
    notes: Mapped[str] = mapped_column(Text, nullable=True)
    duty_items: Mapped[list] = mapped_column(JSON, nullable=False) # JSON array of {duty_name, assigned_to_id, assigned_to_name, role_description, venue, time_slot}
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    event = relationship("Event")
    creator = relationship("User", foreign_keys=[created_by])


# 5.6. CORE COMMITTEE MODEL
class CoreCommittee(Base):
    __tablename__ = "core_committees"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), nullable=False)
    event_date: Mapped[str] = mapped_column(String(50), nullable=True)
    faculty_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False) # Faculty Mentor/In-charge
    description: Mapped[str] = mapped_column(Text, nullable=True)
    student_roles: Mapped[list] = mapped_column(JSON, nullable=False) # Array of { role_name, student_id, student_name, student_roll_no, department, phone, responsibilities }
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    event = relationship("Event")
    faculty_mentor = relationship("User", foreign_keys=[faculty_id])
    creator = relationship("User", foreign_keys=[created_by])


# 6. DYNAMIC FORM MODELS (Google Sheets Sync)
class DynamicForm(Base):
    __tablename__ = "dynamic_forms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    purpose_label: Mapped[str] = mapped_column(String(100), default="Custom Form")
    description: Mapped[str] = mapped_column(Text, nullable=True)
    form_schema: Mapped[dict] = mapped_column(JSON, nullable=False) # JSON array of field definitions
    google_sheet_id: Mapped[str] = mapped_column(String(200), nullable=True)
    google_sheet_tab_name: Mapped[str] = mapped_column(String(100), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    public_slug: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    creator = relationship("User", foreign_keys=[created_by])
    responses = relationship("DynamicFormResponse", back_populates="form", cascade="all, delete-orphan")


class DynamicFormResponse(Base):
    __tablename__ = "dynamic_form_responses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    form_id: Mapped[int] = mapped_column(ForeignKey("dynamic_forms.id", ondelete="CASCADE"), nullable=False)
    response_data: Mapped[dict] = mapped_column(JSON, nullable=False)
    sync_status: Mapped[str] = mapped_column(String(30), default="synced") # synced, pending, failed
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    ip_address: Mapped[str] = mapped_column(String(50), nullable=True)

    form = relationship("DynamicForm", back_populates="responses")


# 7. FEEDBACK FORM MODELS
class FeedbackForm(Base):
    __tablename__ = "feedback_forms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    require_identification: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    questions = relationship("FeedbackQuestion", back_populates="form", cascade="all, delete-orphan")
    responses = relationship("FeedbackResponse", back_populates="form", cascade="all, delete-orphan")


class FeedbackQuestion(Base):
    __tablename__ = "feedback_questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    form_id: Mapped[int] = mapped_column(ForeignKey("feedback_forms.id", ondelete="CASCADE"), nullable=False)
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    question_type: Mapped[str] = mapped_column(String(30), default="single_choice") # single_choice, multi_choice
    options: Mapped[list] = mapped_column(JSON, nullable=False) # JSON array of option strings
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    required: Mapped[bool] = mapped_column(Boolean, default=True)

    form = relationship("FeedbackForm", back_populates="questions")


class FeedbackResponse(Base):
    __tablename__ = "feedback_responses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    form_id: Mapped[int] = mapped_column(ForeignKey("feedback_forms.id", ondelete="CASCADE"), nullable=False)
    respondent_type: Mapped[str] = mapped_column(String(30), default="anonymous")
    respondent_identifier: Mapped[str] = mapped_column(String(150), nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    form = relationship("FeedbackForm", back_populates="responses")
    answers = relationship("FeedbackAnswer", back_populates="response", cascade="all, delete-orphan")


class FeedbackAnswer(Base):
    __tablename__ = "feedback_answers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    response_id: Mapped[int] = mapped_column(ForeignKey("feedback_responses.id", ondelete="CASCADE"), nullable=False)
    question_id: Mapped[int] = mapped_column(ForeignKey("feedback_questions.id", ondelete="CASCADE"), nullable=False)
    selected_options: Mapped[list] = mapped_column(JSON, nullable=False)

    response = relationship("FeedbackResponse", back_populates="answers")
    question = relationship("FeedbackQuestion")


# 8. LEADERBOARD MODELS (STUDENT & STAFF)
class LeaderboardTask(Base):
    __tablename__ = "leaderboard_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    points_value: Mapped[int] = mapped_column(Integer, default=10)
    submission_mode: Mapped[SubmissionMode] = mapped_column(Enum(SubmissionMode), default=SubmissionMode.single)
    due_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    submissions = relationship("LeaderboardTaskSubmission", back_populates="task", cascade="all, delete-orphan")


class LeaderboardTaskSubmission(Base):
    __tablename__ = "leaderboard_task_submissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    leaderboard_task_id: Mapped[int] = mapped_column(ForeignKey("leaderboard_tasks.id", ondelete="CASCADE"), nullable=False)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    submission_text: Mapped[str] = mapped_column(Text, nullable=True)
    file_url: Mapped[str] = mapped_column(String(500), nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    status: Mapped[str] = mapped_column(String(30), default="pending") # pending, approved, rejected
    points_awarded: Mapped[int] = mapped_column(Integer, nullable=True)
    reviewed_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[str] = mapped_column(Text, nullable=True)

    task = relationship("LeaderboardTask", back_populates="submissions")
    student = relationship("User", foreign_keys=[student_id])
    reviewer = relationship("User", foreign_keys=[reviewed_by])


class StudentPointsLedger(Base):
    __tablename__ = "student_points_ledger"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    points: Mapped[int] = mapped_column(Integer, nullable=False)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False) # task_submission / manual_award
    source_id: Mapped[int] = mapped_column(ForeignKey("leaderboard_task_submissions.id", ondelete="SET NULL"), nullable=True)
    reason_note: Mapped[str] = mapped_column(Text, nullable=True)
    awarded_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    student = relationship("User", foreign_keys=[student_id])
    awarder = relationship("User", foreign_keys=[awarded_by])


class FacultyPerformanceLedger(Base):
    __tablename__ = "faculty_performance_ledger"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    faculty_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    score_delta: Mapped[int] = mapped_column(Integer, nullable=False) # +10, +5, -3
    source_type: Mapped[str] = mapped_column(String(50), nullable=False) # task_approved / task_declined / task_overdue
    source_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True)
    note: Mapped[str] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    faculty = relationship("User", foreign_keys=[faculty_id])


# 9. NOTIFICATIONS & AUDIT LOG
class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True) # None = global broadcast
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str] = mapped_column(String(50), nullable=False) # task_assigned, task_approved, task_declined, announcement, query_closed, points_awarded
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    link: Mapped[str] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    user = relationship("User", foreign_keys=[user_id])


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[int] = mapped_column(Integer, nullable=True)
    meta: Mapped[dict] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    actor = relationship("User", foreign_keys=[actor_id])
