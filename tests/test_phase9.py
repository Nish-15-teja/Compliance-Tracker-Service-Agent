import pytest
from datetime import datetime, timezone, timedelta
from app.db import Regulation, RegulationClause, Obligation, ComplianceRecord, RemediationProposal
from app.agents.remediation_agent import generate_remediation
from tests.conftest import TestingSessionLocal

def test_phase9_remediation_agent_deterministic_deadlines():
    db = TestingSessionLocal()

    reg = Regulation(title="Critical Infra Reg", version_label="v1", source_file_path="d.pdf")
    db.add(reg)
    db.commit()

    clause = RegulationClause(regulation_id=reg.id, regulation_version="v1", clause_identifier="Art 10", clause_text="Breach notification in 72h", source_page=1)
    db.add(clause)
    db.commit()

    ob_crit = Obligation(
        source_clause_id=clause.id,
        requirement_text="Report data breaches within 72 hours to regulator.",
        obligation_strength="mandatory",
        risk_severity="critical",
        responsible_role="Chief Information Security Officer",
        required_evidence_description="Breach notification log and response plan."
    )
    db.add(ob_crit)
    db.commit()

    rec = ComplianceRecord(obligation_id=ob_crit.id, compliance_status="NON_COMPLIANT", workflow_state="ACTIVE", evidence_state="VALID")
    db.add(rec)
    db.commit()

    res = generate_remediation(obligation_id=ob_crit.id, compliance_record_id=rec.id, db=db)

    assert res["priority"] == "critical"
    assert res["suggested_owner"] == "Chief Information Security Officer"
    assert res["gap_explanation"] is not None
    assert res["recommended_action"] is not None

    proposal = db.query(RemediationProposal).filter(RemediationProposal.id == res["proposal_id"]).first()
    assert proposal is not None
    assert proposal.priority == "critical"

    expected_deadline_min = datetime.now(timezone.utc) + timedelta(days=6)
    expected_deadline_max = datetime.now(timezone.utc) + timedelta(days=8)
    
    prop_deadline = proposal.suggested_deadline
    if prop_deadline.tzinfo is None:
        prop_deadline = prop_deadline.replace(tzinfo=timezone.utc)

    assert expected_deadline_min <= prop_deadline <= expected_deadline_max
