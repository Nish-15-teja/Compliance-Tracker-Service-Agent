import os
import ast
import pytest
from datetime import datetime, timezone, timedelta
from app.db import Regulation, RegulationClause, Obligation, ComplianceRecord, ClauseChangeLog, StateTransition
from app.core.state_manager import state_manager
from tests.conftest import TestingSessionLocal

def test_correction5_state_manager_zero_llm_imports():
    """
    CORRECTION 5: Static check confirming no LLM/Claude clients are imported in state_manager.py.
    """
    state_manager_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../app/core/state_manager.py"))
    assert os.path.exists(state_manager_path), "state_manager.py not found!"

    with open(state_manager_path, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read())

    forbidden_imports = {"anthropic", "openai", "app.core.llm", "llm_service", "LLMService"}

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name not in forbidden_imports, f"Forbidden import found: import {alias.name}"
        elif isinstance(node, ast.ImportFrom):
            assert node.module not in forbidden_imports, f"Forbidden import found: from {node.module} import ..."
            for alias in node.names:
                assert alias.name not in forbidden_imports, f"Forbidden import found: from {node.module} import {alias.name}"

def test_correction7_exactly_4_agents():
    """
    CORRECTION 7: Confirm exactly 4 agent modules exist in app/agents/ directory.
    """
    agents_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../app/agents"))
    assert os.path.isdir(agents_dir), "app/agents/ directory not found!"

    files = [f for f in os.listdir(agents_dir) if f.endswith(".py") and not f.startswith("__")]
    assert len(files) == 4, f"Expected exactly 4 agent modules, found {len(files)}: {files}"
    
    expected_agents = {"extraction_agent.py", "evidence_agent.py", "change_impact_agent.py", "remediation_agent.py"}
    assert set(files) == expected_agents, f"Unexpected agents in folder: {files}"

def test_correction8_policy_gating_scenarios():
    """
    CORRECTION 8: Confirm policy-gating rules for human approval.
    """
    db = TestingSessionLocal()
    try:
        reg = Regulation(title="Gating Test", version_label="v1", source_file_path="gating.pdf")
        db.add(reg)
        db.commit()

        clause = RegulationClause(regulation_id=reg.id, regulation_version="v1", clause_identifier="C-Gating", clause_text="Gating text", source_page=1)
        db.add(clause)
        db.commit()

        # Case 1: High-confidence COMPLIANT, but CRITICAL-severity -> requires approval (severity overrides)
        ob_crit = Obligation(
            source_clause_id=clause.id,
            requirement_text="Critical requirements need encryption",
            obligation_strength="mandatory",
            risk_severity="critical",
            required_evidence_description="evidence logs"
        )
        db.add(ob_crit)
        db.commit()

        res_crit = state_manager.record_assessment(
            obligation_id=ob_crit.id,
            assessment_result={"proposed_compliance_status": "COMPLIANT", "confidence_score": 0.95, "reasoning": "Evidence is perfect"},
            db=db
        )
        assert res_crit["requires_human_approval"] is True, "Critical severity must require human approval even with high confidence compliant status"
        assert res_crit["approval_status"] == "pending"

        # Case 2: Low-confidence COMPLIANT, but LOW-severity -> requires approval (confidence overrides status/severity)
        ob_low = Obligation(
            source_clause_id=clause.id,
            requirement_text="Low risk reporting",
            obligation_strength="mandatory",
            risk_severity="low",
            required_evidence_description="evidence reports"
        )
        db.add(ob_low)
        db.commit()

        res_low = state_manager.record_assessment(
            obligation_id=ob_low.id,
            assessment_result={"proposed_compliance_status": "COMPLIANT", "confidence_score": 0.70, "reasoning": "Vague compliance proof"},
            db=db
        )
        assert res_low["requires_human_approval"] is True, "Low confidence must require human approval"
        assert res_low["approval_status"] == "pending"

        # Case 3: High-confidence COMPLIANT, and LOW-severity -> auto-applies
        res_auto = state_manager.record_assessment(
            obligation_id=ob_low.id,
            assessment_result={"proposed_compliance_status": "COMPLIANT", "confidence_score": 0.90, "reasoning": "Strong proof"},
            db=db
        )
        assert res_auto["requires_human_approval"] is False, "High confidence low severity compliant should auto-apply"
        assert res_auto["approval_status"] == "auto_applied"
    finally:
        db.close()

