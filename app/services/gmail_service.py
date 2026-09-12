import asyncio
import base64
import email
from email.message import EmailMessage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import hashlib
import hmac
import html
import json
import time
from typing import Dict, List, Optional, Tuple, Any
import urllib.parse

import httpx
from app.config import settings

# In-memory access token cache: { user_id: { "token": str, "expires_at": float } }
_ACCESS_TOKEN_CACHE: Dict[int, Dict[str, Any]] = {}

GMAIL_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/gmail.modify"
]

def generate_oauth_state(user_id: int, user_email: str) -> str:
    """
    Generates a cryptographically signed state token to prevent CSRF in OAuth flow.
    """
    timestamp = int(time.time())
    payload = f"{user_id}:{user_email}:{timestamp}"
    signature = hmac.new(
        settings.JWT_SECRET.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()
    raw = f"{payload}:{signature}"
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")

def verify_oauth_state(state: str, max_age_seconds: int = 1800) -> Tuple[int, str]:
    """
    Verifies the OAuth state token and returns (user_id, user_email).
    Raises ValueError if invalid or expired.
    """
    try:
        raw = base64.urlsafe_b64decode(state.encode("ascii")).decode("utf-8")
        parts = raw.split(":")
        if len(parts) != 4:
            raise ValueError("Malformed state format")
        user_id_str, user_email, timestamp_str, signature = parts
        user_id = int(user_id_str)
        timestamp = int(timestamp_str)
        
        if time.time() - timestamp > max_age_seconds:
            raise ValueError("OAuth state has expired. Please try connecting again.")
            
        payload = f"{user_id}:{user_email}:{timestamp}"
        expected_sig = hmac.new(
            settings.JWT_SECRET.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()
        
        if not hmac.compare_digest(signature, expected_sig):
            raise ValueError("OAuth state signature verification failed.")
            
        return user_id, user_email
    except Exception as e:
        raise ValueError(f"Invalid OAuth state: {str(e)}")

def get_oauth_authorization_url(user_id: int, user_email: str) -> str:
    """
    Constructs the Google OAuth 2.0 authorization URL.
    """
    client_id = settings.GOOGLE_CLIENT_ID
    redirect_uri = settings.GOOGLE_OAUTH_REDIRECT_URI
    if not client_id or not redirect_uri:
        raise ValueError("Google OAuth credentials (GOOGLE_CLIENT_ID, GOOGLE_OAUTH_REDIRECT_URI) are not configured.")
        
    state = generate_oauth_state(user_id, user_email)
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(GMAIL_SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
        "login_hint": user_email
    }
    return f"https://accounts.google.com/o/oauth2/v2/auth?{urllib.parse.urlencode(params)}"

async def exchange_code_for_tokens(code: str) -> Dict[str, Any]:
    """
    Exchanges authorization code for Google tokens and verifies user identity.
    """
    client_id = settings.GOOGLE_CLIENT_ID
    client_secret = settings.GOOGLE_CLIENT_SECRET
    redirect_uri = settings.GOOGLE_OAUTH_REDIRECT_URI
    
    if not client_id or not client_secret or not redirect_uri:
        raise ValueError("Google OAuth credentials are missing.")

    async with httpx.AsyncClient(timeout=20) as client:
        token_res = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code"
            }
        )
        if token_res.status_code != 200:
            raise ValueError(f"Failed to exchange Google OAuth code: {token_res.text}")
            
        token_data = token_res.json()
        access_token = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token")
        
        # Query Google UserInfo to verify authorized email address
        userinfo_res = await client.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {access_token}"}
        )
        if userinfo_res.status_code != 200:
            raise ValueError(f"Failed to retrieve Google profile: {userinfo_res.text}")
            
        userinfo = userinfo_res.json()
        google_email = userinfo.get("email", "").strip().lower()
        
        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_in": token_data.get("expires_in", 3600),
            "google_email": google_email,
            "google_name": userinfo.get("name", ""),
            "google_picture": userinfo.get("picture", "")
        }

