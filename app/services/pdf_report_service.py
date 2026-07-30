from jinja2 import Template
from typing import Dict, Any, List

MICRO_REPORT_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8"/>
    <title>Micro Task Report - {{ task.title }}</title>
    <style>
        body { font-family: 'Helvetica Neue', Arial, sans-serif; margin: 40px; color: #1e293b; background: #fff; }
        .header { border-bottom: 3px solid #1e3a8a; padding-bottom: 12px; margin-bottom: 24px; display: flex; justify-content: space-between; align-items: center; }
        .logo-title { font-size: 22px; font-weight: bold; color: #1e3a8a; }
        .sub { font-size: 13px; color: #64748b; margin-top: 4px; }
        .badge { display: inline-block; padding: 4px 10px; border-radius: 12px; font-size: 12px; font-weight: bold; }
        .approved { background: #dcfce7; color: #166534; }
        .declined { background: #fee2e2; color: #991b1b; }
        .pending { background: #fef3c7; color: #92400e; }
        .section { margin-bottom: 20px; }
        .section-title { font-size: 15px; font-weight: bold; color: #1e3a8a; border-left: 4px solid #3b82f6; padding-left: 8px; margin-bottom: 8px; }
        .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; font-size: 14px; background: #f8fafc; padding: 14px; border-radius: 8px; border: 1px solid #e2e8f0; }
        .box { font-size: 14px; background: #f8fafc; padding: 14px; border-radius: 8px; border: 1px solid #e2e8f0; line-height: 1.5; }
        .footer { margin-top: 40px; font-size: 11px; color: #94a3b8; text-align: center; border-top: 1px solid #e2e8f0; padding-top: 12px; }
    </style>
</head>
<body>
    <div class="header">
        <div>
            <div class="logo-title">GEETA UNIVERSITY - DEAN OF STUDENT WELFARE</div>
            <div class="sub">Micro Task Completion Report</div>
        </div>
        <div>
            <span class="badge {{ task.status }}">{{ task.status | upper }}</span>
        </div>
    </div>

    <div class="section">
        <div class="section-title">TASK METADATA</div>
        <div class="grid">
            <div><strong>Task Title:</strong> {{ task.title }}</div>
            <div><strong>Event:</strong> {{ event.title if event else 'N/A' }}</div>
            <div><strong>Assignee (Faculty):</strong> {{ task.assignee.name if task.assignee else 'Unassigned' }}</div>
            <div><strong>Priority:</strong> {{ task.priority | upper }}</div>
            <div><strong>Due Date:</strong> {{ task.due_date or 'N/A' }}</div>
            <div><strong>Assigned Date:</strong> {{ task.created_at }}</div>
        </div>
    </div>

    <div class="section">
        <div class="section-title">TASK INSTRUCTIONS & SCOPE</div>
        <div class="box">
            {{ task.description or 'No instructions provided.' }}
        </div>
    </div>

    {% if submission %}
    <div class="section">
        <div class="section-title">FACULTY SUBMISSION DETAILS</div>
        <div class="box">
            <p><strong>Submitted Date:</strong> {{ submission.submitted_at }}</p>
            <p><strong>Completion Notes:</strong></p>
            <div>{{ submission.description or 'No description provided.' }}</div>
            {% if submission.file_url %}
            <p style="margin-top: 10px;"><strong>Proof Attachment:</strong> <a href="{{ submission.file_url }}" target="_blank">{{ submission.file_name or 'View Uploaded Proof Document' }}</a></p>
            {% endif %}
        </div>
    </div>
    {% endif %}

    {% if submission and submission.review_remarks %}
    <div class="section">
        <div class="section-title">ADMIN REVIEW REMARKS</div>
        <div class="box">
            <p><strong>Reviewed By:</strong> DSW Super Admin</p>
            <p><strong>Remarks:</strong> {{ submission.review_remarks }}</p>
        </div>
    </div>
    {% endif %}

    <div class="footer">
        Generated automatically by Geeta University DSW Digital Portal • Confidential Internal Report
    </div>
</body>
</html>
"""

MERGED_REPORT_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8"/>
    <title>Merged Event Summary Report - {{ event.title }}</title>
    <style>
        body { font-family: 'Helvetica Neue', Arial, sans-serif; margin: 40px; color: #1e293b; background: #fff; }
        .header { border-bottom: 4px solid #1e3a8a; padding-bottom: 16px; margin-bottom: 24px; text-align: center; }
        .logo-title { font-size: 26px; font-weight: bold; color: #1e3a8a; letter-spacing: 0.5px; }
        .sub { font-size: 15px; color: #475569; margin-top: 6px; font-weight: 500; }
        .section { margin-bottom: 28px; }
        .section-title { font-size: 17px; font-weight: bold; color: #1e3a8a; border-left: 4px solid #2563eb; padding-left: 10px; margin-bottom: 12px; }
        .summary-card { background: #f1f5f9; padding: 18px; border-radius: 10px; border: 1px solid #cbd5e1; display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 12px; margin-bottom: 20px; text-align: center; }
        .stat-val { font-size: 22px; font-weight: bold; color: #1e3a8a; }
        .stat-lbl { font-size: 12px; color: #64748b; text-transform: uppercase; margin-top: 4px; }
        table { width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 13px; }
        th { background: #1e3a8a; color: white; padding: 10px; text-align: left; }
        td { padding: 10px; border-bottom: 1px solid #e2e8f0; }
        tr:nth-child(even) { background: #f8fafc; }
        .page-break { page-break-before: always; margin-top: 30px; border-top: 2px dashed #cbd5e1; padding-top: 20px; }
        .box { font-size: 14px; background: #f8fafc; padding: 14px; border-radius: 8px; border: 1px solid #e2e8f0; line-height: 1.5; }
        .footer { margin-top: 40px; font-size: 11px; color: #94a3b8; text-align: center; border-top: 1px solid #e2e8f0; padding-top: 12px; }
    </style>
</head>
<body>
    <div class="header">
        <div class="logo-title">GEETA UNIVERSITY - DEAN OF STUDENT WELFARE</div>
        <div class="sub">CONSOLIDATED EVENT SUMMARY & TASK REPORT</div>
    </div>

    <div class="section">
        <div class="section-title">EVENT OVERVIEW</div>
        <div class="box">
            <h2 style="margin-top:0; color:#1e3a8a;">{{ event.title }}</h2>
            <p><strong>Description:</strong> {{ event.description or 'No detailed description.' }}</p>
            <p><strong>Event Type:</strong> {{ event.event_type }} | <strong>Venue:</strong> {{ event.venue or 'TBD' }}</p>
            <p><strong>Coordinator:</strong> {{ event.coordinator.name if event.coordinator else 'Not assigned' }}</p>
            <p><strong>Dates:</strong> {{ event.start_date }} to {{ event.end_date }}</p>
            <p><strong>Current Status:</strong> {{ event.status | upper }}</p>
        </div>
    </div>

    <div class="section">
        <div class="section-title">TASK EXECUTION SUMMARY</div>
        <div class="summary-card">
            <div>
                <div class="stat-val">{{ stats.total_tasks }}</div>
                <div class="stat-lbl">Total Tasks</div>
            </div>
            <div>
                <div class="stat-val" style="color: #166534;">{{ stats.completed_tasks }}</div>
                <div class="stat-lbl">Approved</div>
            </div>
            <div>
                <div class="stat-val" style="color: #2563eb;">{{ stats.completion_percentage }}%</div>
                <div class="stat-lbl">Completion Rate</div>
            </div>
        </div>

        <table>
            <thead>
                <tr>
                    <th>#</th>
                    <th>Task Title</th>
                    <th>Assigned Faculty</th>
                    <th>Priority</th>
                    <th>Status</th>
                </tr>
            </thead>
            <tbody>
                {% for task in tasks %}
                <tr>
                    <td>{{ loop.index }}</td>
                    <td><strong>{{ task.title }}</strong></td>
                    <td>{{ task.assignee.name if task.assignee else 'Unassigned' }}</td>
                    <td>{{ task.priority | upper }}</td>
                    <td>{{ task.status | upper }}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>

    {% for task in tasks %}
    <div class="page-break">
        <div class="section-title">TASK #{{ loop.index }}: {{ task.title }}</div>
        <div class="box">
            <p><strong>Assigned To:</strong> {{ task.assignee.name if task.assignee else 'Unassigned' }}</p>
            <p><strong>Instructions:</strong> {{ task.description or 'N/A' }}</p>
            <p><strong>Status:</strong> {{ task.status | upper }}</p>
            {% if task.submissions %}
            {% set sub = task.submissions[-1] %}
            <p><strong>Submission Notes:</strong> {{ sub.description or 'No text notes provided.' }}</p>
            {% if sub.file_url %}
            <p><strong>Proof File:</strong> <a href="{{ sub.file_url }}" target="_blank">{{ sub.file_name or 'View Document' }}</a></p>
            {% endif %}
            {% if sub.review_remarks %}
            <p><strong>Admin Remarks:</strong> {{ sub.review_remarks }}</p>
            {% endif %}
            {% else %}
            <p><em>No submission uploaded yet.</em></p>
            {% endif %}
        </div>
    </div>
    {% endfor %}

    <div class="footer">
        Generated automatically by Geeta University DSW Digital Portal • Official Event Record
    </div>
</body>
</html>
"""

def generate_micro_report_html(task_data: Dict[str, Any], event_data: Dict[str, Any], submission_data: Dict[str, Any]) -> str:
    template = Template(MICRO_REPORT_TEMPLATE)
    return template.render(task=task_data, event=event_data, submission=submission_data)

def generate_merged_report_html(event_data: Dict[str, Any], tasks_data: List[Dict[str, Any]], stats_data: Dict[str, Any]) -> str:
    template = Template(MERGED_REPORT_TEMPLATE)
    return template.render(event=event_data, tasks=tasks_data, stats=stats_data)
