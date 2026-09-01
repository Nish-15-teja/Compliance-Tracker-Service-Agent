from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from app.db import ComplianceRecord, StateTransition, Obligation, EvidenceLink
from app.agents import remediation_agent

def requires_human_approval(assessment_result: Dict[str, Any], obligation: Obligation) -> bool:
    """
    CORRECTION 8: Explicit policy-gated function determining if human review is required.
    """
    proposed_status = assessment_result.get("proposed_compliance_status", "EVIDENCE_MISSING")
    confidence = float(assessment_result.get("confidence_score", 0.0))
    risk_sev = (obligation.risk_severity or "medium").lower()

    if (proposed_status in ["NON_COMPLIANT", "EVIDENCE_MISSING"] or
        confidence < 0.85 or
        risk_sev in ["high", "critical"]):
        return True

    if (proposed_status in ["COMPLIANT", "PARTIALLY_COMPLIANT"] and
        confidence >= 0.85 and
        risk_sev in ["low", "medium"]):
        return False

    return True

class StateManager:
    """
    Deterministic State Manager (Novelty #1). Zero LLM calls.
    Manages live state, policy-gated transition routing, and append-only state history.
    """

    def record_assessment(self, obligation_id: int, assessment_result: Dict[str, Any], db: Session) -> Dict[str, Any]:
        obligation = db.query(Obligation).filter(Obligation.id == obligation_id).first()
        if not obligation:
            raise ValueError(f"Obligation with ID {obligation_id} not found.")

        # Get or create live ComplianceRecord
        record = db.query(ComplianceRecord).filter(ComplianceRecord.obligation_id == obligation_id).first()
        if not record:
            record = ComplianceRecord(
                obligation_id=obligation_id,
                compliance_status="NOT_CHECKED",
                workflow_state="ACTIVE",
                evidence_state="VALID",
                confidence_score=0.0
            )
            db.add(record)
            db.commit()
            db.refresh(record)

        proposed_status = assessment_result.get("proposed_compliance_status", "EVIDENCE_MISSING")
        confidence = float(assessment_result.get("confidence_score", 0.0))
        reasoning = assessment_result.get("reasoning", "")
        excerpts = assessment_result.get("matched_excerpts", [])
        risk_sev = (obligation.risk_severity or "medium").lower()

        # Deterministic Policy Decision
        requires_approval = requires_human_approval(assessment_result, obligation)
        approval_status = "pending" if requires_approval else "auto_applied"

        old_status = record.compliance_status

        if not requires_approval:
            record.compliance_status = proposed_status
            record.confidence_score = confidence
            record.last_assessed_at = datetime.now(timezone.utc)
            db.commit()
        else:
            record.workflow_state = "PENDING_HUMAN_REVIEW"
            record.confidence_score = confidence
            record.last_assessed_at = datetime.now(timezone.utc)
            db.commit()

        # Insert append-only state transition record
        transition = StateTransition(
            compliance_record_id=record.id,
            field_changed="compliance_status",
            old_value=old_status,
            new_value=proposed_status,
            trigger_type="initial_check",
            trigger_description=f"Assessment run with confidence {confidence}",
            reasoning=reasoning,
            confidence_score=confidence,
            required_human_approval=requires_approval,
            approval_status=approval_status,
            remediation_stub_note=None
        )
        db.add(transition)
        db.commit()
        db.refresh(transition)

        if proposed_status in ["NON_COMPLIANT", "EVIDENCE_MISSING"]:
            rem_res = remediation_agent.generate_remediation(
                obligation_id=obligation_id,
                compliance_record_id=record.id,
                state_transition_id=transition.id,
                db=db
            )
            transition.remediation_stub_note = rem_res.get("recommended_action") or rem_res.get("message")
            db.commit()

        return {
            "compliance_record_id": record.id,
            "transition_id": transition.id,
            "proposed_status": proposed_status,
            "applied_status": record.compliance_status,
            "workflow_state": record.workflow_state,
            "requires_human_approval": requires_approval,
            "approval_status": approval_status
        }

    def approve_transition(self, transition_id: int, approved_by: str, edit_notes: Optional[str] = None, resolution_confirmed: bool = True, db: Session = None) -> Dict[str, Any]:
        transition = db.query(StateTransition).filter(StateTransition.id == transition_id).first()
        if not transition:
            raise ValueError(f"State transition with ID {transition_id} not found.")

        record = db.query(ComplianceRecord).filter(ComplianceRecord.id == transition.compliance_record_id).first()
        if not record:
            raise ValueError("Associated compliance record not found.")

        # Apply pending field change
        if transition.field_changed == "compliance_status":
            record.compliance_status = transition.new_value
        elif transition.field_changed == "workflow_state":
            record.workflow_state = transition.new_value
        elif transition.field_changed == "evidence_state":
            record.evidence_state = transition.new_value

        if resolution_confirmed:
            record.workflow_state = "ACTIVE"
        else:
            record.workflow_state = "REMEDIATION_IN_PROGRESS"

        transition.approval_status = "approved"
        transition.approved_by = approved_by
        transition.decided_at = datetime.now(timezone.utc)
        db.commit()

        return {
            "transition_id": transition.id,
            "status": "approved",
            "compliance_status": record.compliance_status,
            "workflow_state": record.workflow_state
        }

    def reject_transition(self, transition_id: int, approved_by: str, edit_notes: Optional[str] = None, db: Session = None) -> Dict[str, Any]:
        transition = db.query(StateTransition).filter(StateTransition.id == transition_id).first()
        if not transition:
            raise ValueError(f"State transition with ID {transition_id} not found.")

        record = db.query(ComplianceRecord).filter(ComplianceRecord.id == transition.compliance_record_id).first()
        if record:
            record.workflow_state = "ACTIVE"

        transition.approval_status = "rejected"
        transition.approved_by = approved_by
        transition.decided_at = datetime.now(timezone.utc)
        db.commit()

        return {
            "transition_id": transition.id,
            "status": "rejected"
        }

    def trigger_reevaluation(self, compliance_record_id: int, reason: str, db: Session) -> Dict[str, Any]:
        record = db.query(ComplianceRecord).filter(ComplianceRecord.id == compliance_record_id).first()
        if not record:
            raise ValueError(f"Compliance record with ID {compliance_record_id} not found.")

        old_wf = record.workflow_state
        record.workflow_state = "RE_EVALUATION_REQUIRED"
        db.commit()

        transition = StateTransition(
            compliance_record_id=record.id,
            field_changed="workflow_state",
            old_value=old_wf,
            new_value="RE_EVALUATION_REQUIRED",
            trigger_type="regulation_change",
            trigger_description=reason,
            required_human_approval=False,
            approval_status="auto_applied"
        )
        db.add(transition)
        db.commit()
        db.refresh(transition)

        return {
            "compliance_record_id": record.id,
            "old_workflow_state": old_wf,
            "new_workflow_state": "RE_EVALUATION_REQUIRED",
            "compliance_status_preserved": record.compliance_status
        }

    def get_history(self, obligation_id: int, db: Session) -> List[StateTransition]:
        record = db.query(ComplianceRecord).filter(ComplianceRecord.obligation_id == obligation_id).first()
        if not record:
            return []
        return db.query(StateTransition).filter(StateTransition.compliance_record_id == record.id).order_by(StateTransition.created_at.asc()).all()

    def get_pending_approvals(self, db: Session) -> List[StateTransition]:
        return db.query(StateTransition).filter(StateTransition.approval_status == "pending").order_by(StateTransition.created_at.desc()).all()

state_manager = StateManager()