async def get_valid_access_token(user_id: int, refresh_token: str) -> str:
    """
    Retrieves or refreshes a valid Google access token for the given user.
    """
    now = time.time()
    cached = _ACCESS_TOKEN_CACHE.get(user_id)
    if cached and cached.get("expires_at", 0) > now + 60:
        return cached["token"]
        
    client_id = settings.GOOGLE_CLIENT_ID
    client_secret = settings.GOOGLE_CLIENT_SECRET
    if not client_id or not client_secret:
        raise ValueError("Google OAuth credentials are not configured on server.")

    async with httpx.AsyncClient(timeout=20) as client:
        res = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token"
            }
        )
        if res.status_code != 200:
            err_body = res.text
            if "invalid_grant" in err_body or "revoked" in err_body:
                raise ValueError("GOOGLE_CONNECTION_REVOKED")
            raise ValueError(f"Failed to refresh Google token: {err_body}")
            
        data = res.json()
        new_token = data.get("access_token")
        expires_in = data.get("expires_in", 3600)
        _ACCESS_TOKEN_CACHE[user_id] = {
            "token": new_token,
            "expires_at": now + expires_in
        }
        return new_token

def _parse_email_header(headers: List[Dict[str, str]], name: str) -> str:
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""

def _parse_body_parts(payload: Dict[str, Any]) -> Tuple[str, str, List[Dict[str, Any]]]:
    """
    Recursively extracts text/plain body, text/html body, and attachments from Gmail message payload.
    """
    body_text = ""
    body_html = ""
    attachments = []

    def walk_parts(part: Dict[str, Any]):
        nonlocal body_text, body_html, attachments
        mime_type = part.get("mimeType", "").lower()
        filename = part.get("filename", "")
        body_data = part.get("body", {})
        att_id = body_data.get("attachmentId")
        size = body_data.get("size", 0)

        if filename and att_id:
            attachments.append({
                "attachment_id": att_id,
                "filename": filename,
                "mime_type": mime_type,
                "size": size
            })
            return

        data_raw = body_data.get("data")
        if data_raw:
            try:
                decoded = base64.urlsafe_b64decode(data_raw.encode("ascii")).decode("utf-8", errors="replace")
                if "text/html" in mime_type:
                    body_html = decoded
                elif "text/plain" in mime_type and not body_text:
                    body_text = decoded
            except Exception:
                pass

        for sub_part in part.get("parts", []):
            walk_parts(sub_part)

    walk_parts(payload)
    return body_text, body_html, attachments

async def fetch_message_summary(client: httpx.AsyncClient, message_id: str, access_token: str) -> Optional[Dict[str, Any]]:
    """
    Fetches lightweight metadata for a single message.
    """
    try:
        url = f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}?format=metadata&metadataHeaders=From&metadataHeaders=To&metadataHeaders=Subject&metadataHeaders=Date"
        res = await client.get(url, headers={"Authorization": f"Bearer {access_token}"})
        if res.status_code != 200:
            return None
        data = res.json()
        headers = data.get("payload", {}).get("headers", [])
        
        label_ids = data.get("labelIds", [])
        return {
            "id": data.get("id"),
            "thread_id": data.get("threadId"),
            "snippet": html.unescape(data.get("snippet", "")),
            "from": _parse_email_header(headers, "From"),
            "to": _parse_email_header(headers, "To"),
            "subject": _parse_email_header(headers, "Subject") or "(No Subject)",
            "date": _parse_email_header(headers, "Date"),
            "internal_date": int(data.get("internalDate", 0)),
            "is_unread": "UNREAD" in label_ids,
            "is_starred": "STARRED" in label_ids,
            "labels": label_ids
        }
    except Exception:
        return None

async def list_mailbox_messages(
    access_token: str,
    folder: str = "inbox",
    q: str = "",
    page_token: Optional[str] = None,
    max_results: int = 20
) -> Dict[str, Any]:
    """
    Lists mailbox messages dynamically with folder filters, search, and pagination.
    """
    folder_queries = {
        "inbox": "in:inbox",
        "starred": "is:starred",
        "sent": "in:sent",
        "drafts": "in:draft",
        "trash": "in:trash",
        "spam": "in:spam"
    }
    base_folder_q = folder_queries.get(folder.lower(), "in:inbox")
    final_query = f"{base_folder_q} {q}".strip() if q else base_folder_q

    async with httpx.AsyncClient(timeout=25) as client:
        params = {
            "q": final_query,
            "maxResults": min(max_results, 50),
        }
        if page_token:
            params["pageToken"] = page_token

        list_url = "https://gmail.googleapis.com/gmail/v1/users/me/messages"
        res = await client.get(list_url, params=params, headers={"Authorization": f"Bearer {access_token}"})
        if res.status_code != 200:
            raise ValueError(f"Failed to list messages: {res.text}")

        list_data = res.json()
        messages_meta = list_data.get("messages", [])
        next_page_token = list_data.get("nextPageToken")
        result_size_estimate = list_data.get("resultSizeEstimate", 0)

        if not messages_meta:
            return {
                "messages": [],
                "next_page_token": None,
                "result_size_estimate": 0,
                "folder": folder
            }

        # Fetch summaries in parallel
        tasks = [fetch_message_summary(client, m["id"], access_token) for m in messages_meta]
        summaries = await asyncio.gather(*tasks)
        valid_messages = [s for s in summaries if s is not None]

        return {
            "messages": valid_messages,
            "next_page_token": next_page_token,
            "result_size_estimate": result_size_estimate,
            "folder": folder
        }

