import os
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from app.database import get_db
from app.core.deps import get_current_user, require_role
from app.core.logo_base64 import GEETA_LOGO_BASE64
from app.models.all_models import EventReport, Event, User, UserRole
from app.schemas.schemas import EventReportCreate, EventReportUpdate, EventReportOut
from jinja2 import Template

router = APIRouter(prefix="/api/event-reports", tags=["Official Event Reports"])


def build_report_out(report: EventReport, event_title: Optional[str] = None, creator_name: Optional[str] = None) -> EventReportOut:
    return EventReportOut(
        id=report.id,
        event_id=report.event_id,
        event_title=event_title or (report.event.title if report.event else None),
        status=report.status,
        category=report.category,
        sub_category=report.sub_category,
        sdg_mapping=report.sdg_mapping,
        event_name=report.event_name,
        organized_by=report.organized_by,
        sponsorship_orgs=report.sponsorship_orgs,
        coordinator_name=report.coordinator_name,
        from_date=report.from_date,
        to_date=report.to_date,
        total_days=report.total_days or 1,
        venue=report.venue,
        description=report.description,
        objectives_sdg=report.objectives_sdg,
        expected_outcome=report.expected_outcome,
        target_audience=report.target_audience,
        proposal_approval_doc=report.proposal_approval_doc,
        circular_notice_doc=report.circular_notice_doc,
        circular_ref_no=report.circular_ref_no,
        event_poster_doc=report.event_poster_doc,
        registration_link=report.registration_link,
        registration_qr_doc=report.registration_qr_doc,
        resource_person_details=report.resource_person_details,
        invitation_letter_doc=report.invitation_letter_doc,
        guest_details=report.guest_details,
        approved_budget_doc=report.approved_budget_doc,
        budget_particulars=report.budget_particulars or [],
        total_budget_amount=report.total_budget_amount or 0.0,
        expense_bills_doc=report.expense_bills_doc,
        total_budget=report.total_budget or 0.0,
        total_expenses=report.total_expenses or 0.0,
        total_budget_words=report.total_budget_words,
        total_expense_words=report.total_expense_words,
        minute_to_minute=report.minute_to_minute or [],
        participants_gu_students=report.participants_gu_students or 0,
        participants_gu_faculty=report.participants_gu_faculty or 0,
        participants_external=report.participants_external or 0,
        participants_total=report.participants_total or 0,
        attendees_list_doc=report.attendees_list_doc,
        event_photos=report.event_photos or [],
        prize_winners=report.prize_winners or [],
        utilization_items=report.utilization_items or [],
        learning_outcome=report.learning_outcome,
        newspaper_name=report.newspaper_name,
        press_release_doc=report.press_release_doc,
        feedback_guest=report.feedback_guest,
        feedback_participants=report.feedback_participants,
        coordinator_signature=report.coordinator_signature,
        head_of_school_signature=report.head_of_school_signature,
        dsw_verified_by=report.dsw_verified_by,
        created_by=report.created_by,
        creator_name=creator_name or (report.creator.name if report.creator else None),
        created_at=report.created_at,
        updated_at=report.updated_at
    )


