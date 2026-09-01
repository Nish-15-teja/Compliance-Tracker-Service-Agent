from fastapi import APIRouter, Depends, HTTPException, Body
from typing import Optional, List
from datetime import datetime
from sqlalchemy.orm import Session
from app.db import get_db, StateTransition, RemediationProposal
from app.core.state_manager import state_manager
from app.agents.change_impact_agent import run_targeted_reassessment

router = APIRouter(tags=["Review & History"])

@router.get("/obligations/{id}/history")
def get_obligation_state_history(
    id: int,
    db: Session = Depends(get_db)
):
    history = state_manager.get_history(obligation_id=id, db=db)
    return {
        "obligation_id": id,
        "history_count": len(history),
        "history": [
            {
                "id": h.id,
                "field_changed": h.field_changed,
                "old_value": h.old_value,
                "new_value": h.new_value,
                "trigger_type": h.trigger_type,
                "reasoning": h.reasoning,
                "confidence_score": h.confidence_score,
                "required_human_approval": h.required_human_approval,
                "approval_status": h.approval_status,
                "remediation_stub_note": h.remediation_stub_note,
                "created_at": h.created_at.isoformat() if h.created_at else None,
                "decided_at": h.decided_at.isoformat() if h.decided_at else None
            }
            for h in history
        ]
    }

@router.get("/review/pending")
def get_pending_reviews(
    db: Session = Depends(get_db)
):
    from app.db import EvidenceDocument
    pending = state_manager.get_pending_approvals(db=db)
    items = []
    for p in pending:
        prop = db.query(RemediationProposal).filter(RemediationProposal.state_transition_id == p.id).first()
        rec = p.compliance_record
        ob = rec.obligation if rec else None
        clause = ob.source_clause if ob else None
        reg = clause.regulation if clause else None

        # Resolve evidence assessed info
        evidence_assessed = "None (No matching evidence excerpts found in repository)"
        if rec and rec.evidence_links:
            links_desc = []
            for el in rec.evidence_links:
                ed = el.evidence_document
                if ed:
                    links_desc.append(f"Document #{ed.id} — {ed.title}")
            if links_desc:
                evidence_assessed = ", ".join(links_desc)
        elif p.evidence_ids:
            docs_desc = []
            for eid in p.evidence_ids:
                ed = db.query(EvidenceDocument).filter(EvidenceDocument.id == eid).first()
                if ed:
                    docs_desc.append(f"Document #{ed.id} — {ed.title}")
            if docs_desc:
                evidence_assessed = ", ".join(docs_desc)
        else:
            # Fallback check if any evidence documents exist in DB
            latest_ev = db.query(EvidenceDocument).order_by(EvidenceDocument.id.desc()).first()
            if latest_ev:
                evidence_assessed = f"Audited against uploaded repository (e.g. Document #{latest_ev.id} — {latest_ev.title}) — Insufficient match"

        items.append({
            "transition_id": p.id,
            "compliance_record_id": p.compliance_record_id,
            "obligation_id": ob.id if ob else None,
            "clause_identifier": clause.clause_identifier if clause else "UNSPECIFIED",
            "clause_text": clause.clause_text if clause else "",
            "source_page": clause.source_page if clause else None,
            "regulation_title": reg.title if reg else "Regulation",
            "regulation_version": reg.version_label if reg else "",
            "requirement_text": ob.requirement_text if ob else "",
            "required_evidence_description": ob.required_evidence_description if ob else "",
            "risk_severity": ob.risk_severity if ob else "medium",
            "responsible_role": ob.responsible_role if ob else "Compliance Officer",
            "evidence_assessed": evidence_assessed,
            "field_changed": p.field_changed,
            "old_value": p.old_value or "NOT_CHECKED",
            "proposed_new_value": p.new_value,
            "trigger_type": p.trigger_type,
            "reasoning": p.reasoning or "Evidence does not satisfy the specified obligation requirement.",
            "confidence_score": p.confidence_score if p.confidence_score is not None else 0.95,
            "remediation_proposal": {
                "id": prop.id,
                "gap_explanation": prop.gap_explanation,
                "recommended_action": prop.recommended_action,
                "suggested_owner": prop.suggested_owner,
                "suggested_deadline": prop.suggested_deadline.isoformat() if prop.suggested_deadline else None,
                "priority": prop.priority,
                "status": prop.status
            } if prop else None,
            "created_at": p.created_at.isoformat() if p.created_at else None
        })

    return {
        "pending_count": len(items),
        "items": items
    }



