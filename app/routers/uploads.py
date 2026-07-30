import os
import uuid
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from app.config import settings
from app.core.deps import get_current_user
from app.models.all_models import User

router = APIRouter(prefix="/api/uploads", tags=["Uploads"])

ALLOWED_EXTENSIONS = {".pdf", ".doc", ".docx", ".jpg", ".jpeg", ".png", ".webp"}
MAX_FILE_SIZE = 15 * 1024 * 1024 # 15 MB

@router.post("")
async def upload_file(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user)
):
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"File extension '{ext}' not allowed. Allowed: PDF, DOC, DOCX, JPG, PNG, WEBP")

    contents = await file.read()
    if len(contents) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File size exceeds maximum allowed limit of 15MB")

    filename = f"{uuid.uuid4()}{ext}"
    filepath = os.path.join(settings.UPLOAD_DIR, filename)

    with open(filepath, "wb") as f:
        f.write(contents)

    file_url = f"/uploads/{filename}"

    return {
        "file_url": file_url,
        "file_name": file.filename,
        "file_type": ext.lstrip("."),
        "file_size": len(contents)
    }