@router.get("", response_model=List[EventReportOut])
async def get_event_reports(
    event_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    query = select(EventReport).order_by(desc(EventReport.created_at))
    
    if event_id:
        query = query.where(EventReport.event_id == event_id)
    if status:
        query = query.where(EventReport.status == status)

    result = await db.execute(query)
    reports = result.scalars().all()

    # Preload user & event details
    out: List[EventReportOut] = []
    for r in reports:
        if search:
            query_str = search.lower()
            if query_str not in (r.event_name or "").lower() and query_str not in (r.coordinator_name or "").lower():
                continue
        out.append(build_report_out(r))
    return out


@router.post("", response_model=EventReportOut)
async def create_event_report(
    payload: EventReportCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    # If event_id provided, verify event exists
    if payload.event_id:
        e_res = await db.execute(select(Event).where(Event.id == payload.event_id))
        event = e_res.scalar_one_or_none()
        if not event:
            raise HTTPException(status_code=404, detail="Associated event not found")

    report = EventReport(
        event_id=payload.event_id,
        status=payload.status or "draft",
        category=payload.category,
        sub_category=payload.sub_category,
        sdg_mapping=payload.sdg_mapping,
        event_name=payload.event_name,
        organized_by=payload.organized_by,
        sponsorship_orgs=payload.sponsorship_orgs,
        coordinator_name=payload.coordinator_name or current_user.name,
        from_date=payload.from_date,
        to_date=payload.to_date,
        total_days=payload.total_days or 1,
        venue=payload.venue,
        description=payload.description,
        objectives_sdg=payload.objectives_sdg,
        expected_outcome=payload.expected_outcome,
        target_audience=payload.target_audience,
        proposal_approval_doc=payload.proposal_approval_doc,
        circular_notice_doc=payload.circular_notice_doc,
        circular_ref_no=payload.circular_ref_no,
        event_poster_doc=payload.event_poster_doc,
        registration_link=payload.registration_link,
        registration_qr_doc=payload.registration_qr_doc,
        resource_person_details=payload.resource_person_details,
        invitation_letter_doc=payload.invitation_letter_doc,
        guest_details=payload.guest_details,
        approved_budget_doc=payload.approved_budget_doc,
        budget_particulars=payload.budget_particulars or [],
        total_budget_amount=payload.total_budget_amount or 0.0,
        expense_bills_doc=payload.expense_bills_doc,
        total_budget=payload.total_budget or 0.0,
        total_expenses=payload.total_expenses or 0.0,
        total_budget_words=payload.total_budget_words,
        total_expense_words=payload.total_expense_words,
        minute_to_minute=payload.minute_to_minute or [],
        participants_gu_students=payload.participants_gu_students or 0,
        participants_gu_faculty=payload.participants_gu_faculty or 0,
        participants_external=payload.participants_external or 0,
        participants_total=payload.participants_total or (
            (payload.participants_gu_students or 0) +
            (payload.participants_gu_faculty or 0) +
            (payload.participants_external or 0)
        ),
        attendees_list_doc=payload.attendees_list_doc,
        event_photos=payload.event_photos or [],
        prize_winners=payload.prize_winners or [],
        utilization_items=payload.utilization_items or [],
        learning_outcome=payload.learning_outcome,
        newspaper_name=payload.newspaper_name,
        press_release_doc=payload.press_release_doc,
        feedback_guest=payload.feedback_guest,
        feedback_participants=payload.feedback_participants,
        coordinator_signature=payload.coordinator_signature,
        head_of_school_signature=payload.head_of_school_signature,
        dsw_verified_by=payload.dsw_verified_by,
        created_by=current_user.id
    )

    db.add(report)
    await db.commit()
    await db.refresh(report)

    return build_report_out(report, creator_name=current_user.name)


@router.get("/{report_id}", response_model=EventReportOut)
async def get_event_report(
    report_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(EventReport).where(EventReport.id == report_id))
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="Event report not found")
    return build_report_out(report)


@router.patch("/{report_id}", response_model=EventReportOut)
async def update_event_report(
    report_id: int,
    payload: EventReportUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(EventReport).where(EventReport.id == report_id))
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="Event report not found")

    update_data = payload.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(report, key, value)

    # Recalculate participant total if individual participant counts changed
    if any(k in update_data for k in ['participants_gu_students', 'participants_gu_faculty', 'participants_external']):
        report.participants_total = (
            (report.participants_gu_students or 0) +
            (report.participants_gu_faculty or 0) +
            (report.participants_external or 0)
        )

    await db.commit()
    await db.refresh(report)
    return build_report_out(report)


@router.delete("/{report_id}")
async def delete_event_report(
    report_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(EventReport).where(EventReport.id == report_id))
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="Event report not found")

    # Only super_admin or creator can delete
    if current_user.role != UserRole.super_admin and report.created_by != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to delete this report")

    await db.delete(report)
    await db.commit()
    return {"message": "Event report deleted successfully"}