@router.put("/remediation/{proposal_id}/edit")
def edit_remediation_proposal(
    proposal_id: int,
    recommended_action: Optional[str] = Body(None, embed=True),
    suggested_owner: Optional[str] = Body(None, embed=True),
    suggested_deadline: Optional[str] = Body(None, embed=True), # YYYY-MM-DD
    priority: Optional[str] = Body(None, embed=True),
    human_edit_notes: Optional[str] = Body("Updated by compliance manager", embed=True),
    db: Session = Depends(get_db)
):
    prop = db.query(RemediationProposal).filter(RemediationProposal.id == proposal_id).first()
    if not prop:
        raise HTTPException(status_code=404, detail=f"Remediation proposal with ID {proposal_id} not found.")

    if recommended_action:
        prop.recommended_action = recommended_action
    if suggested_owner:
        prop.suggested_owner = suggested_owner
    if priority:
        prop.priority = priority
    if suggested_deadline:
        try:
            prop.suggested_deadline = datetime.strptime(suggested_deadline, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format for suggested_deadline. Use YYYY-MM-DD.")

    prop.human_edit_notes = human_edit_notes
    prop.status = "edited"
    db.commit()
    db.refresh(prop)

    return {
        "proposal_id": prop.id,
        "status": prop.status,
        "recommended_action": prop.recommended_action,
        "suggested_owner": prop.suggested_owner,
        "suggested_deadline": prop.suggested_deadline.isoformat(),
        "priority": prop.priority,
        "human_edit_notes": prop.human_edit_notes
    }

@router.post("/review/{transition_id}/approve")
def approve_state_transition(
    transition_id: int,
    approved_by: str = Body("Auditor Admin", embed=True),
    edit_notes: Optional[str] = Body(None, embed=True),
    resolution_confirmed: bool = Body(True, embed=True),
    db: Session = Depends(get_db)
):
    try:
        res = state_manager.approve_transition(
            transition_id=transition_id,
            approved_by=approved_by,
            edit_notes=edit_notes,
            resolution_confirmed=resolution_confirmed,
            db=db
        )

        # Mark linked remediation proposal approved
        prop = db.query(RemediationProposal).filter(RemediationProposal.state_transition_id == transition_id).first()
        if prop:
            prop.status = "approved"
            prop.decided_at = datetime.now()
            db.commit()

        return res
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Approval failed: {str(e)}")

@router.post("/review/{transition_id}/reject")
def reject_state_transition(
    transition_id: int,
    approved_by: str = Body("Auditor Admin", embed=True),
    edit_notes: Optional[str] = Body(None, embed=True),
    db: Session = Depends(get_db)
):
    try:
        res = state_manager.reject_transition(
            transition_id=transition_id,
            approved_by=approved_by,
            edit_notes=edit_notes,
            db=db
        )
        prop = db.query(RemediationProposal).filter(RemediationProposal.state_transition_id == transition_id).first()
        if prop:
            prop.status = "rejected"
            prop.decided_at = datetime.now()
            db.commit()

        return res
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Rejection failed: {str(e)}")

@router.post("/review/reassess-flagged")
def reassess_flagged_records(
    compliance_record_ids: Optional[List[int]] = Body(None, embed=True),
    db: Session = Depends(get_db)
):
    from app.db import ComplianceRecord
    if not compliance_record_ids:
        flagged_recs = db.query(ComplianceRecord).filter(ComplianceRecord.workflow_state == "RE_EVALUATION_REQUIRED").all()
        compliance_record_ids = [r.id for r in flagged_recs]

    try:
        res = run_targeted_reassessment(compliance_record_ids=compliance_record_ids, db=db)
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Reassessment failed: {str(e)}")
