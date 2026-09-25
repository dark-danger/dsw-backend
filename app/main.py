import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select, func, text

from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.core.security import get_password_hash
from app.database import AsyncSessionLocal, Base, engine
from app.models.all_models import User, UserRole
from app.routers import (
    ai, announcements, auth, clubs, committees, dashboard, dpr, duty_charts,
    email, event_reports, events, feedback, forms, leaderboard_staff, leaderboard_student,
    notifications, queries, tasks, uploads, users,
)


async def apply_safe_migrations(conn):
    """
    Applies idempotent column additions and performance indexes to existing tables.
    Ensures that existing databases seamlessly acquire new feature columns and indexes.
    """
    migration_statements = [
        # dynamic_forms table columns
        "ALTER TABLE dynamic_forms ADD COLUMN IF NOT EXISTS google_sheet_url VARCHAR(500);",
        "ALTER TABLE dynamic_forms ADD COLUMN IF NOT EXISTS google_webhook_url VARCHAR(500);",
        "ALTER TABLE dynamic_forms ADD COLUMN IF NOT EXISTS enable_image_upload BOOLEAN DEFAULT FALSE;",
        "ALTER TABLE dynamic_forms ADD COLUMN IF NOT EXISTS image_upload_label VARCHAR(200) DEFAULT 'Upload Document / Photo';",
        "ALTER TABLE dynamic_forms ADD COLUMN IF NOT EXISTS image_upload_required BOOLEAN DEFAULT FALSE;",
        "ALTER TABLE dynamic_forms ADD COLUMN IF NOT EXISTS enable_payment BOOLEAN DEFAULT FALSE;",
        "ALTER TABLE dynamic_forms ADD COLUMN IF NOT EXISTS payment_amount DOUBLE PRECISION DEFAULT 0.0;",
        "ALTER TABLE dynamic_forms ADD COLUMN IF NOT EXISTS upi_id VARCHAR(100);",
        "ALTER TABLE dynamic_forms ADD COLUMN IF NOT EXISTS upi_payee_name VARCHAR(200);",
        # other table column verifications
        "ALTER TABLE events ADD COLUMN IF NOT EXISTS event_type VARCHAR(50) DEFAULT 'Seminar';",
        "ALTER TABLE events ADD COLUMN IF NOT EXISTS venue VARCHAR(200);",
        # Multi-file attachment and arbitrary length column alterations
        "ALTER TABLE task_submissions ALTER COLUMN file_url TYPE TEXT;",
        "ALTER TABLE task_submissions ALTER COLUMN file_name TYPE TEXT;",
        "ALTER TABLE task_submissions ALTER COLUMN file_type TYPE VARCHAR(100);",
        "ALTER TABLE tasks ALTER COLUMN description TYPE TEXT;",
        "ALTER TABLE tasks ALTER COLUMN title TYPE VARCHAR(500);",
        "ALTER TABLE leaderboard_task_submissions ALTER COLUMN file_url TYPE TEXT;",
        "ALTER TABLE club_tasks ALTER COLUMN file_url TYPE TEXT;",
        # Task start_date time limit columns
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS start_date TIMESTAMPTZ;",
        "ALTER TABLE leaderboard_tasks ADD COLUMN IF NOT EXISTS start_date TIMESTAMPTZ;",
        "ALTER TABLE club_tasks ADD COLUMN IF NOT EXISTS start_date TIMESTAMPTZ;",
        # Query target columns & indexes
        "ALTER TABLE queries ADD COLUMN IF NOT EXISTS target_type VARCHAR(50) DEFAULT 'admin';",
        "ALTER TABLE queries ADD COLUMN IF NOT EXISTS target_faculty_id INTEGER;",
        "ALTER TABLE queries ADD COLUMN IF NOT EXISTS target_faculty_name VARCHAR(150);",
        "CREATE INDEX IF NOT EXISTS idx_queries_target_faculty_id ON queries (target_faculty_id);",
        "CREATE INDEX IF NOT EXISTS idx_queries_target_type ON queries (target_type);",
        # High-Performance Indexes for frequently queried filters and foreign keys
        "CREATE INDEX IF NOT EXISTS idx_tasks_assigned_to ON tasks (assigned_to);",
        "CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks (status);",
        "CREATE INDEX IF NOT EXISTS idx_tasks_event_id ON tasks (event_id);",
        "CREATE INDEX IF NOT EXISTS idx_tasks_parent_task_id ON tasks (parent_task_id);",
        "CREATE INDEX IF NOT EXISTS idx_tasks_created_at ON tasks (created_at DESC);",
        "CREATE INDEX IF NOT EXISTS idx_task_sub_task_id ON task_submissions (task_id);",
        "CREATE INDEX IF NOT EXISTS idx_task_sub_submitted_by ON task_submissions (submitted_by);",
        "CREATE INDEX IF NOT EXISTS idx_task_sub_submitted_at ON task_submissions (submitted_at DESC);",
        "CREATE INDEX IF NOT EXISTS idx_events_status ON events (status);",
        "CREATE INDEX IF NOT EXISTS idx_events_coordinator_id ON events (coordinator_id);",
        "CREATE INDEX IF NOT EXISTS idx_events_created_at ON events (created_at DESC);",
        "CREATE INDEX IF NOT EXISTS idx_users_role ON users (role);",
        "CREATE INDEX IF NOT EXISTS idx_users_is_active ON users (is_active);",
        "CREATE INDEX IF NOT EXISTS idx_users_department ON users (department);",
        "CREATE INDEX IF NOT EXISTS idx_faculty_perf_faculty_id ON faculty_performance_ledger (faculty_id);",
        "CREATE INDEX IF NOT EXISTS idx_faculty_perf_created_at ON faculty_performance_ledger (created_at);",
        "CREATE INDEX IF NOT EXISTS idx_student_points_student_id ON student_points_ledger (student_id);",
        "CREATE INDEX IF NOT EXISTS idx_student_points_created_at ON student_points_ledger (created_at);",
        "CREATE INDEX IF NOT EXISTS idx_lb_sub_task_id ON leaderboard_task_submissions (leaderboard_task_id);",
        "CREATE INDEX IF NOT EXISTS idx_lb_sub_student_id ON leaderboard_task_submissions (student_id);",
        "CREATE INDEX IF NOT EXISTS idx_lb_sub_status ON leaderboard_task_submissions (status);",
        "CREATE INDEX IF NOT EXISTS idx_queries_raised_by ON queries (raised_by);",
        "CREATE INDEX IF NOT EXISTS idx_queries_status ON queries (status);",
        "CREATE INDEX IF NOT EXISTS idx_audit_logs_actor_id ON audit_logs (actor_id);",
        # Email Connections table for Google OAuth 2.0 per-user Gmail integration
        """
        CREATE TABLE IF NOT EXISTS email_connections (
            id SERIAL PRIMARY KEY,
            user_id INTEGER UNIQUE NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            provider VARCHAR(50) NOT NULL DEFAULT 'google',
            email VARCHAR(255) NOT NULL,
            encrypted_refresh_token TEXT NOT NULL,
            status VARCHAR(50) NOT NULL DEFAULT 'connected',
            scopes TEXT,
            connected_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        );
        """,
        "CREATE INDEX IF NOT EXISTS idx_email_conn_user_id ON email_connections (user_id);",
        "CREATE INDEX IF NOT EXISTS idx_email_conn_email ON email_connections (email);",
        "CREATE INDEX IF NOT EXISTS idx_audit_logs_created_at ON audit_logs (created_at DESC);",
        "CREATE INDEX IF NOT EXISTS idx_clubs_faculty_id ON clubs (faculty_id);",
        "CREATE INDEX IF NOT EXISTS idx_club_tasks_club_id ON club_tasks (club_id);",
        "CREATE INDEX IF NOT EXISTS idx_club_tasks_status ON club_tasks (status);",
        # Daily Progress Reports table
        """
        CREATE TABLE IF NOT EXISTS daily_progress_reports (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            report_date VARCHAR(20) NOT NULL,
            total_hours DOUBLE PRECISION DEFAULT 0.0,
            summary TEXT,
            challenges TEXT,
            plan_for_tomorrow TEXT,
            other_tasks JSONB DEFAULT '[]'::jsonb,
            status VARCHAR(30) DEFAULT 'submitted',
            admin_remarks TEXT,
            acknowledged_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
            acknowledged_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        );
        """,
        "CREATE INDEX IF NOT EXISTS idx_dpr_user_id ON daily_progress_reports (user_id);",
        "CREATE INDEX IF NOT EXISTS idx_dpr_report_date ON daily_progress_reports (report_date);",
        "CREATE INDEX IF NOT EXISTS idx_dpr_status ON daily_progress_reports (status);",
        "CREATE INDEX IF NOT EXISTS idx_dpr_created_at ON daily_progress_reports (created_at DESC);",
        # DPR Task Updates table
        """
        CREATE TABLE IF NOT EXISTS dpr_task_updates (
            id SERIAL PRIMARY KEY,
            dpr_id INTEGER NOT NULL REFERENCES daily_progress_reports(id) ON DELETE CASCADE,
            task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
            task_title VARCHAR(255) NOT NULL,
            today_work_summary TEXT NOT NULL,
            status_update VARCHAR(50) DEFAULT 'in_progress',
            progress_percentage INTEGER DEFAULT 0,
            hours_spent DOUBLE PRECISION DEFAULT 0.0,
            remarks TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
        """,
        "CREATE INDEX IF NOT EXISTS idx_dpr_tu_dpr_id ON dpr_task_updates (dpr_id);",
        "ALTER TABLE daily_progress_reports ADD COLUMN IF NOT EXISTS document_url VARCHAR(500);",
        "ALTER TABLE daily_progress_reports ADD COLUMN IF NOT EXISTS drive_file_id VARCHAR(200);",
        "ALTER TABLE daily_progress_reports ADD COLUMN IF NOT EXISTS drive_file_url VARCHAR(500);",
        "ALTER TABLE daily_progress_reports ADD COLUMN IF NOT EXISTS drive_folder_url VARCHAR(500);",
        # Update super admin name to Dr. Rekha Narang
        "UPDATE users SET name = 'Dr. Rekha Narang' WHERE email = 'admin@geeta.edu.in' OR (role = 'super_admin' AND name IN ('Admin Yash', 'Dr. Rajesh Sharma (Dean)', 'Admin User'));",

    ]
    for stmt in migration_statements:
        try:
            await conn.execute(text(stmt))
        except Exception as e:
            pass


