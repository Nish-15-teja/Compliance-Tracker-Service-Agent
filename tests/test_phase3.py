import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.db import Regulation, RegulationClause, Obligation
from tests.conftest import TestingSessionLocal

def test_phase3_obligation_extraction_strength_vs_severity():
    client = TestClient(app)

    db = TestingSessionLocal()
    reg = Regulation(title="Data Standards", version_label="v1.0", source_file_path="dummy.pdf")
    db.add(reg)
    db.commit()

    c1 = RegulationClause(
        regulation_id=reg.id,
        regulation_version="v1.0",
        clause_identifier="Clause 1.1",
        clause_text="Organizations must include a minor notification header on internal memos (low impact cosmetic).",
        source_page=1
    )

    c2 = RegulationClause(
        regulation_id=reg.id,
        regulation_version="v1.0",
        clause_identifier="Clause 2.1",
        clause_text="Organizations may optionally publish environmental sustainability summaries.",
        source_page=1
    )

    c3 = RegulationClause(
        regulation_id=reg.id,
        regulation_version="v1.0",
        clause_identifier="Clause 3.1",
        clause_text="Where relevant and if applicable, organizations handling health data must encrypt archives.",
        source_page=2
    )

    db.add_all([c1, c2, c3])
    db.commit()

    response = client.post(f"/regulations/{reg.id}/extract-obligations")
    assert response.status_code == 200
    data = response.json()
    assert data["obligations_created"] >= 3

    ob1 = db.query(Obligation).filter(Obligation.source_clause_id == c1.id).first()
    assert ob1 is not None
    assert ob1.source_clause_id == c1.id
    assert ob1.obligation_strength == "mandatory"
    assert ob1.risk_severity != "critical"

    ob2 = db.query(Obligation).filter(Obligation.source_clause_id == c2.id).first()
    assert ob2 is not None
    assert ob2.obligation_strength == "advisory"

    ob3 = db.query(Obligation).filter(Obligation.source_clause_id == c3.id).first()
    assert ob3 is not None
    assert ob3.obligation_strength == "conditional"
