from datetime import datetime, timedelta, timezone
from typing import Any, Union
import jwt
import bcrypt
from app.config import settings

def verify_password(plain_password: str, hashed_password: str) -> bool:
    if not hashed_password or not plain_password:
        return False
    try:
        return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))
    except Exception:
        try:
            if hashed_password.startswith('$2y$') or hashed_password.startswith('$2a$'):
                normalized = ('$2b$' + hashed_password[4:]).encode('utf-8')
                return bcrypt.checkpw(plain_password.encode('utf-8'), normalized)
        except Exception:
            pass
        return False

def get_password_hash(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def create_access_token(subject: Union[str, Any], role: str, expires_delta: timedelta = None) -> str:
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode = {
        "sub": str(subject),
        "role": str(role),
        "exp": expire,
        "type": "access"
    }
    return jwt.encode(to_encode, settings.JWT_SECRET, algorithm="HS256")

def create_refresh_token(subject: Union[str, Any], role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode = {
        "sub": str(subject),
        "role": str(role),
        "exp": expire,
        "type": "refresh"
    }
    return jwt.encode(to_encode, settings.JWT_REFRESH_SECRET, algorithm="HS256")

def decode_token(token: str, secret: str = settings.JWT_SECRET) -> dict:
    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"])
        return payload
    except Exception:
        return None
