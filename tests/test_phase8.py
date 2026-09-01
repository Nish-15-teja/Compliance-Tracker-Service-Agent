import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.db import Regulation, RegulationClause, Obligation, ComplianceRecord, ClauseChangeLog
from tests.conftest import TestingSessionLocal

def test_phase8_targeted_impact_propagation():
    client = TestClient(app)
    db = TestingSessionLocal()

    reg_v1 = Regulation(title="EU GDPR", version_label="v1", source_file_path="d1.pdf")
    reg_v2 = Regulation(title="EU GDPR", version_label="v2", source_file_path="d2.pdf")
    db.add_all([reg_v1, reg_v2])
    db.commit()

    c17_old = RegulationClause(regulation_id=reg_v1.id, regulation_version="v1", clause_identifier="Article 17", clause_text="Erasure in 30 days", source_page=1)
    c5_old = RegulationClause(regulation_id=reg_v1.id, regulation_version="v1", clause_identifier="Article 5", clause_text="Data minimisation", source_page=1)
    db.add_all([c17_old, c5_old])
    db.commit()

    ob_r17 = Obligation(source_clause_id=c17_old.id, requirement_text="Erase customer data 30 days", obligation_strength="mandatory", risk_severity="high", required_evidence_description="ev")
    ob_r5 = Obligation(source_clause_id=c5_old.id, requirement_text="Data minimisation policy", obligation_strength="mandatory", risk_severity="low", required_evidence_description="ev")
    db.add_all([ob_r17, ob_r5])
    db.commit()

    rec_r17 = ComplianceRecord(obligation_id=ob_r17.id, compliance_status="COMPLIANT", workflow_state="ACTIVE", evidence_state="VALID", confidence_score=0.92)
    rec_r5 = ComplianceRecord(obligation_id=ob_r5.id, compliance_status="COMPLIANT", workflow_state="ACTIVE", evidence_state="VALID", confidence_score=0.95)
    db.add_all([rec_r17, rec_r5])
    db.commit()

    c17_new = RegulationClause(regulation_id=reg_v2.id, regulation_version="v2", clause_identifier="Article 17", clause_text="Erasure in 3 days", source_page=1)
    db.add(c17_new)
    db.commit()

    change_log = ClauseChangeLog(
        old_clause_id=c17_old.id,
        new_clause_id=c17_new.id,
        regulation_id=reg_v2.id,
        change_type="MODIFIED",
        change_reason="Erasure deadline tightened from 30 days to 3 days.",
        change_significance="significant_change"
    )
    db.add(change_log)
    db.commit()

    response = client.post(f"/regulations/{reg_v2.id}/propagate-impact")
    assert response.status_code == 200
    data = response.json()
    assert rec_r17.id in data["flagged_compliance_records"]

    db.refresh(rec_r17)
    db.refresh(rec_r5)

    assert rec_r17.compliance_status == "COMPLIANT" # Preserved!
    assert rec_r17.workflow_state == "RE_EVALUATION_REQUIRED" # Flagged!

    assert rec_r5.compliance_status == "COMPLIANT"
    assert rec_r5.workflow_state == "ACTIVE"
