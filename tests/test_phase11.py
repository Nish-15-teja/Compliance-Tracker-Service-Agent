import pytest
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
from app.main import app
from app.db import Regulation, RegulationClause, Obligation, ComplianceRecord, EvidenceDocument, EvidenceLink
from tests.conftest import TestingSessionLocal

def test_phase11_evidence_freshness_expiry():
    client = TestClient(app)
    db = TestingSessionLocal()

    reg = Regulation(title="Security Policy", version_label="v1", source_file_path="p.pdf")
    db.add(reg)
    db.commit()

    clause = RegulationClause(regulation_id=reg.id, regulation_version="v1", clause_identifier="Clause 1", clause_text="Cert requirement", source_page=1)
    db.add(clause)
    db.commit()

    ob = Obligation(source_clause_id=clause.id, requirement_text="SOC2 certificate required", obligation_strength="mandatory", risk_severity="high", required_evidence_description="ev")
    db.add(ob)
    db.commit()

    rec = ComplianceRecord(obligation_id=ob.id, compliance_status="COMPLIANT", workflow_state="ACTIVE", evidence_state="VALID")
    db.add(rec)
    db.commit()

    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    ev_doc = EvidenceDocument(org_name="Acme", title="Expired SOC2 Cert", source_file_path="cert.pdf", expiry_date=yesterday)
    db.add(ev_doc)
    db.commit()

    link = EvidenceLink(compliance_record_id=rec.id, evidence_document_id=ev_doc.id, matched_excerpt="SOC2 report valid until yesterday", confidence_score=0.95)
    db.add(link)
    db.commit()

    response = client.post("/evidence/check-expiry?warning_days=30")
    assert response.status_code == 200
    data = response.json()
    assert data["expired_records_flagged"] >= 1

    db.refresh(rec)
    assert rec.compliance_status == "COMPLIANT" # Preserved!
    assert rec.evidence_state == "EXPIRED"
    assert rec.workflow_state == "RE_EVALUATION_REQUIRED"