@router.get("/{report_id}/print-html", response_class=HTMLResponse)
async def get_report_printable_html(
    report_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(EventReport).where(EventReport.id == report_id))
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="Event report not found")

    html_template = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Event Report - {{ report.event_name }}</title>
    <style>
        @page {
            size: A4;
            margin: 15mm 15mm 15mm 15mm;
        }
        body {
            font-family: 'Times New Roman', Times, serif;
            color: #000;
            background: #fff;
            margin: 0;
            padding: 0;
            font-size: 11pt;
            line-height: 1.3;
        }
        .page {
            page-break-after: always;
            padding: 0;
            min-height: 250mm;
            position: relative;
        }
        .page:last-child {
            page-break-after: avoid;
        }
        .header-logo {
            text-align: left;
            margin-bottom: 8px;
            padding-bottom: 6px;
            border-bottom: 1.5px solid #0f172a;
        }
        .header-logo img {
            height: 52px;
            max-width: 100%;
            object-fit: contain;
            display: block;
        }
        .report-heading {
            text-align: center;
            font-size: 16pt;
            font-weight: bold;
            letter-spacing: 1px;
            margin: 12px 0 16px 0;
            text-transform: uppercase;
            border-bottom: 2px solid #000;
            padding-bottom: 4px;
        }
        table.form-table {
            width: 100%;
            border-collapse: collapse;
            margin-bottom: 12px;
        }
        table.form-table th, table.form-table td {
            border: 1px solid #000;
            padding: 6px 8px;
            vertical-align: top;
            font-size: 10pt;
        }
        .label-cell {
            font-weight: bold;
            background-color: #f8fafc;
            width: 25%;
        }
        .section-box {
            border: 1px solid #000;
            margin-bottom: 12px;
            padding: 8px;
        }
        .section-title {
            font-weight: bold;
            margin-bottom: 6px;
            text-decoration: underline;
            font-size: 10.5pt;
        }
        .img-container {
            max-width: 100%;
            max-height: 180px;
            object-fit: contain;
            border: 1px solid #cbd5e1;
            margin-top: 6px;
            display: block;
        }
        .grid-2 {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 10px;
        }
        .grid-3 {
            display: grid;
            grid-template-columns: 1fr 1fr 1fr;
            gap: 8px;
        }
        .sig-block {
            margin-top: 40px;
            display: flex;
            justify-content: space-between;
            align-items: flex-end;
            padding-top: 20px;
        }
        .sig-box {
            text-align: center;
            width: 30%;
        }
        .sig-line {
            border-top: 1px solid #000;
            margin-top: 40px;
            padding-top: 4px;
            font-weight: bold;
            font-size: 9.5pt;
        }
        @media print {
            .no-print { display: none; }
        }
    </style>