async def auto_seed_if_empty():
    try:
        async with AsyncSessionLocal() as session:
            # Fast single count check — if users exist, exit immediately with 0 bcrypt overhead
            cnt_res = await session.execute(select(func.count(User.id)))
            user_count = cnt_res.scalar_one()
            if user_count > 0:
                # Also ensure super admin name is updated if already created
                await session.execute(
                    text("UPDATE users SET name = 'Dr. Rekha Narang' WHERE email = 'admin@geeta.edu.in' OR (role = 'super_admin' AND name IN ('Admin Yash', 'Dr. Rajesh Sharma (Dean)', 'Admin User'))")
                )
                await session.commit()
                return

            admin = User(
                name="Dr. Rekha Narang", email="admin@geeta.edu.in",
                phone="+91 98765 43210", role=UserRole.super_admin,
                password_hash=get_password_hash("admin123"), must_change_password=False
            )
            session.add(admin)

            fac = User(
                name="Faculty Yash", email="faculty@geeta.edu.in",
                phone="+91 98123 45678", department="Computer Science & Engineering",
                designation="Associate Professor", employee_id="GU-CSE-042",
                role=UserRole.faculty, password_hash=get_password_hash("faculty123"),
                must_change_password=False
            )
            session.add(fac)

            stu = User(
                name="Student Yash", email="student@geeta.edu.in",
                phone="+91 99887 76655", roll_number="GU2026001",
                course_branch="B.Tech CSE", year="3rd Year",
                role=UserRole.student, password_hash=get_password_hash("student123"),
                must_change_password=False
            )
            session.add(stu)

            await session.commit()
            print("Auto-seeded demo accounts successfully!")
    except Exception as e:
        print(f"Auto-seed warning: {e}")


