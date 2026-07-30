from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.database import get_db
from app.core.security import verify_password, get_password_hash, create_access_token, create_refresh_token, decode_token
from app.core.deps import get_current_user
from app.models.all_models import User, UserRole
from app.schemas.schemas import LoginRequest, TokenResponse, UserOut, ChangePasswordRequest
from app.config import settings

router = APIRouter(prefix="/api/auth", tags=["Auth"])

@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)):
    clean_email = payload.email.strip().lower()
    clean_pass = payload.password.strip()
    
    result = await db.execute(select(User).where(func.lower(User.email) == clean_email))
    user = result.scalar_one_or_none()
    
    if not user or not verify_password(clean_pass, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password"
        )
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is disabled"
        )

    access_token = create_access_token(subject=user.id, role=user.role.value)
    refresh_token = create_refresh_token(subject=user.id, role=user.role.value)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user=UserOut.model_validate(user)
    )

@router.post("/refresh")
async def refresh_token_endpoint(refresh_token: str, db: AsyncSession = Depends(get_db)):
    payload = decode_token(refresh_token, secret=settings.JWT_REFRESH_SECRET)
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")
    
    user_id = payload.get("sub")
    result = await db.execute(select(User).where(User.id == int(user_id)))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not active")
        
    new_access_token = create_access_token(subject=user.id, role=user.role.value)
    return {"access_token": new_access_token, "token_type": "bearer"}

@router.get("/me", response_model=UserOut)
async def get_me(current_user: User = Depends(get_current_user)):
    return UserOut.model_validate(current_user)

@router.post("/change-password")
async def change_password(
    payload: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if not verify_password(payload.old_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is invalid")
    
    current_user.password_hash = get_password_hash(payload.new_password)
    current_user.must_change_password = False
    await db.commit()
    return {"message": "Password changed successfully"}

@router.post("/logout")
async def logout():
    return {"message": "Logged out successfully"}

@router.get("/seed-demo")
async def seed_demo_accounts(db: AsyncSession = Depends(get_db)):
    accounts = [
        ("admin@geeta.edu.in", "Dr. Rajesh Sharma (Dean)", UserRole.super_admin, "admin123"),
        ("faculty@geeta.edu.in", "Prof. Amit Kumar", UserRole.faculty, "faculty123"),
        ("student@geeta.edu.in", "Riya Sharma", UserRole.student, "student123")
    ]
    created_or_updated = []
    for email, name, role, plain_pass in accounts:
        res = await db.execute(select(User).where(User.email == email))
        user = res.scalar_one_or_none()
        if not user:
            user = User(
                name=name,
                email=email,
                role=role,
                password_hash=get_password_hash(plain_pass),
                must_change_password=False,
                is_active=True
            )
            db.add(user)
            created_or_updated.append(f"Created {email}")
        else:
            user.password_hash = get_password_hash(plain_pass)
            user.is_active = True
            created_or_updated.append(f"Reset {email}")
    await db.commit()
    return {"status": "ok", "summary": created_or_updated}

