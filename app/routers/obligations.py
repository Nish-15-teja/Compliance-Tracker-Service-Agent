from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.db import get_db, Obligation, RegulationClause, ComplianceRecord, Regulation
from app.agents.evidence_agent import retrieve_evidence, assess_obligation
from app.core.state_manager import state_manager

router = APIRouter(prefix="/obligations", tags=["Obligations"])

@router.get("")
def list_obligations(
    regulation_id: Optional[int] = Query(None, description="Filter obligations by specific regulation ID"),
    db: Session = Depends(get_db)
):
    try:
        query = db.query(Obligation)
        if regulation_id is not None:
            query = query.join(Obligation.source_clause).filter(RegulationClause.regulation_id == regulation_id)

        results = query.all()
        output = []
        for ob in results:
            clause = ob.source_clause
            reg = clause.regulation if clause else None
            record = ob.compliance_record
            output.append({
                "id": ob.id,
                "requirement_text": ob.requirement_text,
                "obligation_strength": ob.obligation_strength,
                "risk_severity": ob.risk_severity,
                "framework": ob.framework,
                "department": ob.department,
                "responsible_role": ob.responsible_role,
                "required_evidence_description": ob.required_evidence_description,
                "frequency": ob.frequency,
                "deadline_policy": ob.deadline_policy,
                "clause_identifier": clause.clause_identifier if clause else "UNSPECIFIED",
                "source_page": clause.source_page if clause else None,
                "source_section": clause.source_section if clause else None,
                "regulation_id": reg.id if reg else (clause.regulation_id if clause else None),
                "regulation_title": reg.title if reg else "Regulation",
                "regulation_version": reg.version_label if reg else "v1.0",
                "compliance_status": record.compliance_status if record else "NOT_CHECKED",
                "workflow_state": record.workflow_state if record else "ACTIVE",
                "evidence_state": record.evidence_state if record else "VALID",
                "confidence_score": record.confidence_score if record else 0.0,
            })
        return output
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list obligations: {str(e)}")

@router.get("/{id}/evidence-candidates")
def get_evidence_candidates(
    id: int,
    k: int = 5,
    db: Session = Depends(get_db)
):
    try:
        candidates = retrieve_evidence(obligation_id=id, db=db, k=k)
        return {
            "obligation_id": id,
            "candidate_count": len(candidates),
            "candidates": candidates
        }
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to retrieve evidence candidates: {str(e)}")

@router.post("/{id}/assess")
def assess_obligation_endpoint(
    id: int,
    record_state: bool = Query(False, description="Whether to record state transition in compliance records"),
    db: Session = Depends(get_db)
):
    try:
        assessment_result = assess_obligation(obligation_id=id, db=db)
        state_record = None
        if record_state:
            state_record = state_manager.record_assessment(obligation_id=id, assessment_result=assessment_result, db=db)

        return {
            "obligation_id": id,
            "assessment_result": assessment_result,
            "state_record": state_record
        }
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Compliance assessment failed: {str(e)}")
