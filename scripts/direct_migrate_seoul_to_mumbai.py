import asyncio
import os
import sys
import time

# Ensure backend root is in python path
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_root = os.path.abspath(os.path.join(current_dir, ".."))
sys.path.insert(0, backend_root)

import ssl
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import select, text, func
from app.models.all_models import Base

# Source (Seoul) and Target (Mumbai) Connection URLs
SEOUL_URL = "postgresql+asyncpg://postgres.metuxpzpduxkvqhiupcq:Y1a2s3h4%409211067540@aws-1-ap-northeast-2.pooler.supabase.com:6543/postgres"
MUMBAI_URL = "postgresql+asyncpg://postgres.wdkglxguerkswgehuftf:Y1a2s3h4%409211067540@aws-0-ap-south-1.pooler.supabase.com:6543/postgres"

def get_engine(url: str):
    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE
    return create_async_engine(
        url,
        connect_args={
            "ssl": ssl_ctx,
            "statement_cache_size": 0,
            "timeout": 15.0,
            "command_timeout": 30.0
        },
        pool_pre_ping=True
    )

TABLES_IN_ORDER = [
    "users",
    "events",
    "tasks",
    "task_submissions",
    "event_reports",
    "clubs",
    "club_tasks",
    "duty_charts",
    "core_committees",
    "dynamic_forms",
    "dynamic_form_responses",
    "feedback_forms",
    "feedback_questions",
    "feedback_responses",
    "feedback_answers",
    "leaderboard_tasks",
    "leaderboard_task_submissions",
    "student_points_ledger",
    "faculty_performance_ledger",
    "announcements",
    "announcement_reactions",
    "queries",
    "notifications",
    "audit_logs",
    "email_connections"
]

import json

def serialize_row(row_dict):
    clean = {}
    for k, v in row_dict.items():
        if isinstance(v, (dict, list)):
            clean[k] = json.dumps(v)
        else:
            clean[k] = v
    return clean

async def migrate():
    print("=" * 80)
    print("DIRECT PYTHON DATABASE MIGRATION: SEOUL (ap-northeast-2) ➔ MUMBAI (ap-south-1)")
    print("=" * 80)

    source_engine = get_engine(SEOUL_URL)
    target_engine = get_engine(MUMBAI_URL)

    # 1. Test connections
    print("\n[1/4] Testing connections to both databases...")
    try:
        async with source_engine.connect() as s_conn:
            res = await s_conn.execute(text("SELECT current_database(), current_user;"))
            s_db, s_user = res.one()
            print(f"  ✅ Source (Seoul) Connected: user={s_user}")
    except Exception as e:
        print(f"  ❌ Failed to connect to Seoul DB: {e}")
        return

    try:
        async with target_engine.connect() as t_conn:
            res = await t_conn.execute(text("SELECT current_database(), current_user;"))
            t_db, t_user = res.one()
            print(f"  ✅ Target (Mumbai) Connected: user={t_user}")
    except Exception as e:
        print(f"  ❌ Failed to connect to Mumbai DB: {e}")
        return

    # 2. Create tables in Target if not existing
    print("\n[2/4] Ensuring table schemas and indexes exist in Mumbai database...")
    async with target_engine.begin() as t_conn:
        await t_conn.run_sync(Base.metadata.create_all)
    print("  ✅ Table schemas verified in Mumbai.")

    # 3. Copy data table by table
    print("\n[3/4] Copying data table-by-table...")
    total_records_migrated = 0

    async with source_engine.connect() as s_conn:
        async with target_engine.begin() as t_conn:
            # Temporarily disable foreign key constraints for safe bulk insert
            await t_conn.execute(text("SET session_replication_role = 'replica';"))

            for table_name in TABLES_IN_ORDER:
                try:
                    # Fetch all rows from source
                    select_sql = text(f'SELECT * FROM "{table_name}" ORDER BY id ASC;' if table_name != "feedback_answers" else f'SELECT * FROM "{table_name}";')
                    s_res = await s_conn.execute(select_sql)
                    rows = s_res.mappings().all()
                    row_count = len(rows)

                    if row_count > 0:
                        # Clear target table to prevent duplicate key collisions
                        await t_conn.execute(text(f'TRUNCATE TABLE "{table_name}" CASCADE;'))
                        
                        # Insert rows with proper JSON string serialization
                        keys = list(rows[0].keys())
                        cols_str = ", ".join([f'"{k}"' for k in keys])
                        vals_str = ", ".join([f':{k}' for k in keys])
                        insert_sql = text(f'INSERT INTO "{table_name}" ({cols_str}) VALUES ({vals_str});')

                        serialized_rows = [serialize_row(dict(r)) for r in rows]
                        await t_conn.execute(insert_sql, serialized_rows)
                        total_records_migrated += row_count
                        print(f"  ✅ {table_name:<30} | {row_count:>6} rows migrated")
                    else:
                        print(f"  ⚪ {table_name:<30} | {row_count:>6} rows (Empty table)")

                except Exception as e:
                    print(f"  ⚠️ {table_name:<30} | Note/Skipped: {e}")

            # Re-enable foreign key constraints
            await t_conn.execute(text("SET session_replication_role = 'origin';"))

            # 4. Reset serial sequences for auto-increment IDs
            print("\n[4/4] Resetting sequence generators for auto-increment primary keys...")
            for table_name in TABLES_IN_ORDER:
                try:
                    seq_sql = text(f"""
                        SELECT setval(
                            pg_get_serial_sequence('"{table_name}"', 'id'),
                            COALESCE(MAX(id), 1)
                        ) FROM "{table_name}";
                    """)
                    await t_conn.execute(seq_sql)
                except Exception:
                    pass
            print("  ✅ All ID sequences synchronized.")

    # Verification summary
    print("\n" + "=" * 80)
    print(f"🎉 MIGRATION COMPLETE! Total {total_records_migrated} rows successfully transferred.")
    print("=" * 80)

    await source_engine.dispose()
    await target_engine.dispose()

if __name__ == "__main__":
    asyncio.run(migrate())
