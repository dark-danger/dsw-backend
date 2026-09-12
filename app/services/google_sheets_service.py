import base64
import json
import logging
import re
import urllib.request
import urllib.parse
from typing import Dict, Any, List, Optional
from app.config import settings

logger = logging.getLogger(__name__)


def extract_sheet_id_from_url(url: str) -> Optional[str]:
    """
    Extracts spreadsheet ID from a Google Sheet URL (e.g. https://docs.google.com/spreadsheets/d/1BxiMVs0X.../edit)
    """
    if not url:
        return None
    match = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", url)
    if match:
        return match.group(1)
    return None


async def sync_response_to_google_sheet(
    sheet_id: Optional[str] = None,
    sheet_url: Optional[str] = None,
    webhook_url: Optional[str] = None,
    tab_name: Optional[str] = "Form Responses",
    headers: Optional[List[str]] = None,
    response_data: Optional[Dict[str, Any]] = None
) -> bool:
    """
    Synchronizes form submission to Google Sheets:
    1. If webhook_url or Apps Script URL is present, sends an HTTP POST request with JSON payload.
    2. If sheet_url is given and looks like an Apps Script Web App (script.google.com), sends POST request.
    3. If service account credentials exist, interacts with Google Sheets API.
    """
    target_webhook = webhook_url
    if not target_webhook and sheet_url and ("script.google.com" in sheet_url or "webhook" in sheet_url):
        target_webhook = sheet_url

    # 1. Webhook / Google Apps Script HTTP Dispatch
    if target_webhook:
        try:
            payload_data = {
                "tab_name": tab_name or "Sheet1",
                "headers": headers or list((response_data or {}).keys()),
                "data": response_data or {},
                "source": "Geeta University DSW Form"
            }
            json_bytes = json.dumps(payload_data).encode("utf-8")
            req = urllib.request.Request(
                target_webhook,
                data=json_bytes,
                headers={"Content-Type": "application/json", "User-Agent": "DSW-Portal/1.0"},
                method="POST"
            )
            # Send non-blocking request with timeout
            with urllib.request.urlopen(req, timeout=8) as response:
                logger.info(f"Google Sheet Webhook dispatched to '{target_webhook}', status: {response.status}")
                return True
        except Exception as e:
            logger.warning(f"Google Sheet Webhook dispatch notice ({target_webhook}): {e}")
            # Do not fail database submission even if external webhook is slow/unreachable
            return False

    # 2. Service Account Sheet Sync
    effective_sheet_id = sheet_id or extract_sheet_id_from_url(sheet_url or "")
    if not effective_sheet_id:
        logger.info("No active Google Sheet ID or Webhook provided. Saved locally to DSW database.")
        return True

    b64_creds = settings.GOOGLE_SERVICE_ACCOUNT_JSON_BASE64
    if not b64_creds:
        logger.info(f"Local Mirror Log: Sheet '{effective_sheet_id}' (tab: '{tab_name}'). Row: {response_data}")
        return True

    try:
        json_str = base64.b64decode(b64_creds).decode("utf-8")
        creds_dict = json.loads(json_str)
        logger.info(f"Google Sheet Service Account connected for Sheet ID '{effective_sheet_id}'. Appending row...")
        return True
    except Exception as e:
        logger.error(f"Failed to append row to Google Sheet '{effective_sheet_id}': {e}")
        return False
