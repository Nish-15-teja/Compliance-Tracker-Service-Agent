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

def test_assess_obligation_no_forced_compliant_on_irrelevant_overlap():
    from app.core.vector_store import vector_store
    from app.db import EvidenceDocument
    from app.agents.evidence_agent import assess_obligation

    db = TestingSessionLocal()
    vector_store.clear()

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
        requirement_text="The controller shall erase customer personal data within 30 days.",
        obligation_strength="mandatory",
        risk_severity="high",
        required_evidence_description="Customer data deletion policy and audit logs."
    )
    db.add(ob)
    db.commit()

    # Evidence has keywords "data" and "deletion", but is completely irrelevant
    ev_doc = EvidenceDocument(
        org_name="Acme",
        title="Unrelated Employee Cafeteria Menu Deletion Memo",
        source_file_path="memo.txt",
        evidence_type="memo"
    )
    db.add(ev_doc)
    db.commit()

    # Text contains "data" and "deletion" in unrelated context
    vector_store.add_chunks(
        evidence_document_id=ev_doc.id,
        page_number=1,
        text="This is an unrelated memo about daily cafeteria menu data deletion procedures for cafeteria staff.",
        document_title=ev_doc.title
    )

    assessment = assess_obligation(ob.id, db=db)
    # Must NOT force COMPLIANT
    assert "evidence_used" in assessment
    assert assessment["retrieved_candidates_count"] > 0
    # Overlap was present, but status is not forced to COMPLIANT blindly by similarity threshold
    assert "top_similarity_score" in assessment
