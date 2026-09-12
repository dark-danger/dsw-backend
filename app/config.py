import os
import base64
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List, Optional

_DEFAULT_GEMINI_B64 = "QVEuQWI4Uk42SURzdDdsYXFhdGxkQi1CMjVIdjZtQm9idVdDckNvWWZ1a003aF9HcGZQQmc="

def _get_gemini_key() -> str:
    env_key = (os.getenv("GEMINI_API_KEY") or "").strip()
    if env_key:
        return env_key
    try:
        return base64.b64decode(_DEFAULT_GEMINI_B64.encode("utf-8")).decode("utf-8").strip()
    except Exception:
        return ""

class Settings(BaseSettings):
    PROJECT_NAME: str = "DSW Geeta University Portal API"
    ENV: str = "development"
    DATABASE_URL: str = os.getenv("DATABASE_URL") or os.getenv("SUPABASE_URL", "")
    JWT_SECRET: str = "geeta-university-dsw-super-secret-key-2026"
    JWT_REFRESH_SECRET: str = "geeta-university-dsw-refresh-secret-key-2026"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 hours
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    CORS_ORIGINS: List[str] = ["http://localhost:3000", "http://localhost:5173", "*"]
    UPLOAD_DIR: str = "/tmp/uploads"
    GOOGLE_SERVICE_ACCOUNT_JSON_BASE64: Optional[str] = None
    BLOB_READ_WRITE_TOKEN: Optional[str] = None
    GEMINI_API_KEY: str = _get_gemini_key()
    
    # Google Workspace OAuth 2.0 & Gmail Settings
    GOOGLE_CLIENT_ID: Optional[str] = os.getenv("GOOGLE_CLIENT_ID")
    GOOGLE_CLIENT_SECRET: Optional[str] = os.getenv("GOOGLE_CLIENT_SECRET")
    GOOGLE_OAUTH_REDIRECT_URI: Optional[str] = os.getenv("GOOGLE_OAUTH_REDIRECT_URI")
    FRONTEND_URL: str = os.getenv("FRONTEND_URL", "http://localhost:5173")
    MAIL_ENCRYPTION_SECRET: str = os.getenv("MAIL_ENCRYPTION_SECRET", "gu-dsw-mail-encryption-key-2026-secret")

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()

try:
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
except Exception:
    pass
