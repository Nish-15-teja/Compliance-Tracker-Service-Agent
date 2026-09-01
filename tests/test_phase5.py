import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.db import Regulation, RegulationClause, Obligation, ComplianceRecord
from tests.conftest import TestingSessionLocal

def test_phase5_compliance_assessment():
    client = TestClient(app)
    db = TestingSessionLocal()

    reg = Regulation(title="Data Privacy Standard", version_label="v1", source_file_path="dummy.pdf")
    db.add(reg)
    db.commit()

    clause = RegulationClause(
        regulation_id=reg.id,
        regulation_version="v1",
        clause_identifier="Art 17",
        clause_text="Right to erasure (right to be forgotten).",
        source_page=1
    )
    db.add(clause)
    db.commit()

    ob = Obligation(
        source_clause_id=clause.id,
        requirement_text="The controller shall erase personal data without undue delay.",
        obligation_strength="mandatory",
        risk_severity="high",
        required_evidence_description="Erasure procedure and automated log confirmation."
    )
    db.add(ob)
    db.commit()

    resp_missing = client.post(f"/obligations/{ob.id}/assess")
    assert resp_missing.status_code == 200
    res_data = resp_missing.json()["assessment_result"]
    assert res_data["proposed_compliance_status"] in ["EVIDENCE_MISSING", "NON_COMPLIANT"]

    rec_count = db.query(ComplianceRecord).count()
    assert rec_count == 0