async def get_message_detail(
    access_token: str,
    message_id: str,
    mark_as_read: bool = True
) -> Dict[str, Any]:
    """
    Fetches full message payload with body, headers, attachments, and marks as read if requested.
    """
    async with httpx.AsyncClient(timeout=25) as client:
        url = f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}?format=full"
        res = await client.get(url, headers={"Authorization": f"Bearer {access_token}"})
        if res.status_code != 200:
            raise ValueError(f"Failed to retrieve message: {res.text}")

        data = res.json()
        payload = data.get("payload", {})
        headers = payload.get("headers", [])
        label_ids = data.get("labelIds", [])

        body_text, body_html, attachments = _parse_body_parts(payload)

        # Mark as read automatically if unread
        if mark_as_read and "UNREAD" in label_ids:
            try:
                await client.post(
                    f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}/modify",
                    headers={"Authorization": f"Bearer {access_token}"},
                    json={"removeLabelIds": ["UNREAD"]}
                )
                label_ids = [l for l in label_ids if l != "UNREAD"]
            except Exception:
                pass

        return {
            "id": data.get("id"),
            "thread_id": data.get("threadId"),
            "snippet": html.unescape(data.get("snippet", "")),
            "from": _parse_email_header(headers, "From"),
            "to": _parse_email_header(headers, "To"),
            "cc": _parse_email_header(headers, "Cc"),
            "bcc": _parse_email_header(headers, "Bcc"),
            "subject": _parse_email_header(headers, "Subject") or "(No Subject)",
            "date": _parse_email_header(headers, "Date"),
            "message_id_header": _parse_email_header(headers, "Message-ID"),
            "in_reply_to": _parse_email_header(headers, "In-Reply-To"),
            "references": _parse_email_header(headers, "References"),
            "body_text": body_text,
            "body_html": body_html or f"<pre style='font-family:inherit;white-space:pre-wrap;'>{html.escape(body_text)}</pre>",
            "attachments": attachments,
            "is_unread": "UNREAD" in label_ids,
            "is_starred": "STARRED" in label_ids,
            "is_trash": "TRASH" in label_ids,
            "is_spam": "SPAM" in label_ids,
            "labels": label_ids
        }

async def get_attachment_data(
    access_token: str,
    message_id: str,
    attachment_id: str
) -> bytes:
    """
    Downloads an email attachment by ID from Gmail API.
    """
    async with httpx.AsyncClient(timeout=30) as client:
        url = f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}/attachments/{attachment_id}"
        res = await client.get(url, headers={"Authorization": f"Bearer {access_token}"})
        if res.status_code != 200:
            raise ValueError(f"Failed to fetch attachment: {res.text}")
        data = res.json().get("data", "")
        return base64.urlsafe_b64decode(data.encode("ascii"))

async def send_email_message(
    access_token: str,
    sender_email: str,
    to_list: List[str],
    cc_list: Optional[List[str]] = None,
    bcc_list: Optional[List[str]] = None,
    subject: str = "",
    body_html: str = "",
    in_reply_to: Optional[str] = None,
    references: Optional[str] = None,
    thread_id: Optional[str] = None,
    attachments: Optional[List[Dict[str, str]]] = None # List of {"filename": str, "content_base64": str, "mime_type": str}
) -> Dict[str, Any]:
    """
    Sends an email message strictly using the user's authentic sender address.
    """
    msg = MIMEMultipart("mixed")
    msg["From"] = sender_email
    msg["To"] = ", ".join(to_list)
    if cc_list:
        msg["Cc"] = ", ".join(cc_list)
    if bcc_list:
        msg["Bcc"] = ", ".join(bcc_list)
    msg["Subject"] = subject
    
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
    if references:
        msg["References"] = references

    # Alternative part for HTML + PlainText fallback
    alt_part = MIMEMultipart("alternative")
    plain_text = body_html.replace("<br>", "\n").replace("</p>", "\n\n")
    # Strip basic html tags for plaintext
    import re
    plain_clean = re.sub(r'<[^>]+>', '', plain_text)
    
    alt_part.attach(MIMEText(plain_clean, "plain", "utf-8"))
    alt_part.attach(MIMEText(body_html, "html", "utf-8"))
    msg.attach(alt_part)

    # Attachments
    if attachments:
        for att in attachments:
            try:
                fn = att.get("filename", "attachment")
                content_b64 = att.get("content_base64", "")
                mtype = att.get("mime_type", "application/octet-stream")
                maintype, subtype = mtype.split("/", 1) if "/" in mtype else ("application", "octet-stream")
                
                raw_data = base64.b64decode(content_b64)
                part = MIMEBase(maintype, subtype)
                part.set_payload(raw_data)
                encoders.encode_base64(part)
                part.add_header("Content-Disposition", f'attachment; filename="{fn}"')
                msg.attach(part)
            except Exception as e:
                print(f"[Attachment Encode Error] {e}")

    raw_bytes = msg.as_bytes()
    raw_b64 = base64.urlsafe_b64encode(raw_bytes).decode("ascii")

    payload: Dict[str, Any] = {"raw": raw_b64}
    if thread_id:
        payload["threadId"] = thread_id

    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.post(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
            headers={"Authorization": f"Bearer {access_token}"},
            json=payload
        )
        if res.status_code != 200:
            raise ValueError(f"Failed to send email: {res.text}")
        return res.json()

