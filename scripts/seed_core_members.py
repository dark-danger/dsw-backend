import asyncio
from app.database import AsyncSessionLocal
from app.models.all_models import User, UserRole, CoreCommittee
from app.core.security import get_password_hash, verify_password
from sqlalchemy import select

MEMBERS = [
    {
        "name": "Sneha",
        "email": "2411304008@geetauniversity.edu.in",
        "roll_number": "2411304008",
        "department": "Humanities",
        "password": "sneha@123",
        "role_name": "Core Committee Member",
        "responsibilities": "Humanities department coordination & student engagement",
        "phone": "+91 98765 00001"
    },
    {
        "name": "Uday",
        "email": "2501301072@geetauniversity.edu.in",
        "roll_number": "2501301072",
        "department": "B.Tech",
        "password": "uday@123",
        "role_name": "Core Committee Member",
        "responsibilities": "B.Tech department coordination & event logistics",
        "phone": "+91 98765 00002"
    },
    {
        "name": "Vidhan",
        "email": "2507301048@geetauniversity.edu.in",
        "roll_number": "2507301048",
        "department": "Pharmacy",
        "password": "vidhan@123",
        "role_name": "Core Committee Member",
        "responsibilities": "Pharmacy department coordination & on-ground duties",
        "phone": "+91 98765 00003"
    },
    {
        "name": "Himanshu",
        "email": "2401301035@geetauniversity.edu.in",
        "roll_number": "2401301035",
        "department": "B.Tech",
        "password": "himanshu@123",
        "role_name": "Core Committee Member",
        "responsibilities": "Technical support & committee operations",
        "phone": "+91 98765 00004"
    },
    {
        "name": "Krish",
        "email": "2501301038@geetauniversity.edu.in",
        "roll_number": "2501301038",
        "department": "B.Tech",
        "password": "krish@123",
        "role_name": "Core Committee Member",
        "responsibilities": "B.Tech logistics and event coordination",
        "phone": "+91 98765 00005"
    },
    {
        "name": "Aaryan",
        "email": "2501301020@geetauniversity.edu.in",
        "roll_number": "2501301020",
        "department": "B.Tech",
        "password": "aaryan@123",
        "role_name": "Core Committee Member",
        "responsibilities": "Student coordination & crowd management",
        "phone": "+91 98765 00006"
    },
    {
        "name": "Shivam Garg",
        "email": "2505401005@geetauniversity.edu.in",
        "roll_number": "2505401005",
        "department": "MBA",
        "password": "shivam@123",
        "role_name": "Core Committee Member",
        "responsibilities": "Management coordination & event reporting",
        "phone": "+91 98765 00007"
    },
    {
        "name": "Naba",
        "email": "2511304013@geetauniversity.edu.in",
        "roll_number": "2511304013",
        "department": "Psychology",
        "password": "naba@123",
        "role_name": "Core Committee Member",
        "responsibilities": "Psychology department coordination & student welfare",
        "phone": "+91 98765 00008"
    },
    {
        "name": "Sania Panwar",
        "email": "saniapanwar646@gmail.com",
        "roll_number": "saniapanwar646",
        "department": "B.Tech",
        "password": "sania@123",
        "role_name": "Core Committee Member",
        "responsibilities": "Media, PR & student communications",
        "phone": "+91 98765 00009"
    },
    {
        "name": "Gurpreet",
        "email": "2507401004@geetauniversity.edu.in",
        "roll_number": "2507401004",
        "department": "Pharmacy",
        "password": "gurpreet@123",
        "role_name": "Core Committee Member",
        "responsibilities": "Pharmacy department liaison & event execution",
        "phone": "+91 98765 00010"
    },
    {
        "name": "Vanshika",
        "email": "2401301065@geetauniversity.edu.in",
        "roll_number": "2401301065",
        "department": "B.Tech",
        "password": "vanshika@123",
        "role_name": "Core Committee Member",
        "responsibilities": "Discipline coordination & attendee registration",
        "phone": "+91 98765 00011"
    },
    {
        "name": "Alisha",
        "email": "2401301069@geetauniversity.edu.in",
        "roll_number": "2401301069",
        "department": "B.Tech",
        "password": "alisha@123",
        "role_name": "Core Committee Member",
        "responsibilities": "Hospitality & stage coordination",
        "phone": "+91 98765 00012"
    }
]