def test_correction4_and_9_field_independence_and_targeted_propagation():
    """
    CORRECTION 4 & 9: Confirm compliance_status, workflow_state, and evidence_state decoupling,
    and targeted impact propagation (only flagging compliance records tied to the modified clause).
    """
    db = TestingSessionLocal()
    try:
        reg_v1 = Regulation(title="Targeted Prop", version_label="v1", source_file_path="d1.pdf")
        reg_v2 = Regulation(title="Targeted Prop", version_label="v2", source_file_path="d2.pdf")
        db.add_all([reg_v1, reg_v2])
        db.commit()

        c_target_old = RegulationClause(regulation_id=reg_v1.id, regulation_version="v1", clause_identifier="Article A", clause_text="Old requirements", source_page=1)
        c_unrelated_old = RegulationClause(regulation_id=reg_v1.id, regulation_version="v1", clause_identifier="Article B", clause_text="Unrelated text", source_page=2)
        db.add_all([c_target_old, c_unrelated_old])
        db.commit()

        ob_target = Obligation(source_clause_id=c_target_old.id, requirement_text="Req A", obligation_strength="mandatory", risk_severity="high", required_evidence_description="ev")
        ob_unrelated = Obligation(source_clause_id=c_unrelated_old.id, requirement_text="Req B", obligation_strength="mandatory", risk_severity="low", required_evidence_description="ev")
        db.add_all([ob_target, ob_unrelated])
        db.commit()

        # Seed initial compliance records
        rec_target = ComplianceRecord(obligation_id=ob_target.id, compliance_status="COMPLIANT", workflow_state="ACTIVE", evidence_state="VALID", confidence_score=0.95)
        rec_unrelated = ComplianceRecord(obligation_id=ob_unrelated.id, compliance_status="COMPLIANT", workflow_state="ACTIVE", evidence_state="VALID", confidence_score=0.95)
        db.add_all([rec_target, rec_unrelated])
        db.commit()

        # Simulate change on target clause
        c_target_new = RegulationClause(regulation_id=reg_v2.id, regulation_version="v2", clause_identifier="Article A", clause_text="New tightened requirements", source_page=1)
        db.add(c_target_new)
        db.commit()

        change_log = ClauseChangeLog(
            old_clause_id=c_target_old.id,
            new_clause_id=c_target_new.id,
            regulation_id=reg_v2.id,
            change_type="MODIFIED",
            change_reason="Substantial update",
            change_significance="significant_change"
        )
        db.add(change_log)
        db.commit()

        # Run impact propagation
        from app.agents.change_impact_agent import propagate_impact
        prop_res = propagate_impact(new_regulation_id=reg_v2.id, db=db)
        
        db.refresh(rec_target)
        db.refresh(rec_unrelated)

        # Assert targeted propagation (Correction 9)
        assert rec_target.id in prop_res["flagged_compliance_records"]
        assert rec_unrelated.id not in prop_res["flagged_compliance_records"]

        # Assert field independence (Correction 4)
        assert rec_target.compliance_status == "COMPLIANT", "Compliance status should remain COMPLIANT until re-assessment runs"
        assert rec_target.workflow_state == "RE_EVALUATION_REQUIRED", "Workflow state should transition to RE_EVALUATION_REQUIRED"
        assert rec_target.evidence_state == "VALID", "Evidence state should remain VALID"

        # Assert unrelated record is completely untouched
        assert rec_unrelated.compliance_status == "COMPLIANT"
        assert rec_unrelated.workflow_state == "ACTIVE"
        assert rec_unrelated.evidence_state == "VALID"
    finally:
        db.close()
