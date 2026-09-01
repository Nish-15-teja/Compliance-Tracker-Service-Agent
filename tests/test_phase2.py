import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.db import RegulationClause, RegulationRawPage, Regulation
from tests.conftest import TestingSessionLocal

def test_phase2_clause_extraction_and_parenting():
    client = TestClient(app)

    db = TestingSessionLocal()
    reg = Regulation(title="EU Data Protection Act", version_label="v2.0", source_file_path="dummy.pdf")
    db.add(reg)
    db.commit()
    db.refresh(reg)

    raw_text_content = """
Article 5 Principles relating to processing of personal data.
Personal data shall be processed lawfully, fairly and in a transparent manner.

Article 6 Lawfulness of processing.
Processing shall be lawful only if at least one of the conditions applies.

Article 6(1) Specific conditions for consent.
The data subject has given consent to the processing of his or her personal data for one or more specific purposes.
"""

    raw_page = RegulationRawPage(regulation_id=reg.id, page_number=1, raw_text=raw_text_content)
    db.add(raw_page)
    db.commit()

    response = client.post(f"/regulations/{reg.id}/extract-clauses")
    assert response.status_code == 200
    data = response.json()
    assert data["clause_count"] >= 3

    clauses = db.query(RegulationClause).filter(RegulationClause.regulation_id == reg.id).all()
    identifiers = [c.clause_identifier for c in clauses]

    assert "Article 5" in identifiers
    assert "Article 6" in identifiers
    assert "Article 6(1)" in identifiers

    nested_clause = db.query(RegulationClause).filter(
        RegulationClause.regulation_id == reg.id,
        RegulationClause.clause_identifier == "Article 6(1)"
    ).first()

    assert nested_clause is not None
    assert nested_clause.parent_clause_identifier == "Article 6"
