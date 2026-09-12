import urllib.parse
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse, StreamingResponse
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.deps import get_current_user, get_db
from app.models.all_models import EmailConnection, User, UserRole
from app.services.email_crypto import decrypt_refresh_token, encrypt_refresh_token
from app.services import gmail_service

router = APIRouter(prefix="/api/email", tags=["Email & Mailbox"])

# Request & Response Schemas
class EmailStatusResponse(BaseModel):
    connected: bool
    email: Optional[str] = None
    status: str
    unread_count: int = 0
    message: Optional[str] = None

class SendEmailRequest(BaseModel):
    to: List[str]
    cc: Optional[List[str]] = Field(default_factory=list)
    bcc: Optional[List[str]] = Field(default_factory=list)
    subject: str = ""
    body_html: str = ""
    in_reply_to: Optional[str] = None
    references: Optional[str] = None
    thread_id: Optional[str] = None
    attachments: Optional[List[Dict[str, str]]] = Field(default_factory=list) # [{filename, content_base64, mime_type}]

class SaveDraftRequest(BaseModel):
    to: Optional[List[str]] = Field(default_factory=list)
    cc: Optional[List[str]] = Field(default_factory=list)
    bcc: Optional[List[str]] = Field(default_factory=list)
    subject: str = ""
    body_html: str = ""
    draft_id: Optional[str] = None

class ToggleStarRequest(BaseModel):
    is_starred: bool

class ToggleReadRequest(BaseModel):
    mark_as_read: bool

class ToggleTrashRequest(BaseModel):
    trash: bool = True

async def _get_user_connection(db: AsyncSession, user_id: int) -> Optional[EmailConnection]:
    stmt = select(EmailConnection).where(EmailConnection.user_id == user_id)
    res = await db.execute(stmt)
    return res.scalar_one_or_none()

async def _get_access_token_for_user(db: AsyncSession, user: User) -> Tuple[str, EmailConnection]:
    conn = await _get_user_connection(db, user.id)
    if not conn or conn.status != "connected":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Your university email is not connected. Please connect your Google account first."
        )

    try:
        raw_refresh_token = decrypt_refresh_token(conn.encrypted_refresh_token)
        access_token = await gmail_service.get_valid_access_token(user.id, raw_refresh_token)
        return access_token, conn
    except ValueError as ve:
        if "REVOKED" in str(ve):
            conn.status = "revoked"
            await db.commit()
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Your university email connection has expired or been revoked. Please reconnect."
            )
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Mail authentication error: {str(e)}")


@router.get("/status", response_model=EmailStatusResponse)
async def get_email_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Returns the user's Gmail connection status and active unread inbox count.
    """
    conn = await _get_user_connection(db, current_user.id)
    if not conn or conn.status != "connected":
        return EmailStatusResponse(
            connected=False,
            email=conn.email if conn else None,
            status=conn.status if conn else "not_connected",
            unread_count=0
        )

    try:
        raw_refresh_token = decrypt_refresh_token(conn.encrypted_refresh_token)
        access_token = await gmail_service.get_valid_access_token(current_user.id, raw_refresh_token)
        unread_count = await gmail_service.get_inbox_unread_count(access_token)
        return EmailStatusResponse(
            connected=True,
            email=conn.email,
            status="connected",
            unread_count=unread_count
        )
    except Exception as e:
        if "REVOKED" in str(e):
            conn.status = "revoked"
            await db.commit()
            return EmailStatusResponse(connected=False, email=conn.email, status="revoked", message="Connection revoked by Google.")
        return EmailStatusResponse(connected=True, email=conn.email, status="connected", unread_count=0)


@router.get("/connect")
async def connect_email(
    current_user: User = Depends(get_current_user)
):
    """
    Initiates the Google OAuth 2.0 authorization URL for the logged-in user.
    """
    try:
        auth_url = gmail_service.get_oauth_authorization_url(current_user.id, current_user.email)
        return {"auth_url": auth_url}
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/oauth/callback")
async def oauth_callback(
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """
    Google OAuth Callback. Verifies state, exchanges code for refresh token,
    and enforces that the authorized Google account matches the portal user.
    """
    frontend_base = settings.FRONTEND_URL.rstrip("/")

    if error or not code or not state:
        err_msg = error or "Authorization code or state is missing."
        return RedirectResponse(f"{frontend_base}/login?mail_error={urllib.parse.quote(err_msg)}")

    try:
        user_id, expected_email = gmail_service.verify_oauth_state(state)
    except Exception as e:
        return RedirectResponse(f"{frontend_base}/login?mail_error={urllib.parse.quote(f'Invalid state token: {str(e)}')}")

    # Fetch user from DB to know user's portal role for redirection
    stmt = select(User).where(User.id == user_id)
    res = await db.execute(stmt)
    user = res.scalar_one_or_none()
    if not user:
        return RedirectResponse(f"{frontend_base}/login?mail_error=User+not+found")

    role_path = "admin" if user.role == UserRole.super_admin else "faculty" if user.role == UserRole.faculty else "student"
    mail_url = f"{frontend_base}/{role_path}/mail"

    try:
        tokens = await gmail_service.exchange_code_for_tokens(code)
        google_email = tokens.get("google_email", "").strip().lower()
        refresh_token = tokens.get("refresh_token")

        if not refresh_token:
            # If Google didn't return a refresh token (because previously consented without prompt=consent)
            # Re-request consent
            return RedirectResponse(f"{mail_url}?mail_error={urllib.parse.quote('Refresh token was not provided by Google. Please reconnect.')}")

        # Enforce strict email matching: Google account MUST match portal registered email
        if google_email != expected_email.strip().lower():
            err = f"Email Mismatch: You authorized '{google_email}', but your registered portal account is '{expected_email}'. Please sign in with your official university account."
            return RedirectResponse(f"{mail_url}?mail_error={urllib.parse.quote(err)}")

        encrypted_token = encrypt_refresh_token(refresh_token)

        # Upsert EmailConnection
        conn = await _get_user_connection(db, user.id)
        if conn:
            conn.email = google_email
            conn.encrypted_refresh_token = encrypted_token
            conn.status = "connected"
            conn.updated_at = datetime.now(timezone.utc)
        else:
            conn = EmailConnection(
                user_id=user.id,
                provider="google",
                email=google_email,
                encrypted_refresh_token=encrypted_token,
                status="connected",
                scopes=" ".join(gmail_service.GMAIL_SCOPES),
                connected_at=datetime.now(timezone.utc)
            )
            db.add(conn)

        await db.commit()
        return RedirectResponse(f"{mail_url}?mail_status=connected")

    except Exception as e:
        print(f"[OAuth Callback Error] {e}")
        return RedirectResponse(f"{mail_url}?mail_error={urllib.parse.quote(str(e))}")


@router.post("/disconnect")
async def disconnect_email(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Disconnects and removes the user's stored Google connection.
    """
    stmt = delete(EmailConnection).where(EmailConnection.user_id == current_user.id)
    await db.execute(stmt)
    await db.commit()
    gmail_service._ACCESS_TOKEN_CACHE.pop(current_user.id, None)
    return {"message": "University email disconnected successfully."}