async def save_draft_message(
    access_token: str,
    sender_email: str,
    to_list: List[str],
    cc_list: Optional[List[str]] = None,
    bcc_list: Optional[List[str]] = None,
    subject: str = "",
    body_html: str = "",
    draft_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Creates or updates a Gmail draft.
    """
    msg = MIMEMultipart("alternative")
    msg["From"] = sender_email
    if to_list:
        msg["To"] = ", ".join(to_list)
    if cc_list:
        msg["Cc"] = ", ".join(cc_list)
    if bcc_list:
        msg["Bcc"] = ", ".join(bcc_list)
    msg["Subject"] = subject
    msg.attach(MIMEText(body_html, "html", "utf-8"))

    raw_bytes = msg.as_bytes()
    raw_b64 = base64.urlsafe_b64encode(raw_bytes).decode("ascii")
    payload = {"message": {"raw": raw_b64}}

    async with httpx.AsyncClient(timeout=20) as client:
        if draft_id:
            url = f"https://gmail.googleapis.com/gmail/v1/users/me/drafts/{draft_id}"
            res = await client.put(url, headers={"Authorization": f"Bearer {access_token}"}, json=payload)
        else:
            url = "https://gmail.googleapis.com/gmail/v1/users/me/drafts"
            res = await client.post(url, headers={"Authorization": f"Bearer {access_token}"}, json=payload)
            
        if res.status_code not in (200, 201):
            raise ValueError(f"Failed to save draft: {res.text}")
        return res.json()

async def toggle_star(access_token: str, message_id: str, is_starred: bool) -> bool:
    """
    Stars or unstars a message.
    """
    async with httpx.AsyncClient(timeout=15) as client:
        payload = {"removeLabelIds" if is_starred else "addLabelIds": ["STARRED"]}
        res = await client.post(
            f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}/modify",
            headers={"Authorization": f"Bearer {access_token}"},
            json=payload
        )
        return res.status_code == 200

async def toggle_read(access_token: str, message_id: str, mark_as_read: bool) -> bool:
    """
    Marks a message as read or unread.
    """
    async with httpx.AsyncClient(timeout=15) as client:
        payload = {"removeLabelIds": ["UNREAD"]} if mark_as_read else {"addLabelIds": ["UNREAD"]}
        res = await client.post(
            f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}/modify",
            headers={"Authorization": f"Bearer {access_token}"},
            json=payload
        )
        return res.status_code == 200

async def trash_message(access_token: str, message_id: str) -> bool:
    async with httpx.AsyncClient(timeout=15) as client:
        res = await client.post(
            f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}/trash",
            headers={"Authorization": f"Bearer {access_token}"}
        )
        return res.status_code == 200

async def untrash_message(access_token: str, message_id: str) -> bool:
    async with httpx.AsyncClient(timeout=15) as client:
        res = await client.post(
            f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}/untrash",
            headers={"Authorization": f"Bearer {access_token}"}
        )
        return res.status_code == 200

async def get_inbox_unread_count(access_token: str) -> int:
    """
    Retrieves the count of unread messages in the INBOX.
    """
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.get(
                "https://gmail.googleapis.com/gmail/v1/users/me/labels/INBOX",
                headers={"Authorization": f"Bearer {access_token}"}
            )
            if res.status_code == 200:
                return res.json().get("messagesUnread", 0)
    except Exception:
        pass
    return 0
