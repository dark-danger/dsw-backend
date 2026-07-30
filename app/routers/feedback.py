import csv
import io
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from typing import List, Optional, Dict, Any
from app.database import get_db
from app.core.deps import get_current_user, require_role
from app.models.all_models import User, UserRole, FeedbackForm, FeedbackQuestion, FeedbackResponse, FeedbackAnswer
from app.schemas.schemas import (
    FeedbackFormCreate, FeedbackFormOut, FeedbackQuestionOut, FeedbackSubmissionPayload
)
from app.services.notification_service import log_audit

router = APIRouter(prefix="/api/feedback", tags=["Feedback Forms"])

def build_feedback_out(f: FeedbackForm) -> FeedbackFormOut:
    q_out = []
    if hasattr(f, "questions") and f.questions:
        sorted_qs = sorted(f.questions, key=lambda q: q.order_index)
        for q in sorted_qs:
            q_out.append(FeedbackQuestionOut(
                id=q.id,
                question_text=q.question_text,
                question_type=q.question_type,
                options=q.options,
                order_index=q.order_index,
                required=q.required
            ))

    resp_count = len(f.responses) if hasattr(f, "responses") and f.responses else 0

    return FeedbackFormOut(
        id=f.id,
        title=f.title,
        description=f.description,
        require_identification=f.require_identification,
        is_active=f.is_active,
        created_by=f.created_by,
        created_at=f.created_at,
        questions=q_out,
        response_count=resp_count
    )

@router.post("", response_model=FeedbackFormOut)
async def create_feedback_form(
    payload: FeedbackFormCreate,
    current_user: User = Depends(require_role([UserRole.super_admin])),
    db: AsyncSession = Depends(get_db)
):
    form = FeedbackForm(
        title=payload.title,
        description=payload.description,
        require_identification=payload.require_identification,
        created_by=current_user.id
    )
    db.add(form)
    await db.flush()

    for idx, q in enumerate(payload.questions):
        question = FeedbackQuestion(
            form_id=form.id,
            question_text=q.question_text,
            question_type=q.question_type,
            options=q.options,
            order_index=idx,
            required=q.required
        )
        db.add(question)

    await db.commit()

    res = await db.execute(
        select(FeedbackForm).options(selectinload(FeedbackForm.questions), selectinload(FeedbackForm.responses)).where(FeedbackForm.id == form.id)
    )
    created = res.scalar_one()

    await log_audit(db, action="CREATE_FEEDBACK_FORM", entity_type="feedback_form", actor_id=current_user.id, entity_id=form.id)
    await db.commit()

    return build_feedback_out(created)

@router.get("", response_model=List[FeedbackFormOut])
async def list_feedback_forms(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(FeedbackForm)
        .options(selectinload(FeedbackForm.questions), selectinload(FeedbackForm.responses))
        .order_by(FeedbackForm.created_at.desc())
    )
    forms = result.scalars().all()
    return [build_feedback_out(f) for f in forms]

@router.get("/public/{form_id}", response_model=FeedbackFormOut)
async def get_public_feedback_form(form_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(FeedbackForm)
        .options(selectinload(FeedbackForm.questions), selectinload(FeedbackForm.responses))
        .where(FeedbackForm.id == form_id)
    )
    form = result.scalar_one_or_none()
    if not form or not form.is_active:
        raise HTTPException(status_code=404, detail="Feedback form not found or inactive")
    return build_feedback_out(form)

@router.post("/public/{form_id}/submit")
async def submit_feedback_response(
    form_id: int,
    payload: FeedbackSubmissionPayload,
    db: AsyncSession = Depends(get_db)
):
    form_res = await db.execute(select(FeedbackForm).where(FeedbackForm.id == form_id))
    form = form_res.scalar_one_or_none()
    if not form or not form.is_active:
        raise HTTPException(status_code=400, detail="This feedback form is inactive")

    fb_response = FeedbackResponse(
        form_id=form.id,
        respondent_type=payload.respondent_type,
        respondent_identifier=payload.respondent_identifier
    )
    db.add(fb_response)
    await db.flush()

    for q_id, selected in payload.answers.items():
        ans = FeedbackAnswer(
            response_id=fb_response.id,
            question_id=int(q_id),
            selected_options=selected
        )
        db.add(ans)

    await db.commit()
    return {"message": "Feedback submitted successfully"}

@router.get("/{form_id}/results")
async def get_feedback_analytics(
    form_id: int,
    current_user: User = Depends(require_role([UserRole.super_admin])),
    db: AsyncSession = Depends(get_db)
):
    form_res = await db.execute(
        select(FeedbackForm).options(selectinload(FeedbackForm.questions), selectinload(FeedbackForm.responses)).where(FeedbackForm.id == form_id)
    )
    form = form_res.scalar_one_or_none()
    if not form:
        raise HTTPException(status_code=404, detail="Feedback form not found")

    # Fetch all answers for this form
    ans_res = await db.execute(
        select(FeedbackAnswer).join(FeedbackResponse).where(FeedbackResponse.form_id == form_id)
    )
    all_answers = ans_res.scalars().all()

    analytics = []
    total_resp = len(form.responses)

    for q in sorted(form.questions, key=lambda x: x.order_index):
        q_answers = [a for a in all_answers if a.question_id == q.id]
        option_counts = {opt: 0 for opt in q.options}
        
        for a in q_answers:
            for opt in a.selected_options:
                option_counts[opt] = option_counts.get(opt, 0) + 1

        chart_data = [{"option": opt, "count": cnt, "percentage": round((cnt / total_resp * 100), 1) if total_resp > 0 else 0.0} for opt, cnt in option_counts.items()]

        analytics.append({
            "question_id": q.id,
            "question_text": q.question_text,
            "question_type": q.question_type,
            "total_answers": len(q_answers),
            "chart_data": chart_data
        })

    return {
        "form_id": form.id,
        "title": form.title,
        "total_responses": total_resp,
        "analytics": analytics
    }

@router.delete("/{form_id}")
async def delete_feedback_form(
    form_id: int,
    current_user: User = Depends(require_role([UserRole.super_admin])),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(FeedbackForm).where(FeedbackForm.id == form_id))
    form = result.scalar_one_or_none()
    if not form:
        raise HTTPException(status_code=404, detail="Feedback form not found")
        
    await db.delete(form)
    await db.commit()
    return {"message": "Feedback form deleted successfully"}

