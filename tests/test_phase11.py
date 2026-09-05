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

def test_isolated_evidence_expiry_only_affects_linked_obligation():
    from app.core.vector_store import vector_store
    from app.agents.evidence_agent import assess_obligation
    from app.core.state_manager import state_manager
    from app.core.evidence_monitor import check_evidence_expiry

    db = TestingSessionLocal()
    vector_store.clear()

    reg = Regulation(title="Security Policy 2", version_label="v1", source_file_path="p.pdf")
    db.add(reg)
    db.commit()

    clause = RegulationClause(regulation_id=reg.id, regulation_version="v1", clause_identifier="Clause Sec", clause_text="Sec text", source_page=1)
    db.add(clause)
    db.commit()

    # Obligation 1: Data erasure
    ob1 = Obligation(source_clause_id=clause.id, requirement_text="Obligation 1: Delete customer data", obligation_strength="mandatory", risk_severity="low", required_evidence_description="Erasure logs")
    # Obligation 2: Access control
    ob2 = Obligation(source_clause_id=clause.id, requirement_text="Obligation 2: Access control MFA", obligation_strength="mandatory", risk_severity="low", required_evidence_description="MFA logs")
    # Obligation 3: Encryption
    ob3 = Obligation(source_clause_id=clause.id, requirement_text="Obligation 3: Data encryption at rest", obligation_strength="mandatory", risk_severity="low", required_evidence_description="AES logs")
    db.add_all([ob1, ob2, ob3])
    db.commit()

    # Evidence A: Expiring yesterday, linked ONLY to Obligation 1
    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    ev_a = EvidenceDocument(org_name="Acme", title="Data Deletion SOP (Expiring)", source_file_path="del.pdf", expiry_date=yesterday)
    # Evidence B: Valid for 1 year, linked to Obligation 2 & 3
    next_year = datetime.now(timezone.utc) + timedelta(days=365)
    ev_b = EvidenceDocument(org_name="Acme", title="Security Architecture & MFA Spec", source_file_path="sec.pdf", expiry_date=next_year)
    db.add_all([ev_a, ev_b])
    db.commit()

    # Add chunks to vector store
    vector_store.add_chunks(evidence_document_id=ev_a.id, page_number=1, text="All customer data deletion requests are permanently purged within 30 days of receipt.", document_title=ev_a.title)
    vector_store.add_chunks(evidence_document_id=ev_b.id, page_number=1, text="All staff access control requires MFA and data encryption at rest with AES-256.", document_title=ev_b.title)

    # Real assessment flow for Obligation 1 -> links to Evidence A
    res1 = assess_obligation(ob1.id, db=db)
    state_manager.record_assessment(ob1.id, res1, db=db)

    # Real assessment flow for Obligation 2 & 3 -> links to Evidence B
    res2 = assess_obligation(ob2.id, db=db)
    state_manager.record_assessment(ob2.id, res2, db=db)

    res3 = assess_obligation(ob3.id, db=db)
    state_manager.record_assessment(ob3.id, res3, db=db)

    rec1 = db.query(ComplianceRecord).filter(ComplianceRecord.obligation_id == ob1.id).first()
    rec2 = db.query(ComplianceRecord).filter(ComplianceRecord.obligation_id == ob2.id).first()
    rec3 = db.query(ComplianceRecord).filter(ComplianceRecord.obligation_id == ob3.id).first()

    assert rec1.evidence_state == "VALID"
    assert rec2.evidence_state == "VALID"
    assert rec3.evidence_state == "VALID"

    # Now run evidence expiry check
    expiry_res = check_evidence_expiry(db=db)
    assert expiry_res["expired_records_flagged"] == 1

    db.refresh(rec1)
    db.refresh(rec2)
    db.refresh(rec3)

    # Obligation 1 MUST be flagged EXPIRED and RE_EVALUATION_REQUIRED
    assert rec1.evidence_state == "EXPIRED"
    assert rec1.workflow_state == "RE_EVALUATION_REQUIRED"

    # Obligations 2 and 3 MUST be completely untouched!
    assert rec2.evidence_state == "VALID"
    assert rec2.workflow_state == "ACTIVE"
    assert rec3.evidence_state == "VALID"
    assert rec3.workflow_state == "ACTIVE"
