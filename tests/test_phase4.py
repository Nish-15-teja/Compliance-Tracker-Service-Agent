import os
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.db import Regulation, RegulationClause, Obligation
from tests.conftest import TestingSessionLocal

def test_phase4_evidence_retrieval():
    client = TestClient(app)
    db = TestingSessionLocal()

    reg = Regulation(title="Data Retention Policy Standard", version_label="v1", source_file_path="dummy.pdf")
    db.add(reg)
    db.commit()

    clause = RegulationClause(
        regulation_id=reg.id,
        regulation_version="v1",
        clause_identifier="Clause 4.1",
        clause_text="Data deletion procedure requirement.",
        source_page=1
    )
    db.add(clause)
    db.commit()

    obligation = Obligation(
        source_clause_id=clause.id,
        requirement_text="The organization must delete customer personal data within 30 days of request.",
        obligation_strength="mandatory",
        risk_severity="high",
        required_evidence_description="Customer data deletion policy document and automated execution logs."
    )
    db.add(obligation)
    db.commit()

    evidence_file_path = "sample_policy.txt"
    with open(evidence_file_path, "w", encoding="utf-8") as f:
        f.write("Section 1: General Company Overview\nAcme Corp provides cloud platform solutions.\n---PAGE---\nSection 2: Data Retention & Deletion Policy\nAll customer personal data deletion requests are processed within 30 days of submission into audit logs.")

    with open(evidence_file_path, "rb") as f:
        upload_resp = client.post(
            "/evidence/upload",
            data={"org_name": "Acme Corp", "title": "Data Deletion Standard Operating Procedure", "evidence_type": "policy"},
            files={"file": ("sample_policy.txt", f, "text/plain")}
        )

    if os.path.exists(evidence_file_path):
        os.remove(evidence_file_path)

    assert upload_resp.status_code == 201
    ev_data = upload_resp.json()
    assert ev_data["evidence_document_id"] is not None

    ret_resp = client.get(f"/obligations/{obligation.id}/evidence-candidates?k=5")
    assert ret_resp.status_code == 200
    cand_data = ret_resp.json()
    assert cand_data["candidate_count"] > 0

    top_candidate = cand_data["candidates"][0]
    assert "data" in top_candidate["matched_text"].lower() or "deletion" in top_candidate["matched_text"].lower()
    assert top_candidate["similarity_score"] > 0.0
