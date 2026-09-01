from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session
from app.db import Obligation, ComplianceRecord, RemediationProposal, StateTransition
from app.core.llm import llm_service

DEADLINE_DAYS_MAP = {
    "critical": 7,
    "high": 30,
    "medium": 90,
    "low": 180
}

def generate_remediation(
    obligation_id: int,
    compliance_record_id: int,
    state_transition_id: Optional[int] = None,
    db: Optional[Session] = None
) -> Dict[str, Any]:
    """
    Phase 9 function: Agent 4 (Remediation Agent).
    Combines LLM gap explanation & action generation with DETERMINISTIC priority and deadline derivation.
    """
    if db is None:
        return {
            "status": "stub",
            "message": "Remediation agent called without DB session."
        }

    obligation = db.query(Obligation).filter(Obligation.id == obligation_id).first()
    record = db.query(ComplianceRecord).filter(ComplianceRecord.id == compliance_record_id).first()

    if not obligation or not record:
        raise ValueError("Obligation or Compliance Record not found for remediation generation.")

    latest_transition = db.query(StateTransition).filter(
        StateTransition.compliance_record_id == compliance_record_id
    ).order_by(StateTransition.created_at.desc()).first()

    transition_id = state_transition_id or (latest_transition.id if latest_transition else 0)

    # 1. Deterministic Derivation of Priority & Deadline from risk_severity
    risk_sev = (obligation.risk_severity or "medium").lower()
    priority = risk_sev if risk_sev in DEADLINE_DAYS_MAP else "medium"

    days_to_add = DEADLINE_DAYS_MAP.get(priority, 90)
    if obligation.deadline_policy and obligation.deadline_policy.isdigit():
        days_to_add = int(obligation.deadline_policy)

    suggested_deadline = datetime.now(timezone.utc) + timedelta(days=days_to_add)

    # 2. LLM Call for Gap Explanation & Recommended Action
    prompt = f"""You are a senior regulatory compliance remediation officer.
Generate a structured remediation proposal for the following identified compliance gap.

Obligation Requirement: {obligation.requirement_text}
Risk Severity: {obligation.risk_severity}
Required Evidence: {obligation.required_evidence_description}
Audit Reasoning: {latest_transition.reasoning if latest_transition else 'Evidence missing or insufficient.'}

Output strict JSON:
{{
  "gap_explanation": "Clear 2-3 sentence summary of the non-compliance gap.",
  "cited_requirement": "{obligation.requirement_text}",
  "evidence_considered": ["Audited evidence documents"],
  "missing_evidence": "Specific documentation or operational logs required to remediate.",
  "recommended_action": "Concrete, step-by-step corrective action.",
  "suggested_owner": "{obligation.responsible_role or 'Compliance Manager'}"
}}
"""
    llm_res = llm_service.call_llm_json(prompt, fallback_type="remediation")

    proposal = RemediationProposal(
        compliance_record_id=record.id,
        state_transition_id=transition_id,
        gap_explanation=llm_res.get("gap_explanation", "Compliance gap identified."),
        cited_requirement=obligation.requirement_text,
        evidence_considered=llm_res.get("evidence_considered", []),
        missing_evidence=llm_res.get("missing_evidence", "Required compliance evidence logs."),
        recommended_action=llm_res.get("recommended_action", "Implement corrective action policy."),
        suggested_owner=obligation.responsible_role or llm_res.get("suggested_owner", "Compliance Manager"),
        suggested_deadline=suggested_deadline,
        priority=priority,
        status="pending"
    )

    db.add(proposal)

    # Update compliance record workflow state to REMEDIATION_IN_PROGRESS
    record.workflow_state = "REMEDIATION_IN_PROGRESS"
    db.commit()
    db.refresh(proposal)

    return {
        "proposal_id": proposal.id,
        "priority": proposal.priority,
        "suggested_deadline": proposal.suggested_deadline.isoformat(),
        "gap_explanation": proposal.gap_explanation,
        "recommended_action": proposal.recommended_action,
        "suggested_owner": proposal.suggested_owner,
        "status": proposal.status
    }