@router.get("/messages")
async def list_messages(
    folder: str = Query("inbox", description="inbox, starred, sent, drafts, trash, spam"),
    q: str = Query("", description="Optional search query filter"),
    page_token: Optional[str] = Query(None),
    max_results: int = Query(20, le=50),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Lists mailbox messages dynamically from the user's connected Gmail account.
    """
    access_token, _ = await _get_access_token_for_user(db, current_user)
    try:
        res = await gmail_service.list_mailbox_messages(
            access_token=access_token,
            folder=folder,
            q=q,
            page_token=page_token,
            max_results=max_results
        )
        return res
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Failed to fetch emails: {str(e)}")


@router.get("/messages/{message_id}")
async def get_message(
    message_id: str,
    mark_as_read: bool = Query(True),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Fetches full message details with headers, sanitized HTML body, and attachment metadata.
    """
    access_token, _ = await _get_access_token_for_user(db, current_user)
    try:
        return await gmail_service.get_message_detail(access_token, message_id, mark_as_read=mark_as_read)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Failed to get message: {str(e)}")


@router.get("/messages/{message_id}/attachments/{attachment_id}")
async def download_attachment(
    message_id: str,
    attachment_id: str,
    filename: Optional[str] = Query("attachment"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Streams the raw bytes of an email attachment safely.
    """
    access_token, _ = await _get_access_token_for_user(db, current_user)
    try:
        data_bytes = await gmail_service.get_attachment_data(access_token, message_id, attachment_id)
        return Response(
            content=data_bytes,
            media_type="application/octet-stream",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Failed to download attachment: {str(e)}")


@router.post("/send")
async def send_email(
    payload: SendEmailRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Sends an email message via Gmail API strictly enforcing From: current_user.email.
    """
    if not payload.to or len(payload.to) == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="At least one recipient ('To') is required.")

    access_token, conn = await _get_access_token_for_user(db, current_user)
    try:
        res = await gmail_service.send_email_message(
            access_token=access_token,
            sender_email=conn.email,
            to_list=payload.to,
            cc_list=payload.cc,
            bcc_list=payload.bcc,
            subject=payload.subject,
            body_html=payload.body_html,
            in_reply_to=payload.in_reply_to,
            references=payload.references,
            thread_id=payload.thread_id,
            attachments=payload.attachments
        )
        return {"status": "sent", "data": res}
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Failed to send email: {str(e)}")


@router.post("/drafts")
async def save_draft(
    payload: SaveDraftRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Saves or updates a Gmail draft.
    """
    access_token, conn = await _get_access_token_for_user(db, current_user)
    try:
        res = await gmail_service.save_draft_message(
            access_token=access_token,
            sender_email=conn.email,
            to_list=payload.to or [],
            cc_list=payload.cc,
            bcc_list=payload.bcc,
            subject=payload.subject,
            body_html=payload.body_html,
            draft_id=payload.draft_id
        )
        return {"status": "saved", "data": res}
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Failed to save draft: {str(e)}")


@router.post("/messages/{message_id}/star")
async def toggle_star(
    message_id: str,
    payload: ToggleStarRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    access_token, _ = await _get_access_token_for_user(db, current_user)
    success = await gmail_service.toggle_star(access_token, message_id, payload.is_starred)
    return {"success": success}


@router.post("/messages/{message_id}/read")
async def toggle_read(
    message_id: str,
    payload: ToggleReadRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    access_token, _ = await _get_access_token_for_user(db, current_user)
    success = await gmail_service.toggle_read(access_token, message_id, payload.mark_as_read)
    return {"success": success}


@router.post("/messages/{message_id}/trash")
async def toggle_trash(
    message_id: str,
    payload: ToggleTrashRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    access_token, _ = await _get_access_token_for_user(db, current_user)
    if payload.trash:
        success = await gmail_service.trash_message(access_token, message_id)
    else:
        success = await gmail_service.untrash_message(access_token, message_id)
    return {"success": success}
