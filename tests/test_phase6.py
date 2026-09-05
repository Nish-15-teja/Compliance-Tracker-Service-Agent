import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.db import Regulation, RegulationClause, Obligation, StateTransition
from app.core.state_manager import state_manager
from tests.conftest import TestingSessionLocal

def test_phase6_state_manager_policy_and_history():
    db = TestingSessionLocal()

    reg = Regulation(title="Policy Policy", version_label="v1", source_file_path="dummy.pdf")
    db.add(reg)
    db.commit()

    clause = RegulationClause(regulation_id=reg.id, regulation_version="v1", clause_identifier="Sec 1", clause_text="Text", source_page=1)
    db.add(clause)
    db.commit()

    ob_low = Obligation(source_clause_id=clause.id, requirement_text="Low risk req", obligation_strength="mandatory", risk_severity="low", required_evidence_description="ev")
    db.add(ob_low)
    db.commit()

    res_auto = state_manager.record_assessment(
        obligation_id=ob_low.id,
        assessment_result={"proposed_compliance_status": "COMPLIANT", "confidence_score": 0.95, "reasoning": "Good evidence"},
        db=db
    )
    assert res_auto["requires_human_approval"] is False
    assert res_auto["approval_status"] == "auto_applied"
    assert res_auto["applied_status"] == "COMPLIANT"

    ob_crit = Obligation(source_clause_id=clause.id, requirement_text="Crit risk req", obligation_strength="mandatory", risk_severity="critical", required_evidence_description="ev")
    db.add(ob_crit)
    db.commit()

    res_crit = state_manager.record_assessment(
        obligation_id=ob_crit.id,
        assessment_result={"proposed_compliance_status": "COMPLIANT", "confidence_score": 0.95, "reasoning": "Good evidence"},
        db=db
    )
    assert res_crit["requires_human_approval"] is True
    assert res_crit["approval_status"] == "pending"
    assert res_crit["workflow_state"] == "PENDING_HUMAN_REVIEW"

    ob_noncomp = Obligation(source_clause_id=clause.id, requirement_text="Noncomp req", obligation_strength="mandatory", risk_severity="medium", required_evidence_description="ev")
    db.add(ob_noncomp)
    db.commit()

    res_noncomp = state_manager.record_assessment(
        obligation_id=ob_noncomp.id,
        assessment_result={"proposed_compliance_status": "NON_COMPLIANT", "confidence_score": 0.90, "reasoning": "No evidence"},
        db=db
    )
    assert res_noncomp["requires_human_approval"] is True
    assert res_noncomp["approval_status"] == "pending"

    trans_noncomp = db.query(StateTransition).filter(StateTransition.id == res_noncomp["transition_id"]).first()
    assert trans_noncomp is not None

    client = TestClient(app)
    app_resp = client.post(f"/review/{res_crit['transition_id']}/approve", json={"approved_by": "Senior Auditor"})
    assert app_resp.status_code == 200
    assert app_resp.json()["status"] == "approved"

    history = state_manager.get_history(obligation_id=ob_crit.id, db=db)
    assert len(history) == 1
    assert history[0].approval_status == "approved"

def test_phase6_evidence_link_populated_in_real_assessment_flow():
    from app.core.vector_store import vector_store
    from app.db import EvidenceDocument, EvidenceLink, ComplianceRecord
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
        requirement_text="The controller shall erase customer data within 30 days.",
        obligation_strength="mandatory",
        risk_severity="low",
        required_evidence_description="Customer data erasure policy and audit logs."
    )
    db.add(ob)
    db.commit()

    ev_doc = EvidenceDocument(
        org_name="Acme",
        title="Customer Data Erasure Standard Operating Procedure",
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

    assessment = assess_obligation(ob.id, db=db)
    assert "evidence_used" in assessment
    assert len(assessment["evidence_used"]) > 0

    record_res = state_manager.record_assessment(obligation_id=ob.id, assessment_result=assessment, db=db)
    rec_id = record_res["compliance_record_id"]

    # Verify that an actual EvidenceLink row was persisted in the database
    links = db.query(EvidenceLink).filter(EvidenceLink.compliance_record_id == rec_id).all()
    assert len(links) >= 1
    assert links[0].evidence_document_id == ev_doc.id
    assert links[0].compliance_record_id == rec_id

    # Verify transition also recorded evidence_ids
    trans = db.query(StateTransition).filter(StateTransition.compliance_record_id == rec_id).first()
    assert trans.evidence_ids is not None
    assert ev_doc.id in trans.evidence_ids
