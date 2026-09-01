import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.db import Regulation, RegulationClause, ClauseChangeLog
from tests.conftest import TestingSessionLocal

def test_phase7_four_step_change_detection():
    client = TestClient(app)
    db = TestingSessionLocal()

    reg_v1 = Regulation(title="EU GDPR Regulation", version_label="v1.0", source_file_path="dummy1.pdf")
    reg_v2 = Regulation(title="EU GDPR Regulation", version_label="v2.0", source_file_path="dummy2.pdf")
    db.add_all([reg_v1, reg_v2])
    db.commit()

    c1_v1 = RegulationClause(regulation_id=reg_v1.id, regulation_version="v1.0", clause_identifier="Article 1", clause_text="Cosmetic formatting notice for internal distribution.", source_page=1)
    c2_v1 = RegulationClause(regulation_id=reg_v1.id, regulation_version="v1.0", clause_identifier="Article 17", clause_text="Delete customer data within 30 days of request.", source_page=2)
    c3_v1 = RegulationClause(regulation_id=reg_v1.id, regulation_version="v1.0", clause_identifier="Article 99", clause_text="Old clause to be removed in v2.", source_page=3)
    db.add_all([c1_v1, c2_v1, c3_v1])

    c1_v2 = RegulationClause(regulation_id=reg_v2.id, regulation_version="v2.0", clause_identifier="Article 1", clause_text="Cosmetic formatting notice for internal distribution (minor notification).", source_page=1)
    c2_v2 = RegulationClause(regulation_id=reg_v2.id, regulation_version="v2.0", clause_identifier="Article 17", clause_text="Delete customer data within 3 days of request.", source_page=2)
    c4_v2 = RegulationClause(regulation_id=reg_v2.id, regulation_version="v2.0", clause_identifier="Article 100", clause_text="Newly added clause in v2 for AI governance.", source_page=4)
    db.add_all([c1_v2, c2_v2, c4_v2])
    db.commit()

    response = client.post(f"/regulations/{reg_v2.id}/detect-changes?compare_to={reg_v1.id}")
    assert response.status_code == 200
    report = response.json()

    assert report["modified"] == 2
    assert report["added"] == 1
    assert report["removed"] == 1

    logs = db.query(ClauseChangeLog).filter(ClauseChangeLog.regulation_id == reg_v2.id).all()
    art17_log = [l for l in logs if l.old_clause_id == c2_v1.id][0]
    assert art17_log.change_type == "MODIFIED"
    assert art17_log.change_significance == "significant_change"

    art1_log = [l for l in logs if l.old_clause_id == c1_v1.id][0]
    assert art1_log.change_type == "MODIFIED"
    assert art1_log.change_significance == "minor_wording"
