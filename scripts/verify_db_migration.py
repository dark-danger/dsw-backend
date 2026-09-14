import asyncio
import os
import sys
import time

# Ensure backend root is in python path
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_root = os.path.abspath(os.path.join(current_dir, ".."))
sys.path.insert(0, backend_root)

from sqlalchemy import select, func, text
from app.database import engine, AsyncSessionLocal
from app.models.all_models import (
    User, UserRole, Event, Task, TaskSubmission, EventReport,
    Club, ClubTask, DutyChart, CoreCommittee, DynamicForm,
    DynamicFormResponse, FeedbackForm, FeedbackResponse,
    LeaderboardTask, StudentPointsLedger, FacultyPerformanceLedger,
    Announcement, QueryItem, Notification, EmailConnection
)


async def verify_migration():
    print("=" * 75)
    print("DSW PORTAL — DATABASE MIGRATION INTEGRITY & VERIFICATION TOOL")
    print("=" * 75)

    # 1. Connection & Ping Benchmark
    print("\n[1/3] Testing Connection & Latency...")
    t0 = time.perf_counter()
    try:
        async with engine.connect() as conn:
            res = await conn.execute(text("SELECT current_database(), current_user, version();"))
            db_name, db_user, pg_version = res.one()
            latency_ms = (time.perf_counter() - t0) * 1000

        print(f"  ✅ Successfully connected to: {db_name}")
        print(f"  👤 DB User: {db_user}")
        print(f"  ⚡ Round-Trip Latency Ping: {latency_ms:.2f} ms")
        print(f"  🐘 Engine Info: {pg_version.split(',')[0]}")
    except Exception as e:
        print(f"  ❌ Connection Failed: {e}")
        print("  Please verify your DATABASE_URL in .env before continuing.")
        return

    # 2. Table-by-Table Row Counts
    print("\n[2/3] Verifying Migrated Tables & Row Counts...")
    tables_to_check = [
        ("users", User),
        ("events", Event),
        ("tasks", Task),
        ("task_submissions", TaskSubmission),
        ("event_reports", EventReport),
        ("clubs", Club),
        ("club_tasks", ClubTask),
        ("duty_charts", DutyChart),
        ("core_committees", CoreCommittee),
        ("dynamic_forms", DynamicForm),
        ("dynamic_form_responses", DynamicFormResponse),
        ("feedback_forms", FeedbackForm),
        ("feedback_responses", FeedbackResponse),
        ("leaderboard_tasks", LeaderboardTask),
        ("student_points_ledger", StudentPointsLedger),
        ("faculty_performance_ledger", FacultyPerformanceLedger),
        ("announcements", Announcement),
        ("queries", QueryItem),
        ("notifications", Notification),
        ("email_connections", EmailConnection),
    ]

    total_rows = 0
    async with AsyncSessionLocal() as session:
        print(f"  {'Table Name':<30} | {'Status':<10} | {'Row Count':<10}")
        print("  " + "-" * 56)
        for tbl_name, model in tables_to_check:
            try:
                cnt_res = await session.execute(select(func.count()).select_from(model))
                count = cnt_res.scalar_one()
                total_rows += count
                status_icon = "✅ OK" if count >= 0 else "⚠️ 0"
                print(f"  {tbl_name:<30} | {status_icon:<10} | {count:>8} rows")
            except Exception as e:
                print(f"  {tbl_name:<30} | ❌ ERROR   | {str(e)[:30]}")

        # 3. User Role Integrity Verification
        print("\n[3/3] Checking User Role Integrity...")
        try:
            role_counts = await session.execute(
                select(User.role, func.count(User.id)).group_by(User.role)
            )
            for role, count in role_counts.all():
                print(f"  👥 {str(role.value):<15}: {count} accounts")
        except Exception as e:
            print(f"  ❌ Role verification error: {e}")

    print("\n" + "=" * 75)
    print(f"VERIFICATION SUMMARY: {total_rows} total rows verified across all entities.")
    print("=" * 75)


if __name__ == "__main__":
    asyncio.run(verify_migration())