_db_initialized = False

async def ensure_db_initialized():
    if not settings.DATABASE_URL:
        raise RuntimeError("CRITICAL ERROR: Supabase DATABASE_URL is missing in Vercel environment variables. You must set it to prevent data loss.")
    global _db_initialized
    if not _db_initialized:
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
                await apply_safe_migrations(conn)
            await auto_seed_if_empty()
            _db_initialized = True
            print("DB, Indexes and Seed initialized successfully.")
        except Exception as e:
            print(f"Error initializing DB: {e}")
            raise e

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Perform one-time async database and index initialization on server startup
    try:
        await ensure_db_initialized()
    except Exception as e:
        print(f"[Startup] DB init note: {e}")
    yield
    # Graceful shutdown
    try:
        await engine.dispose()
    except Exception:
        pass

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Full-stack portal for Dean of Student Welfare (DSW) Geeta University",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


import time
import contextvars
from sqlalchemy import event

# Per-request context variables for DB query tracking
_query_count_ctx = contextvars.ContextVar("query_count", default=0)
_query_time_ctx = contextvars.ContextVar("query_time", default=0.0)

# Attach query listeners on the sync_engine
@event.listens_for(engine.sync_engine, "before_cursor_execute")
def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    context._query_start_time = time.perf_counter()

