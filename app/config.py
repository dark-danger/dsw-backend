import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List, Optional

class Settings(BaseSettings):
    PROJECT_NAME: str = "DSW Geeta University Portal API"
    ENV: str = "development"
    # Enforce Supabase PostgreSQL connection. SQLite in /tmp causes data loss on serverless cold starts.
    DATABASE_URL: str
    JWT_SECRET: str = "geeta-university-dsw-super-secret-key-2026"
    JWT_REFRESH_SECRET: str = "geeta-university-dsw-refresh-secret-key-2026"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 hours
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    CORS_ORIGINS: List[str] = ["http://localhost:3000", "http://localhost:5173", "*"]
    UPLOAD_DIR: str = "/tmp/uploads"
    GOOGLE_SERVICE_ACCOUNT_JSON_BASE64: Optional[str] = None
    BLOB_READ_WRITE_TOKEN: Optional[str] = None

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()

try:
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
except Exception:
    pass
