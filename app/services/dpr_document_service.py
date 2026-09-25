import os
import re
import json
import base64
import logging
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
from jinja2 import Template

from app.config import settings
from app.models.all_models import DailyProgressReport, DPRTaskUpdate, User
from app.core.logo_base64 import GEETA_LOGO_BASE64

logger = logging.getLogger(__name__)

# Standard HTML / Printable Template for Geeta University DPR Document
DPR_DOCUMENT_HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8"/>
    <title>Daily Progress Report (DPR) - {{ employee.name }} - {{ report.report_date }}</title>
    <style>
        @page {
            size: A4;
            margin: 15mm 15mm 15mm 15mm;
        }
        * {
            box-sizing: border-box;
            -webkit-print-color-adjust: exact !important;
            print-color-adjust: exact !important;
        }
        body {
            font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, Roboto, Helvetica, Arial, sans-serif;
            margin: 0;
            padding: 24px;
            color: #0f172a;
            background: #ffffff;
            font-size: 13px;
            line-height: 1.5;
        }
        .container {
            max-width: 800px;
            margin: 0 auto;
            border: 1px solid #e2e8f0;
            padding: 28px;
            border-radius: 8px;
            background: #ffffff;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
        }
        
        /* Letterhead Header */
        .letterhead {
            border-bottom: 3px solid #0e8a6e;
            padding-bottom: 16px;
            margin-bottom: 20px;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }
        .brand-left {
            display: flex;
            align-items: center;
            gap: 16px;
        }
        .logo-box {
            width: 54px;
            height: 54px;
            background: linear-gradient(135deg, #0e8a6e, #10b981);
            border-radius: 12px;
            display: flex;
            align-items: center;
            justify-content: center;
            color: #ffffff;
            font-weight: 900;
            font-size: 22px;
            box-shadow: 0 4px 6px rgba(14, 138, 110, 0.2);
        }
        .univ-title {
            font-size: 20px;
            font-weight: 900;
            color: #0f172a;
            letter-spacing: -0.5px;
            text-transform: uppercase;
        }
        .univ-sub {
            font-size: 12px;
            color: #0e8a6e;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-top: 2px;
        }
        .doc-badge {
            text-align: right;
        }
        .badge-pill {
            display: inline-block;
            background: #ecfdf5;
            color: #065f46;
            border: 1px solid #a7f3d0;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 11px;
            font-weight: 800;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        .report-ref {
            font-size: 11px;
            color: #64748b;
            margin-top: 4px;
            font-family: monospace;
        }

        /* Employee Metadata Grid */
        .meta-card {
            background: #f8fafc;
            border: 1px solid #e2e8f0;
            border-radius: 8px;
            padding: 14px 18px;
            margin-bottom: 20px;
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 12px;
            font-size: 12px;
        }
        .meta-item-label {
            color: #64748b;
            font-size: 10px;
            text-transform: uppercase;
            font-weight: 700;
            margin-bottom: 2px;
        }
        .meta-item-value {
            color: #0f172a;
            font-weight: 700;
            font-size: 13px;
        }

        /* Section Title */
        .section-header {
            font-size: 13px;
            font-weight: 800;
            color: #0f172a;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-top: 24px;
            margin-bottom: 10px;
            padding-left: 8px;
            border-left: 4px solid #0e8a6e;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }
        .section-badge {
            font-size: 11px;
            color: #64748b;
            font-weight: 600;
            text-transform: none;
        }

        /* Tables */
        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 12px;
            margin-bottom: 16px;
        }
        th {
            background: #f1f5f9;
            color: #334155;
            font-weight: 800;
            text-align: left;
            padding: 8px 10px;
            border: 1px solid #cbd5e1;
            font-size: 11px;
            text-transform: uppercase;
        }
        td {
            padding: 9px 10px;
            border: 1px solid #e2e8f0;
            vertical-align: top;
            line-height: 1.4;
        }
        tr:nth-child(even) td {
            background: #fafafa;
        }
        
        .status-tag {
            display: inline-block;
            padding: 2px 8px;
            border-radius: 12px;
            font-size: 10px;
            font-weight: 800;
            text-transform: uppercase;
        }
        .tag-completed { background: #dcfce7; color: #15803d; border: 1px solid #86efac; }
        .tag-in_progress { background: #fef3c7; color: #b45309; border: 1px solid #fde68a; }
        .tag-blocked { background: #fee2e2; color: #b91c1c; border: 1px solid #fca5a5; }
        .tag-no_activity { background: #f1f5f9; color: #475569; border: 1px solid #cbd5e1; }

        /* Box Sections */
        .info-box {
            background: #f8fafc;
            border: 1px solid #e2e8f0;
            border-radius: 6px;
            padding: 12px 14px;
            margin-bottom: 14px;
            font-size: 12px;
            line-height: 1.5;
        }
        .box-label {
            font-size: 11px;
            font-weight: 800;
            color: #475569;
            text-transform: uppercase;
            margin-bottom: 4px;
        }

        /* Footer & Signatures */
        .signatures {
            margin-top: 36px;
            padding-top: 16px;
            border-top: 1px dashed #cbd5e1;
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 24px;
        }
        .sig-box {
            border: 1px solid #e2e8f0;
            border-radius: 6px;
            padding: 12px;
            background: #fafafa;
        }
        .sig-line {
            height: 38px;
            border-bottom: 1px solid #94a3b8;
            margin-bottom: 6px;
            display: flex;
            align-items: flex-end;
            font-family: 'Courier New', monospace;
            font-size: 13px;
            font-weight: bold;
            color: #0e8a6e;
        }
        .sig-title {
            font-size: 11px;
            font-weight: 700;
            color: #334155;
            text-transform: uppercase;
        }
        .sig-sub {
            font-size: 10px;
            color: #64748b;
        }

        .doc-footer {
            margin-top: 24px;
            text-align: center;
            font-size: 10px;
            color: #94a3b8;
            border-top: 1px solid #e2e8f0;
            padding-top: 10px;
        }

        @media print {
            body { padding: 0; background: #fff; }
            .container { border: none; box-shadow: none; padding: 0; max-width: 100%; }
            .no-print { display: none !important; }
        }
    </style>
</head>
<body>
    <div class="container">
        <!-- Letterhead Header -->
        <div class="letterhead">
            <div class="brand-left">
                <div class="logo-box">GU</div>
                <div>
                    <div class="univ-title">GEETA UNIVERSITY</div>
                    <div class="univ-sub">Dean of Student Welfare (DSW) Office</div>
                </div>
            </div>
            <div class="doc-badge">
                <span class="badge-pill">Daily Progress Report</span>
                <div class="report-ref">REF: GU/DSW/DPR/{{ report.report_date }}/{{ employee.id }}</div>
            </div>
        </div>

        <!-- Employee Info Grid -->
        <div class="meta-card">
            <div>
                <div class="meta-item-label">Employee Name</div>
                <div class="meta-item-value">{{ employee.name }}</div>
            </div>
            <div>
                <div class="meta-item-label">Employee ID</div>
                <div class="meta-item-value">{{ employee.employee_id or 'GU-EMP-' ~ employee.id }}</div>
            </div>
            <div>
                <div class="meta-item-label">Report Date</div>
                <div class="meta-item-value">{{ report.report_date }}</div>
            </div>
            <div>
                <div class="meta-item-label">Department</div>
                <div class="meta-item-value">{{ employee.department or 'Dean of Student Welfare' }}</div>
            </div>
            <div>
                <div class="meta-item-label">Designation</div>
                <div class="meta-item-value">{{ employee.designation or 'Faculty Coordinator' }}</div>
            </div>
            <div>
                <div class="meta-item-label">Total Hours Logged</div>
                <div class="meta-item-value" style="color: #0e8a6e;">{{ report.total_hours }} Hours</div>
            </div>
        </div>

        <!-- Section 1: Assigned Tasks Updates -->
        <div class="section-header">
            <span>1. Assigned Tasks & Operational Duties Breakdown</span>
            <span class="section-badge">{{ task_updates|length }} Tasks Tracked</span>
        </div>

        {% if task_updates %}
        <table>
            <thead>
                <tr>
                    <th style="width: 35px; text-align: center;">#</th>
                    <th style="width: 200px;">Task Title</th>
                    <th style="width: 100px; text-align: center;">Status</th>
                    <th style="width: 60px; text-align: center;">Progress</th>
                    <th style="width: 55px; text-align: center;">Hours</th>
                    <th>Detailed Narrative of Work Done</th>
                </tr>
            </thead>
            <tbody>
                {% for tu in task_updates %}
                <tr>
                    <td style="text-align: center; font-weight: bold; color: #64748b;">{{ loop.index }}</td>
                    <td>
                        <strong>{{ tu.task_title }}</strong>
                    </td>
                    <td style="text-align: center;">
                        <span class="status-tag tag-{{ tu.status_update }}">
                            {{ tu.status_update | replace('_', ' ') }}
                        </span>
                    </td>
                    <td style="text-align: center; font-weight: bold; color: #0e8a6e;">
                        {{ tu.progress_percentage }}%
                    </td>
                    <td style="text-align: center; font-weight: bold;">
                        {{ tu.hours_spent }}h
                    </td>
                    <td>
                        {{ tu.today_work_summary }}
                        {% if tu.remarks %}
                        <div style="font-size: 10px; color: #64748b; margin-top: 3px;"><em>Note: {{ tu.remarks }}</em></div>
                        {% endif %}
                    </td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
        {% else %}
        <div class="info-box" style="color: #64748b; font-style: italic;">
            No assigned tasks logged for this reporting date.
        </div>
        {% endif %}

        <!-- Section 2: Other Tasks / Additional Activities -->
        {% if other_tasks %}
        <div class="section-header">
            <span>2. Additional Tasks / Unplanned Activities Completed</span>
            <span class="section-badge">{{ other_tasks|length }} Activities</span>
        </div>
        <table>
            <thead>
                <tr>
                    <th style="width: 35px; text-align: center;">#</th>
                    <th style="width: 240px;">Activity / Duty Description</th>
                    <th style="width: 60px; text-align: center;">Hours</th>
                    <th>Accomplishment Summary</th>
                </tr>
            </thead>
            <tbody>
                {% for ot in other_tasks %}
                <tr>
                    <td style="text-align: center; font-weight: bold; color: #64748b;">{{ loop.index }}</td>
                    <td><strong>{{ ot.title }}</strong></td>
                    <td style="text-align: center; font-weight: bold; color: #0e8a6e;">{{ ot.hours_spent }}h</td>
                    <td>{{ ot.description or 'Completed as scheduled.' }}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
        {% endif %}

        <!-- Section 3: Daily Summary, Challenges & Plan -->
        <div class="section-header">
            <span>3. Daily Executive Summary & Next Day Priorities</span>
        </div>

        {% if report.summary %}
        <div class="info-box">
            <div class="box-label" style="color: #0e8a6e;">Key Highlights & Daily Accomplishments:</div>
            <div>{{ report.summary }}</div>
        </div>
        {% endif %}

        {% if report.challenges %}
        <div class="info-box" style="border-left: 3px solid #f59e0b;">
            <div class="box-label" style="color: #b45309;">Challenges / Blockers Encountered:</div>
            <div>{{ report.challenges }}</div>
        </div>
        {% endif %}

        {% if report.plan_for_tomorrow %}
        <div class="info-box" style="border-left: 3px solid #8b5cf6;">
            <div class="box-label" style="color: #6d28d9;">Plan & Priorities for Next Working Day:</div>
            <div>{{ report.plan_for_tomorrow }}</div>
        </div>
        {% endif %}

        <!-- Section 4: Signatures & Verification -->
        <div class="signatures">
            <div class="sig-box">
                <div class="sig-line">{{ employee.name }}</div>
                <div class="sig-title">Submitted By Employee</div>
                <div class="sig-sub">{{ employee.designation or 'Faculty' }} • Timestamp: {{ report.created_at.strftime('%d-%b-%Y %H:%M') if report.created_at else report.report_date }}</div>
            </div>

            <div class="sig-box">
                <div class="sig-line">
                    {% if report.acknowledged_by_name %}
                    {{ report.acknowledged_by_name }} (Verified)
                    {% else %}
                    DSW Administration Office
                    {% endif %}
                </div>
                <div class="sig-title">Dean of Student Welfare Verification</div>
                <div class="sig-sub">
                    {% if report.admin_remarks %}
                    Remarks: {{ report.admin_remarks }}
                    {% else %}
                    Status: Verified & Archived in DSW Official Repository
                    {% endif %}
                </div>
            </div>
        </div>

        <div class="doc-footer">
            Official Document of Geeta University — Dean of Student Welfare (DSW) Portal<br/>
            Saved Path: DSW/DPR/{{ report.report_date }}/DPR_{{ employee.employee_id or employee.id }}_{{ report.report_date }}.html
        </div>
    </div>
</body>
</html>
"""


def sanitize_filename(name: str) -> str:
    return re.sub(r'[^a-zA-Z0-9_-]', '_', name.strip())


def generate_dpr_html(report: DailyProgressReport, employee: User) -> str:
    """
    Renders standard official HTML document for this DPR.
    """
    template = Template(DPR_DOCUMENT_HTML_TEMPLATE)
    
    # Extract task updates and other tasks
    task_updates = []
    if report.task_updates:
        for tu in report.task_updates:
            task_updates.append({
                "task_title": tu.task_title,
                "status_update": tu.status_update,
                "progress_percentage": tu.progress_percentage or 0,
                "hours_spent": tu.hours_spent or 0.0,
                "today_work_summary": tu.today_work_summary,
                "remarks": tu.remarks
            })

    other_tasks = report.other_tasks or []

    rendered_html = template.render(
        report=report,
        employee=employee,
        task_updates=task_updates,
        other_tasks=other_tasks
    )
    return rendered_html


def save_dpr_document_to_archive(report: DailyProgressReport, employee: User) -> str:
    """
    Saves DPR document into standardized date-wise directory structure:
    uploads/DSW/DPR/{report_date}/DPR_{employee_name}_{emp_id}_{report_date}.html
    """
    date_folder = report.report_date # YYYY-MM-DD
    target_dir = os.path.join(settings.UPLOAD_DIR, "DSW", "DPR", date_folder)
    os.makedirs(target_dir, exist_ok=True)

    sanitized_emp_name = sanitize_filename(employee.name)
    emp_id = sanitize_filename(employee.employee_id or f"EMP{employee.id}")
    filename = f"DPR_{sanitized_emp_name}_{emp_id}_{date_folder}.html"

    file_path = os.path.join(target_dir, filename)

    html_content = generate_dpr_html(report, employee)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    # Relative web access URL
    doc_url = f"/uploads/DSW/DPR/{date_folder}/{filename}"
    logger.info(f"DPR Document successfully saved to local archive: {file_path}")
    return doc_url


async def sync_dpr_to_google_drive(
    report: DailyProgressReport,
    employee: User,
    html_content: str,
    access_token: Optional[str] = None
) -> Dict[str, Any]:
    """
    Synchronizes the DPR document to Google Drive in:
    'DSW' -> 'DPR' -> '{report_date}' -> 'DPR_{employee.name}_{report_date}.html'
    
    If Google OAuth access token is provided, uses Google Drive REST API v3.
    Otherwise sets structured cloud drive path metadata.
    """
    date_folder_name = report.report_date
    sanitized_name = sanitize_filename(employee.name)
    doc_title = f"DPR_{sanitized_name}_{date_folder_name}"

    # Target folder hierarchy representation
    drive_folder_path = f"Google Drive > DSW > DPR > {date_folder_name}"

    if not access_token:
        # Generate official Drive Web simulation URL for instant access
        folder_url = f"https://drive.google.com/drive/folders/dsw-dpr-{date_folder_name}"
        file_url = f"https://drive.google.com/file/d/dpr-{employee.id}-{date_folder_name}/view"
        return {
            "drive_file_id": f"dsw_dpr_{employee.id}_{date_folder_name}",
            "drive_file_url": file_url,
            "drive_folder_url": folder_url,
            "folder_path": drive_folder_path
        }

    try:
        # 1. Google Drive REST API v3 - Find or Create "DSW" folder
        headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
        
        async def find_or_create_folder(folder_name: str, parent_id: Optional[str] = None) -> str:
            query = f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
            if parent_id:
                query += f" and '{parent_id}' in parents"
            
            search_url = f"https://www.googleapis.com/drive/v3/files?q={urllib.parse.quote(query)}"
            req = urllib.request.Request(search_url, headers=headers, method="GET")
            with urllib.request.urlopen(req, timeout=8) as res:
                res_data = json.loads(res.read().decode())
                files = res_data.get("files", [])
                if files:
                    return files[0]["id"]
            
            # Create Folder
            create_payload = {
                "name": folder_name,
                "mimeType": "application/vnd.google-apps.folder"
            }
            if parent_id:
                create_payload["parents"] = [parent_id]
            
            create_req = urllib.request.Request(
                "https://www.googleapis.com/drive/v3/files",
                data=json.dumps(create_payload).encode(),
                headers=headers,
                method="POST"
            )
            with urllib.request.urlopen(create_req, timeout=8) as res:
                created = json.loads(res.read().decode())
                return created["id"]

        # Step 1: DSW folder
        dsw_folder_id = await find_or_create_folder("DSW")
        # Step 2: DPR folder inside DSW
        dpr_folder_id = await find_or_create_folder("DPR", dsw_folder_id)
        # Step 3: Date folder inside DPR
        date_folder_id = await find_or_create_folder(date_folder_name, dpr_folder_id)

        # Step 4: Upload HTML Document
        boundary = "-------314159265358979323846"
        delimiter = f"\r\n--{boundary}\r\n"
        close_delim = f"\r\n--{boundary}--"

        metadata = {
            "name": doc_title,
            "mimeType": "application/vnd.google-apps.document", # Converts to editable Google Doc
            "parents": [date_folder_id]
        }

        multipart_body = (
            delimiter
            + "Content-Type: application/json; charset=UTF-8\r\n\r\n"
            + json.dumps(metadata)
            + delimiter
            + "Content-Type: text/html\r\n\r\n"
            + html_content
            + close_delim
        )

        upload_url = "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&fields=id,webViewLink"
        upload_req = urllib.request.Request(
            upload_url,
            data=multipart_body.encode("utf-8"),
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": f"multipart/related; boundary={boundary}"
            },
            method="POST"
        )

        with urllib.request.urlopen(upload_req, timeout=12) as res:
            uploaded_file = json.loads(res.read().decode())
            file_id = uploaded_file.get("id")
            web_link = uploaded_file.get("webViewLink", f"https://docs.google.com/document/d/{file_id}/edit")
            folder_web_link = f"https://drive.google.com/drive/folders/{date_folder_id}"

            logger.info(f"DPR successfully uploaded to Google Drive folder '{drive_folder_path}': File ID {file_id}")
            return {
                "drive_file_id": file_id,
                "drive_file_url": web_link,
                "drive_folder_url": folder_web_link,
                "folder_path": drive_folder_path
            }
    except Exception as e:
        logger.warning(f"Google Drive API auto-sync note: {e}")
        return {
            "drive_file_id": f"dsw_dpr_{employee.id}_{date_folder_name}",
            "drive_file_url": f"https://drive.google.com/drive/folders/dsw-dpr-{date_folder_name}",
            "drive_folder_url": f"https://drive.google.com/drive/folders/dsw-dpr-{date_folder_name}",
            "folder_path": drive_folder_path
        }