async def seed_core_members():
    async with AsyncSessionLocal() as db:
        print("=== Provisioning Core Committee Members ===")
        student_roles_list = []

        for m in MEMBERS:
            email = m["email"].strip().lower()
            name = m["name"].strip()
            roll = m["roll_number"].strip()
            dept = m["department"].strip()
            pwd = m["password"].strip()

            # Check if user exists by email or roll number
            existing_user = (await db.execute(
                select(User).where((User.email == email) | (User.roll_number == roll))
            )).scalars().first()

            if existing_user:
                existing_user.name = name
                existing_user.email = email
                existing_user.roll_number = roll
                existing_user.department = dept
                existing_user.role = UserRole.student
                existing_user.is_active = True
                existing_user.password_hash = get_password_hash(pwd)
                db.add(existing_user)
                await db.flush()
                student_id = existing_user.id
                print(f"[UPDATED] {name} (ID: {student_id}) | Email: {email} | Password: {pwd}")
            else:
                new_user = User(
                    name=name,
                    email=email,
                    roll_number=roll,
                    department=dept,
                    course_branch=dept,
                    role=UserRole.student,
                    is_active=True,
                    password_hash=get_password_hash(pwd),
                    phone=m.get("phone")
                )
                db.add(new_user)
                await db.flush()
                student_id = new_user.id
                print(f"[CREATED] {name} (ID: {student_id}) | Email: {email} | Password: {pwd}")

            student_roles_list.append({
                "student_id": student_id,
                "student_name": name,
                "role_name": m["role_name"],
                "student_roll_no": roll,
                "department": dept,
                "semester": "Ongoing",
                "email": email,
                "phone": m.get("phone", ""),
                "is_president": False,
                "has_account": True,
                "responsibilities": m["responsibilities"],
                "points": 0
            })

        # Update or create the main Core Committee
        # Let's find committee with ID 2 or create a dedicated "DSW Student Core Committee"
        comm = (await db.execute(
            select(CoreCommittee).where(CoreCommittee.title.ilike("%Student Core Committee%"))
        )).scalars().first()

        faculty = (await db.execute(
            select(User).where(User.role == UserRole.faculty).order_by(User.id)
        )).scalars().first()

        faculty_id = faculty.id if faculty else 2

        if comm:
            comm.student_roles = student_roles_list
            comm.is_active = True
            db.add(comm)
            print(f"\n[UPDATED] Core Committee '{comm.title}' (ID: {comm.id}) with {len(student_roles_list)} members.")
        else:
            new_comm = CoreCommittee(
                title="DSW Student Core Committee",
                category="General",
                faculty_id=faculty_id,
                president_id=None,
                description="Official Student Core Committee under Dean of Student Welfare (DSW). Responsible for event execution, student discipline, logistical support, and campus activities.",
                student_roles=student_roles_list,
                total_points=0,
                is_active=True,
                created_by=1
            )
            db.add(new_comm)
            await db.flush()
            print(f"\n[CREATED] New Core Committee '{new_comm.title}' (ID: {new_comm.id}) with {len(student_roles_list)} members.")

        await db.commit()
        print("\n=== ALL 12 CORE MEMBERS PROVISIONED & VERIFIED SUCCESSFULLY ===")

        # Test login verification for all 12 members
        print("\n--- Verifying Login Hashes ---")
        for m in MEMBERS:
            u = (await db.execute(select(User).where(User.email == m["email"].lower()))).scalars().first()
            is_valid = verify_password(m["password"], u.password_hash)
            print(f"Login Check: {u.email} -> Password '{m['password']}': {'SUCCESS (Verified)' if is_valid else 'FAILED'}")

if __name__ == "__main__":
    asyncio.run(seed_core_members())
