import os
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.db import Regulation, RegulationClause, Obligation, ComplianceRecord, RemediationProposal
from app.core.state_manager import state_manager
from tests.conftest import TestingSessionLocal

def test_phase10_full_human_in_loop_remediation_lifecycle():
    client = TestClient(app)
    db = TestingSessionLocal()

    reg = Regulation(title="ISO 27001", version_label="v1", source_file_path="iso.pdf")
    db.add(reg)
    db.commit()

    clause = RegulationClause(regulation_id=reg.id, regulation_version="v1", clause_identifier="A.9.2.1", clause_text="User registration and de-registration policy requirement.", source_page=1)
    db.add(clause)
    db.commit()

    ob = Obligation(
        source_clause_id=clause.id,
        requirement_text="Formal user registration and de-registration procedure must be implemented.",
        obligation_strength="mandatory",
        risk_severity="medium",
        required_evidence_description="Access control policy document and quarterly user access audit logs."
    )
    db.add(ob)
    db.commit()

    res1 = state_manager.record_assessment(
        obligation_id=ob.id,
        assessment_result={"proposed_compliance_status": "NON_COMPLIANT", "confidence_score": 0.90, "reasoning": "Missing user access policy"},
        db=db
    )
    assert res1["approval_status"] == "pending"

    prop = db.query(RemediationProposal).filter(RemediationProposal.state_transition_id == res1["transition_id"]).first()
    assert prop is not None

    edit_resp = client.put(
        f"/remediation/{prop.id}/edit",
        json={"priority": "high", "suggested_owner": "IT Security Lead", "suggested_deadline": "2026-12-31"}
    )
    assert edit_resp.status_code == 200

    app_resp = client.post(f"/review/{res1['transition_id']}/approve", json={"approved_by": "Compliance Manager", "resolution_confirmed": False})
    assert app_resp.status_code == 200

    rec = db.query(ComplianceRecord).filter(ComplianceRecord.obligation_id == ob.id).first()
    assert rec.workflow_state == "REMEDIATION_IN_PROGRESS"

    evidence_file_path = "sample_access_policy.txt"
    with open(evidence_file_path, "w", encoding="utf-8") as f:
        f.write("Section 1: Access Control Policy\nFormal user registration and de-registration procedure is implemented with quarterly access audit logs.")

    with open(evidence_file_path, "rb") as f:
        up_resp = client.post(
            "/evidence/upload",
            data={"org_name": "Acme", "title": "User Access Control Policy", "evidence_type": "policy"},
            files={"file": ("sample_access_policy.txt", f, "text/plain")}
        )

    if os.path.exists(evidence_file_path):
        os.remove(evidence_file_path)

    assert up_resp.status_code == 201

    db.refresh(rec)
    history = state_manager.get_history(obligation_id=ob.id, db=db)
    assert len(history) >= 2