@event.listens_for(engine.sync_engine, "after_cursor_execute")
def after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    duration = time.perf_counter() - getattr(context, "_query_start_time", time.perf_counter())
    count = _query_count_ctx.get() + 1
    _query_count_ctx.set(count)
    _query_time_ctx.set(_query_time_ctx.get() + duration)


@app.middleware("http")
async def profiling_and_timing_middleware(request: Request, call_next):
    # Reset per-request DB query metrics
    _query_count_ctx.set(0)
    _query_time_ctx.set(0.0)
    start_time = time.perf_counter()

    # Preflight OPTIONS requests return immediately with wide-open CORS headers
    if request.method == "OPTIONS":
        return JSONResponse(
            status_code=200,
            content={"status": "ok"},
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, PATCH, OPTIONS",
                "Access-Control-Allow-Headers": "*",
                "Access-Control-Max-Age": "86400",
            }
        )

    # Lightweight health/docs routes bypass DB initialization for maximum speed
    if request.url.path in ["/", "/health", "/api/keep-warm", "/docs", "/openapi.json"]:
        try:
            response = await call_next(request)
        except Exception as e:
            return JSONResponse(
                status_code=500,
                content={"detail": str(e), "error_type": type(e).__name__},
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "*",
                    "Access-Control-Allow-Headers": "*"
                }
            )
        process_time = (time.perf_counter() - start_time) * 1000
        response.headers["X-Process-Time"] = f"{process_time:.2f}ms"
        response.headers["Access-Control-Allow-Origin"] = "*"
        return response
        
    global _db_initialized
    if not _db_initialized:
        try:
            await ensure_db_initialized()
        except Exception as e:
            print(f"[DB Init Error] {e}")
            return JSONResponse(
                status_code=500,
                content={"detail": f"Database initialization failed: {str(e)}", "error_type": "DatabaseConfigurationError"},
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "*",
                    "Access-Control-Allow-Headers": "*"
                }
            )

    try:
        response = await call_next(request)
    except Exception as exc:
        print(f"[Unhandled Exception] {request.method} {request.url.path} -> {exc}")
        return JSONResponse(
            status_code=500,
            content={"detail": str(exc), "error_type": type(exc).__name__},
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "*",
                "Access-Control-Allow-Headers": "*"
            }
        )

    total_time_ms = (time.perf_counter() - start_time) * 1000
    db_count = _query_count_ctx.get()
    db_time_ms = _query_time_ctx.get() * 1000

    response.headers["X-Process-Time"] = f"{total_time_ms:.2f}ms"
    response.headers["X-DB-Queries"] = str(db_count)
    response.headers["X-DB-Time"] = f"{db_time_ms:.2f}ms"
    response.headers["Access-Control-Allow-Origin"] = "*"

    # Log query execution time & counts for instant N+1 / slow route visibility
    print(f"[API Profiler] {request.method} {request.url.path} -> {response.status_code} ({total_time_ms:.1f}ms total | {db_count} DB queries in {db_time_ms:.1f}ms)")
    return response

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    print(f"Global Exception: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc), "error_type": type(exc).__name__},
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "*",
            "Access-Control-Allow-Headers": "*"
        }
    )


# Mount all domain routers
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(tasks.router)
app.include_router(events.router)
app.include_router(event_reports.router)
app.include_router(announcements.router)
app.include_router(queries.router)
app.include_router(forms.router)
app.include_router(feedback.router)
app.include_router(leaderboard_student.router)
app.include_router(leaderboard_staff.router)
app.include_router(dashboard.router)
app.include_router(notifications.router)
app.include_router(uploads.router)
app.include_router(duty_charts.router)
app.include_router(committees.router)
app.include_router(clubs.router)
app.include_router(ai.router)
app.include_router(email.router)
app.include_router(dpr.router)

# Mount static uploads directory for direct access to uploaded images/proofs
if os.path.exists(settings.UPLOAD_DIR):
    app.mount("/uploads", StaticFiles(directory=settings.UPLOAD_DIR), name="uploads")


@app.get("/health")
@app.get("/api/keep-warm")
async def health_check():
    return {
        "status": "healthy",
        "service": "DSW API",
        "db_initialized": _db_initialized,
        "timestamp": time.time()
    }

@app.get("/")
async def root():
    return {
        "status": "online",
        "service": "DSW Geeta University Portal API",
        "docs": "/docs"
    }

handler = app
