import os
import shutil
from typing import Optional
from datetime import datetime
from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.db import get_db, EvidenceDocument
from app.agents.evidence_agent import index_evidence_document, retrieve_evidence
from app.core.evidence_monitor import check_evidence_expiry

router = APIRouter(prefix="/evidence", tags=["Evidence"])

UPLOAD_DIR = os.path.join(os.getcwd(), "uploads", "evidence")
os.makedirs(UPLOAD_DIR, exist_ok=True)

@router.post("/upload", status_code=status.HTTP_201_CREATED)
def upload_evidence(
    file: UploadFile = File(...),
    org_name: str = Form("Acme Corp"),
    title: str = Form(...),
    expiry_date: Optional[str] = Form(None), # YYYY-MM-DD format
    evidence_type: Optional[str] = Form("policy"),
    db: Session = Depends(get_db)
):
    file_location = os.path.join(UPLOAD_DIR, f"{title}_{file.filename}")
    with open(file_location, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    parsed_expiry = None
    if expiry_date:
        try:
            parsed_expiry = datetime.strptime(expiry_date, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid expiry_date format. Use YYYY-MM-DD.")

    evidence_doc = EvidenceDocument(
        org_name=org_name,
        title=title,
        source_file_path=file_location,
        expiry_date=parsed_expiry,
        evidence_type=evidence_type
    )
    db.add(evidence_doc)
    db.commit()
    db.refresh(evidence_doc)

    index_evidence_document(evidence_document_id=evidence_doc.id, file_path=file_location, db=db)

    from app.db import ComplianceRecord
    from app.agents.evidence_agent import assess_obligation
    from app.core.state_manager import state_manager

    reassessed_recs = []
    active_recs = db.query(ComplianceRecord).filter(
        ComplianceRecord.workflow_state.in_(["REMEDIATION_IN_PROGRESS", "RE_EVALUATION_REQUIRED"])
    ).all()

    for rec in active_recs:
        assessment = assess_obligation(obligation_id=rec.obligation_id, db=db)
        res = state_manager.record_assessment(obligation_id=rec.obligation_id, assessment_result=assessment, db=db)

        if res.get("applied_status") == "COMPLIANT" and not res.get("requires_human_approval"):
            rec.workflow_state = "CLOSED"
            db.commit()

        reassessed_recs.append(rec.id)

    return {
        "evidence_document_id": evidence_doc.id,
        "title": evidence_doc.title,
        "org_name": evidence_doc.org_name,
        "expiry_date": evidence_doc.expiry_date.isoformat() if evidence_doc.expiry_date else None,
        "reassessed_records": reassessed_recs,
        "message": "Evidence uploaded, indexed, and re-verification loop completed."
    }

@router.post("/check-expiry")
def run_evidence_expiry_check(
    warning_days: int = 30,
    db: Session = Depends(get_db)
):
    try:
        res = check_evidence_expiry(db=db, warning_days=warning_days)
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Evidence expiry check failed: {str(e)}")
