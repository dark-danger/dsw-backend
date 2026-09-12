import uuid
import csv
import io
from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from typing import List, Optional, Dict, Any
from app.database import get_db
from app.core.deps import get_current_user, require_role
from app.models.all_models import User, UserRole, DynamicForm, DynamicFormResponse
from app.schemas.schemas import DynamicFormCreate, DynamicFormOut, FormFieldSchema, DynamicFormResponseOut
from app.services.google_sheets_service import sync_response_to_google_sheet
from app.services.notification_service import log_audit

router = APIRouter(prefix="/api/forms", tags=["Dynamic Public Forms"])

def build_form_out(f: DynamicForm) -> DynamicFormOut:
    fields = [FormFieldSchema(**field) for field in f.form_schema] if f.form_schema else []
    resp_count = len(f.responses) if hasattr(f, "responses") and f.responses else 0

    return DynamicFormOut(
        id=f.id,
        title=f.title,
        purpose_label=f.purpose_label,
        description=f.description,
        form_schema=fields,
        google_sheet_id=f.google_sheet_id,
        google_sheet_url=f.google_sheet_url,
        google_webhook_url=f.google_webhook_url,
        google_sheet_tab_name=f.google_sheet_tab_name,
        enable_image_upload=f.enable_image_upload or False,
        image_upload_label=f.image_upload_label or "Upload Document / Photo",
        image_upload_required=f.image_upload_required or False,
        enable_payment=f.enable_payment or False,
        payment_amount=f.payment_amount or 0.0,
        upi_id=f.upi_id,
        upi_payee_name=f.upi_payee_name,
        is_active=f.is_active,
        public_slug=f.public_slug,
        created_by=f.created_by,
        created_at=f.created_at,
        response_count=resp_count
    )

@router.post("", response_model=DynamicFormOut)
async def create_dynamic_form(
    payload: DynamicFormCreate,
    current_user: User = Depends(require_role([UserRole.super_admin])),
    db: AsyncSession = Depends(get_db)
):
    slug = f"{payload.title.lower().replace(' ', '-')[:30]}-{str(uuid.uuid4())[:6]}"
    schema_data = [field.model_dump() for field in payload.fields]

    form = DynamicForm(
        title=payload.title,
        purpose_label=payload.purpose_label,
        description=payload.description,
        form_schema=schema_data,
        google_sheet_id=payload.google_sheet_id or f"sheet_{slug}",
        google_sheet_url=payload.google_sheet_url,
        google_webhook_url=payload.google_webhook_url,
        google_sheet_tab_name=payload.google_sheet_tab_name or "Form Responses",
        enable_image_upload=payload.enable_image_upload,
        image_upload_label=payload.image_upload_label or "Upload Document / Photo",
        image_upload_required=payload.image_upload_required,
        enable_payment=payload.enable_payment,
        payment_amount=payload.payment_amount or 0.0,
        upi_id=payload.upi_id,
        upi_payee_name=payload.upi_payee_name or "Geeta University DSW",
        public_slug=slug,
        created_by=current_user.id
    )
    db.add(form)
    await db.commit()

    res = await db.execute(
        select(DynamicForm).options(selectinload(DynamicForm.responses)).where(DynamicForm.id == form.id)
    )
    created = res.scalar_one()

    await log_audit(db, action="CREATE_DYNAMIC_FORM", entity_type="form", actor_id=current_user.id, entity_id=form.id, meta={"title": form.title, "slug": slug})
    await db.commit()

    return build_form_out(created)

@router.get("", response_model=List[DynamicFormOut])
async def list_dynamic_forms(
    current_user: User = Depends(require_role([UserRole.super_admin])),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(DynamicForm).options(selectinload(DynamicForm.responses)).order_by(DynamicForm.created_at.desc())
    )
    forms = result.scalars().all()
    return [build_form_out(f) for f in forms]

@router.get("/public/{slug}", response_model=DynamicFormOut)
async def get_public_form(slug: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(DynamicForm).options(selectinload(DynamicForm.responses)).where(DynamicForm.public_slug == slug)
    )
    form = result.scalar_one_or_none()
    if not form or not form.is_active:
        raise HTTPException(status_code=404, detail="Form not found or closed to new responses")
    return build_form_out(form)

