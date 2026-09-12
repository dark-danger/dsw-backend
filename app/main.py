import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from sqlalchemy import select, func

from app.config import settings
from app.core.security import get_password_hash
from app.database import AsyncSessionLocal, Base, engine
from app.models.all_models import User, UserRole
from app.routers import (
    announcements, auth, clubs, committees, dashboard, duty_charts,
    events, feedback, forms, leaderboard_staff, leaderboard_student,
    notifications, queries, tasks, uploads, users,
)



async def auto_seed_if_empty():
    try:
        async with AsyncSessionLocal() as session:
            # Fast single count check — if users exist, exit immediately with 0 bcrypt overhead
            cnt_res = await session.execute(select(func.count(User.id)))
            user_count = cnt_res.scalar_one()
            if user_count > 0:
                return

            admin = User(
                name="Admin Yash", email="admin@geeta.edu.in",
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
            await auto_seed_if_empty()
            _db_initialized = True
            print("DB and Seed initialized successfully.")
        except Exception as e:
            print(f"Error initializing DB: {e}")
            raise e

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Full-stack portal for Dean of Student Welfare (DSW) Geeta University",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def db_init_middleware(request: Request, call_next):
    # Preflight requests immediately return 200 OK with full CORS headers
    if request.method == "OPTIONS":
        return Response(
            status_code=200,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS, PATCH, HEAD",
                "Access-Control-Allow-Headers": "*",
                "Access-Control-Max-Age": "86400",
            }
        )
        
    if request.url.path in ["/", "/health", "/docs", "/openapi.json"]:
        response = await call_next(request)
        response.headers["Access-Control-Allow-Origin"] = "*"
        return response

    try:
        await ensure_db_initialized()
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"detail": str(e), "error_type": "DatabaseConfigurationError"},
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "*",
                "Access-Control-Allow-Headers": "*"
            }
        )
        
    response = await call_next(request)
    response.headers["Access-Control-Allow-Origin"] = "*"
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



@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "DSW API",
        "db_initialized": _db_initialized
    }

@app.get("/")
async def root():
    return {
        "status": "online",
        "service": "DSW Geeta University Portal API",
        "docs": "/docs"
    }

handler = app
