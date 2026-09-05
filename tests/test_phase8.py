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

def test_reassessment_uses_new_obligation_text_not_old():
    from app.agents.change_impact_agent import detect_changes, propagate_impact, run_targeted_reassessment
    from app.agents.extraction_agent import extract_clauses, extract_all_obligations_for_regulation
    from app.agents.evidence_agent import assess_obligation
    from app.core.state_manager import state_manager
    from app.core.vector_store import vector_store
    from app.db import EvidenceDocument, RegulationRawPage

    db = TestingSessionLocal()
    vector_store.clear()

    # 1. Regulation v1 with 30-day requirement
    reg_v1 = Regulation(title="Data Deletion Policy", version_label="v1", source_file_path="v1.pdf")
    db.add(reg_v1)
    db.commit()

    raw_p1 = RegulationRawPage(
        regulation_id=reg_v1.id,
        page_number=1,
        raw_text="Article 5 General Principles.\nPersonal data shall be processed lawfully and fairly.\n\nArticle 17 Right to erasure.\nOrganizations must delete customer data within 30 days of receiving a verified request."
    )
    db.add(raw_p1)
    db.commit()

    extract_clauses(reg_v1.id, db=db)
    extract_all_obligations_for_regulation(reg_v1.id, db=db)

    old_clause = db.query(RegulationClause).filter(RegulationClause.regulation_id == reg_v1.id, RegulationClause.clause_identifier == "Article 17").first()
    old_ob = db.query(Obligation).filter(Obligation.source_clause_id == old_clause.id).first()

    # 2. Add evidence satisfying 30 days
    ev_doc = EvidenceDocument(
        org_name="Acme",
        title="30 Day Data Erasure Procedure",
        source_file_path="sop.txt",
        evidence_type="policy"
    )
    db.add(ev_doc)
    db.commit()

    vector_store.add_chunks(
        evidence_document_id=ev_doc.id,
        page_number=1,
        text="All customer data deletion requests are permanently purged within 30 days of receipt.",
        document_title=ev_doc.title
    )

    # Initial assessment -> COMPLIANT
    initial_assessment = assess_obligation(old_ob.id, db=db)
    state_manager.record_assessment(old_ob.id, initial_assessment, db=db)

    rec = db.query(ComplianceRecord).filter(ComplianceRecord.obligation_id == old_ob.id).first()
    assert rec is not None
    assert rec.compliance_status == "COMPLIANT"

    # 3. Regulation v2 with tightened 3-day requirement
    reg_v2 = Regulation(title="Data Deletion Policy", version_label="v2", source_file_path="v2.pdf")
    db.add(reg_v2)
    db.commit()

    raw_p2 = RegulationRawPage(
        regulation_id=reg_v2.id,
        page_number=1,
        raw_text="Article 5 General Principles.\nPersonal data shall be processed lawfully and fairly.\n\nArticle 17 Right to erasure.\nOrganizations must delete customer data within 3 days of receiving a verified request."
    )
    db.add(raw_p2)
    db.commit()

    extract_clauses(reg_v2.id, db=db)

    # 4. Detect changes and propagate impact
    change_rep = detect_changes(old_regulation_id=reg_v1.id, new_regulation_id=reg_v2.id, db=db)
    assert change_rep["significant_changes"] >= 1

    prop_res = propagate_impact(new_regulation_id=reg_v2.id, db=db)
    assert rec.id in prop_res["flagged_compliance_records"]

    # 5. Run targeted reassessment
    reassess_res = run_targeted_reassessment(compliance_record_ids=[rec.id], db=db)
    assert reassess_res["reassessed_count"] == 1

    # 6. Verify that the compliance record now points to the NEW obligation text ("3 days", NOT "30 days")
    db.refresh(rec)
    current_ob = db.query(Obligation).filter(Obligation.id == rec.obligation_id).first()

    assert current_ob.id != old_ob.id
    assert "3 days" in current_ob.requirement_text or "3 days" in current_ob.source_clause.clause_text
    assert "30 days" not in current_ob.source_clause.clause_text

    # 7. Verify that the reassessment StateTransition has trigger_type == 'regulation_change' (Fix 6)
    transitions = state_manager.get_history(obligation_id=current_ob.id, db=db)
    reassess_trans = [t for t in transitions if t.trigger_type == "regulation_change"]
    assert len(reassess_trans) >= 1