@router.post("/public/{slug}/submit")
async def submit_public_form(
    slug: str,
    payload: Dict[str, Any],
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(DynamicForm).where(DynamicForm.public_slug == slug))
    form = result.scalar_one_or_none()
    if not form or not form.is_active:
        raise HTTPException(status_code=400, detail="This form is currently closed")

    headers = [field["label"] for field in form.form_schema]
    if form.enable_image_upload:
        headers.append(form.image_upload_label or "Uploaded Image")
    if form.enable_payment:
        headers.extend(["Payment Amount (INR)", "UPI ID", "Transaction ID / UTR", "Payment Screenshot"])

    client_ip = request.client.host if request.client else "127.0.0.1"

    # Attempt Google Sheets sync (Webhook or Service Account)
    synced = await sync_response_to_google_sheet(
        sheet_id=form.google_sheet_id,
        sheet_url=form.google_sheet_url,
        webhook_url=form.google_webhook_url,
        tab_name=form.google_sheet_tab_name,
        headers=headers,
        response_data=payload
    )

    resp = DynamicFormResponse(
        form_id=form.id,
        response_data=payload,
        sync_status="synced" if synced else "pending",
        ip_address=client_ip
    )
    db.add(resp)
    await db.commit()

    return {"message": "Form submitted successfully", "submission_id": resp.id, "sync_status": resp.sync_status}

@router.get("/{form_id}/responses", response_model=List[DynamicFormResponseOut])
async def get_form_responses(
    form_id: int,
    current_user: User = Depends(require_role([UserRole.super_admin])),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(DynamicFormResponse).where(DynamicFormResponse.form_id == form_id).order_by(DynamicFormResponse.submitted_at.desc())
    )
    responses = result.scalars().all()
    return [DynamicFormResponseOut.model_validate(r) for r in responses]

@router.get("/{form_id}/responses/export")
async def export_form_responses_csv(
    form_id: int,
    current_user: User = Depends(require_role([UserRole.super_admin])),
    db: AsyncSession = Depends(get_db)
):
    form_res = await db.execute(select(DynamicForm).where(DynamicForm.id == form_id))
    form = form_res.scalar_one_or_none()
    if not form:
        raise HTTPException(status_code=404, detail="Form not found")

    resp_res = await db.execute(
        select(DynamicFormResponse).where(DynamicFormResponse.form_id == form_id).order_by(DynamicFormResponse.submitted_at.asc())
    )
    responses = resp_res.scalars().all()

    field_keys = [field["field_id"] for field in form.form_schema]
    headers = ["Submission ID", "Submitted At"] + [field["label"] for field in form.form_schema]
    if form.enable_image_upload:
        headers.append(form.image_upload_label or "Uploaded Image URL")
    if form.enable_payment:
        headers.extend(["Payment Amount (INR)", "UPI ID", "Transaction ID / UTR", "Payment Screenshot URL"])

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(headers)

    for r in responses:
        row = [r.id, r.submitted_at.strftime("%Y-%m-%d %H:%M:%S")]
        for key in field_keys:
            val = r.response_data.get(key, "")
            row.append(str(val) if not isinstance(val, list) else ", ".join(val))
        if form.enable_image_upload:
            row.append(r.response_data.get("_uploaded_image", ""))
        if form.enable_payment:
            row.extend([
                r.response_data.get("_payment_amount", form.payment_amount),
                r.response_data.get("_upi_id", form.upi_id or ""),
                r.response_data.get("_transaction_id", ""),
                r.response_data.get("_payment_screenshot", "")
            ])
        writer.writerow(row)

    output.seek(0)
    filename = f"{form.title.replace(' ', '_')}_responses.csv"
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode()),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

@router.delete("/{form_id}")
async def delete_dynamic_form(
    form_id: int,
    current_user: User = Depends(require_role([UserRole.super_admin])),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(DynamicForm).where(DynamicForm.id == form_id))
    form = result.scalar_one_or_none()
    if not form:
        raise HTTPException(status_code=404, detail="Form not found")
        
    await db.delete(form)
    await db.commit()
    return {"message": "Form deleted successfully"}