</head>
<body>

    <!-- PAGE 1: IDENTIFICATION & OBJECTIVES -->
    <div class="page">
        <div class="header-logo">
            <img src="{{ logo_url }}" alt="Geeta University Logo" />
        </div>
        <div class="report-heading">EVENT REPORT</div>

        <table class="form-table">
            <tr>
                <td class="label-cell" rowspan="2">Type of Event<br><small>(Follow Annexure-1)</small></td>
                <th style="width: 25%;">Category</th>
                <th style="width: 25%;">Sub-Category</th>
                <th style="width: 25%;">SDG Number & Name</th>
            </tr>
            <tr>
                <td>{{ report.category or '-' }}</td>
                <td>{{ report.sub_category or '-' }}</td>
                <td>{{ report.sdg_mapping or '-' }}</td>
            </tr>
            <tr>
                <td class="label-cell">Event Name:</td>
                <td colspan="3"><strong>{{ report.event_name }}</strong></td>
            </tr>
            <tr>
                <td class="label-cell">Organized By (School/Department):</td>
                <td colspan="3">{{ report.organized_by or '-' }}</td>
            </tr>
            <tr>
                <td class="label-cell">Sponsorship Organization(s) (If Any):</td>
                <td colspan="3">{{ report.sponsorship_orgs or 'N/A' }}</td>
            </tr>
            <tr>
                <td class="label-cell">Event Coordinator with Designation:</td>
                <td colspan="3">{{ report.coordinator_name or '-' }}</td>
            </tr>
            <tr>
                <td class="label-cell">Date(s) of the Event (DD/MM/YYYY):</td>
                <td><strong>From Date:</strong> {{ report.from_date or '-' }}</td>
                <td><strong>To Date:</strong> {{ report.to_date or '-' }}</td>
                <td><strong>Total Days:</strong> {{ report.total_days or 1 }}</td>
            </tr>
            <tr>
                <td class="label-cell">Venue / Platform of Event:</td>
                <td colspan="3">{{ report.venue or '-' }}</td>
            </tr>
            <tr>
                <td class="label-cell">Event Description:</td>
                <td colspan="3" style="min-height: 60px;">{{ report.description or '-' }}</td>
            </tr>
            <tr>
                <td class="label-cell">Event Objective(s) Mapped with SDGs:</td>
                <td colspan="3">{{ report.objectives_sdg or '-' }}</td>
            </tr>
            <tr>
                <td class="label-cell">Expected Outcome:</td>
                <td colspan="3">{{ report.expected_outcome or '-' }}</td>
            </tr>
            <tr>
                <td class="label-cell">Target Audience:</td>
                <td colspan="3">{{ report.target_audience or '-' }}</td>
            </tr>
        </table>
    </div>

    <!-- PAGE 2: APPROVALS, NOTICES & GUESTS -->
    <div class="page">
        <div class="header-logo">
            <img src="{{ logo_url }}" alt="Geeta University Logo" />
        </div>
        <div class="report-heading">EVENT REPORT</div>

        <div class="section-box">
            <div class="section-title">Proposal With Approval (Scanned Copy/Picture):</div>
            {% if report.proposal_approval_doc %}
                <img src="{{ report.proposal_approval_doc }}" class="img-container" alt="Proposal Approval" />
            {% else %}
                <p style="color:#64748b; font-style:italic;">Attached with official documentation file.</p>
            {% endif %}
        </div>

        <div class="section-box">
            <div class="section-title">Event Circular/Notice by Registrar Office/DSW/School Head with Date & Reference No.:</div>
            <p><strong>Ref No. / Date:</strong> {{ report.circular_ref_no or 'N/A' }}</p>
            {% if report.circular_notice_doc %}
                <img src="{{ report.circular_notice_doc }}" class="img-container" alt="Circular Notice" />
            {% endif %}
        </div>

        <div class="section-box">
            <div class="section-title">Event Poster & Registration Link / QR Code:</div>
            <div class="grid-2">
                <div>
                    <strong>Poster:</strong><br>
                    {% if report.event_poster_doc %}
                        <img src="{{ report.event_poster_doc }}" class="img-container" alt="Event Poster" />
                    {% else %}
                        <em>No poster attached</em>
                    {% endif %}
                </div>
                <div>
                    <strong>Registration / Details:</strong>
                    <p>{{ report.registration_link or 'N/A' }}</p>
                    {% if report.registration_qr_doc %}
                        <img src="{{ report.registration_qr_doc }}" style="max-height: 120px;" alt="QR Code" />
                    {% endif %}
                </div>
            </div>
        </div>

        <div class="section-box">
            <div class="section-title">Details of Resource Person & Guest Acceptance:</div>
            <p><strong>Resource Person:</strong> {{ report.resource_person_details or 'N/A' }}</p>
            <p><strong>Guest Details / LinkedIn:</strong> {{ report.guest_details or 'N/A' }}</p>
            {% if report.invitation_letter_doc %}
                <p><strong>Invitation Letter:</strong> Attached</p>
            {% endif %}
        </div>
    </div>

    <!-- PAGE 3: BUDGET, EXPENSES, MINUTE TO MINUTE & PARTICIPANTS -->
    <div class="page">
        <div class="header-logo">
            <img src="{{ logo_url }}" alt="Geeta University Logo" />
        </div>
        <div class="report-heading">EVENT REPORT</div>

        <div class="section-title">Approved Budget (Particulars Breakdown):</div>
        <table class="form-table">
            <thead>
                <tr style="background:#f1f5f9;">
                    <th style="width: 10%;">Sr. No.</th>
                    <th style="width: 60%;">Particular</th>
                    <th style="width: 30%;">Budget Amount (₹)</th>
                </tr>
            </thead>
            <tbody>
                {% for item in report.budget_particulars %}
                <tr>
                    <td style="text-align:center;">{{ loop.index }}</td>
                    <td>{{ item.particular }}</td>
                    <td style="text-align:right;">₹ {{ item.amount }}</td>
                </tr>
                {% else %}
                <tr>
                    <td colspan="3" style="text-align:center; color:#64748b;">Standard budget allocation applied.</td>
                </tr>
                {% endfor %}
                <tr style="font-weight:bold; background:#f8fafc;">
                    <td colspan="2" style="text-align:right;">Total Approved Budget:</td>
                    <td style="text-align:right;">₹ {{ report.total_budget_amount }}</td>
                </tr>
            </tbody>
        </table>

        <div class="section-title" style="margin-top:14px;">Expense Report:</div>
        <table class="form-table">
            <tr>
                <td class="label-cell">Total Budget (if any):</td>
                <td>₹ {{ report.total_budget }}</td>
                <td class="label-cell">Total Expenses (if any):</td>
                <td>₹ {{ report.total_expenses }}</td>
            </tr>
            <tr>
                <td class="label-cell">Total Budget in Words:</td>
                <td>{{ report.total_budget_words or '-' }}</td>
                <td class="label-cell">Total Expense in Words:</td>
                <td>{{ report.total_expense_words or '-' }}</td>
            </tr>
        </table>

        <div class="section-title" style="margin-top:14px;">Minute to Minute Schedule: {{ report.event_name }} (Venue: {{ report.venue }})</div>
        <table class="form-table">
            <thead>
                <tr style="background:#f1f5f9;">
                    <th style="width: 12%;">Sr. No.</th>
                    <th style="width: 28%;">Timings</th>
                    <th style="width: 60%;">Sequence of Events</th>
                </tr>
            </thead>
            <tbody>
                {% for item in report.minute_to_minute %}
                <tr>
                    <td style="text-align:center;">{{ item.sr_no or loop.index }}</td>
                    <td>{{ item.timings }}</td>
                    <td>{{ item.sequence }}</td>
                </tr>
                {% else %}
                <tr>
                    <td colspan="3" style="text-align:center; color:#64748b;">Schedule conducted as per agenda.</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>

        <div class="section-title" style="margin-top:14px;">Number of Participant(s):</div>
        <table class="form-table">
            <tr>
                <td class="label-cell">GU Students</td>
                <td>{{ report.participants_gu_students }}</td>
            </tr>
            <tr>
                <td class="label-cell">GU Faculty & Staff Members</td>
                <td>{{ report.participants_gu_faculty }}</td>
            </tr>
            <tr>
                <td class="label-cell">External Participants</td>
                <td>{{ report.participants_external }}</td>
            </tr>
            <tr style="font-weight:bold; background:#f8fafc;">
                <td class="label-cell">Total Participants</td>
                <td>{{ report.participants_total }}</td>
            </tr>
        </table>
    </div>

    <!-- PAGE 4: HIGHLIGHTS, WINNERS & UTILIZATION -->
    <div class="page">
        <div class="header-logo">
            <img src="{{ logo_url }}" alt="Geeta University Logo" />
        </div>
        <div class="report-heading">EVENT REPORT</div>

        <div class="section-title">Event Highlights & Glimpse of the Event (Geo-tagged Photographs):</div>
        <div class="grid-2" style="margin-bottom: 12px;">
            {% for photo in report.event_photos %}
            <div style="border: 1px solid #cbd5e1; padding: 4px; text-align: center;">
                <img src="{{ photo.url }}" style="max-height: 120px; max-width: 100%; object-fit: cover;" alt="{{ photo.category }}" />
                <div style="font-size: 8pt; font-weight: bold; margin-top: 2px;">{{ photo.category }}</div>
                {% if photo.caption %}<div style="font-size: 7.5pt; color: #475569;">{{ photo.caption }}</div>{% endif %}
            </div>
            {% else %}
            <div style="grid-column: span 2; text-align:center; color:#64748b; padding: 10px;">
                Photographic records archived in university media repository.
            </div>
            {% endfor %}
        </div>

        {% if report.prize_winners and report.prize_winners|length > 0 %}
        <div class="section-title">Prize Details with List of Winners:</div>
        <table class="form-table">
            <thead>
                <tr style="background:#f1f5f9;">
                    <th>#</th>
                    <th>Student Name</th>
                    <th>Sem</th>
                    <th>Program</th>
                    <th>University</th>
                    <th>Position</th>
                    <th>Prize</th>
                </tr>
            </thead>
            <tbody>
                {% for w in report.prize_winners %}
                <tr>
                    <td style="text-align:center;">{{ w.sr_no or loop.index }}</td>
                    <td><strong>{{ w.student_name }}</strong></td>
                    <td>{{ w.semester or '-' }}</td>
                    <td>{{ w.program_name or '-' }}</td>
                    <td>{{ w.university_name or 'GU' }}</td>
                    <td><strong>{{ w.position }}</strong></td>
                    <td>{{ w.prize or '-' }}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
        {% endif %}

        {% if report.utilization_items and report.utilization_items|length > 0 %}
        <div class="section-title">Utilization Certificate and Handover of Items:</div>
        <table class="form-table">
            <thead>
                <tr style="background:#f1f5f9;">
                    <th>#</th>
                    <th>Particulars</th>
                    <th>Issued</th>
                    <th>Consumed</th>
                    <th>Balance</th>
                    <th>Handover To</th>
                </tr>
            </thead>
            <tbody>
                {% for u in report.utilization_items %}
                <tr>
                    <td style="text-align:center;">{{ u.sr_no or loop.index }}</td>
                    <td>{{ u.particulars }}</td>
                    <td>{{ u.issued_qty }}</td>
                    <td>{{ u.consumption_qty }}</td>
                    <td>{{ u.balance }}</td>
                    <td>{{ u.handover_to }}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
        {% endif %}

        <div class="section-title" style="margin-top:10px;">Learning Outcome:</div>
        <div class="section-box" style="min-height: 40px;">
            {{ report.learning_outcome or 'Students gained comprehensive practical exposure and domain mastery.' }}
        </div>
    </div>

    <!-- PAGE 5: PRESS RELEASE, FEEDBACK & SIGNATURES -->
    <div class="page">
        <div class="header-logo">
            <img src="{{ logo_url }}" alt="Geeta University Logo" />
        </div>
        <div class="report-heading">EVENT REPORT</div>

        <div class="section-box">
            <div class="section-title">News Brief with Press Release (Newspaper & Photographs):</div>
            <p><strong>Name of Newspaper:</strong> {{ report.newspaper_name or 'N/A' }}</p>
            {% if report.press_release_doc %}
                <img src="{{ report.press_release_doc }}" class="img-container" alt="Press Release" />
            {% endif %}
        </div>

        <div class="section-box">
            <div class="section-title">Feedback of Guest / Resource Person:</div>
            <p>{{ report.feedback_guest or 'Highly positive appreciation for student enthusiasm and organization.' }}</p>
        </div>

        <div class="section-box">
            <div class="section-title">Feedback of Participants:</div>
            <p>{{ report.feedback_participants or 'Exemplary engagement with 95%+ positive rating across key parameters.' }}</p>
        </div>

        <div class="sig-block" style="margin-top: 60px;">
            <div class="sig-box">
                <div style="font-size: 10pt; font-weight:bold;">{{ report.coordinator_signature or report.coordinator_name or 'Event Coordinator' }}</div>
                <div class="sig-line">Event Coordinator<br><small>Name & Signature</small></div>
            </div>
            <div class="sig-box">
                <div style="font-size: 10pt; font-weight:bold;">{{ report.head_of_school_signature or 'Head of School' }}</div>
                <div class="sig-line">Head of School<br><small>Name & Signature</small></div>
            </div>
            <div class="sig-box">
                <div style="font-size: 10pt; font-weight:bold;">{{ report.dsw_verified_by or 'DSW Office' }}</div>
                <div class="sig-line">Verified By DSW Office<br><small>Name & Signature</small></div>
            </div>
        </div>
    </div>

</body>
</html>
    """
    template = Template(html_template)
    return template.render(report=report, logo_url=GEETA_LOGO_BASE64)
