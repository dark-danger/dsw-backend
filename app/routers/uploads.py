import io
import os
import uuid
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, Request
from app.config import settings
from app.core.deps import get_current_user
from app.models.all_models import User

router = APIRouter(prefix="/api/uploads", tags=["Uploads"])

ALLOWED_EXTENSIONS = {
    ".pdf", ".doc", ".docx", ".jpg", ".jpeg", ".png", ".webp",
    ".gif", ".svg", ".xls", ".xlsx", ".ppt", ".pptx", ".zip", ".txt", ".csv"
}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
MAX_FILE_SIZE = 25 * 1024 * 1024 # 25 MB
MAX_IMAGE_DIMENSION = 1920 # Max width or height in px for uploaded photos


def _optimize_image_if_possible(contents: bytes, ext: str) -> bytes:
    """
    Resizes high-resolution photos and compresses JPEG/PNG/WebP before saving.
    Gracefully falls back to raw bytes if Pillow is not available.
    """
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(contents))

        # Auto-convert RGBA/P to RGB for JPEG
        if ext in [".jpg", ".jpeg"] and img.mode in ("RGBA", "P"):
            img = img.convert("RGB")

        # Downscale if exceeding max resolution
        w, h = img.size
        if max(w, h) > MAX_IMAGE_DIMENSION:
            img.thumbnail((MAX_IMAGE_DIMENSION, MAX_IMAGE_DIMENSION), Image.Resampling.LANCZOS)

        out_io = io.BytesIO()
        save_format = "JPEG" if ext in [".jpg", ".jpeg"] else ("PNG" if ext == ".png" else "WEBP")
        
        save_kwargs = {"optimize": True}
        if save_format in ("JPEG", "WEBP"):
            save_kwargs["quality"] = 82

        img.save(out_io, format=save_format, **save_kwargs)
        compressed = out_io.getvalue()

        # Only use compressed version if it is actually smaller
        return compressed if len(compressed) < len(contents) else contents
    except Exception:
        # If Pillow is missing or image decoding fails, safely return original bytes
        return contents


@router.post("")
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user)
):
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"File extension '{ext}' not allowed. Allowed: PDF, DOC, DOCX, JPG, PNG, WEBP")

    contents = await file.read()
    if len(contents) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File size exceeds maximum allowed limit of 15MB")

    # Optimize images before writing to disk
    if ext in IMAGE_EXTENSIONS and len(contents) > 200 * 1024:
        contents = _optimize_image_if_possible(contents, ext)

    filename = f"{uuid.uuid4()}{ext}"
    filepath = os.path.join(settings.UPLOAD_DIR, filename)

    with open(filepath, "wb") as f:
        f.write(contents)

    base_url = str(request.base_url).rstrip('/')
    file_url = f"{base_url}/uploads/{filename}"

    return {
        "file_url": file_url,
        "file_name": file.filename,
        "file_type": ext.lstrip("."),
        "file_size": len(contents)
    }
