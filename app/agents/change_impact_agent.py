import difflib
from typing import Dict, Any, List
from sqlalchemy.orm import Session
from app.db import RegulationClause, ClauseChangeLog
from app.core.llm import llm_service
from app.core.vector_store import SimpleVectorStore

def detect_changes(old_regulation_id: int, new_regulation_id: int, db: Session) -> Dict[str, Any]:
    """
    Phase 7 function: 4-Step Regulation Change Detection Pipeline (Novelty #2).
    Step 1: Clause ID match
    Step 2: Exact text diff
    Step 3: Semantic fallback match
    Step 4: LLM verification for modified clauses
    """
    old_clauses = db.query(RegulationClause).filter(RegulationClause.regulation_id == old_regulation_id).all()
    new_clauses = db.query(RegulationClause).filter(RegulationClause.regulation_id == new_regulation_id).all()

    old_map = {c.clause_identifier: c for c in old_clauses}
    new_map = {c.clause_identifier: c for c in new_clauses}

    change_logs: List[ClauseChangeLog] = []

    matched_old_ids = set()
    matched_new_ids = set()

    # STEP 1 & STEP 2: Identifier match and text diff
    for clause_id, old_c in old_map.items():
        if clause_id in new_map:
            new_c = new_map[clause_id]
            matched_old_ids.add(old_c.id)
            matched_new_ids.add(new_c.id)

            if old_c.clause_text.strip() == new_c.clause_text.strip():
                # Step 2: Exact match -> UNCHANGED
                log = ClauseChangeLog(
                    old_clause_id=old_c.id,
                    new_clause_id=new_c.id,
                    regulation_id=new_regulation_id,
                    change_type="UNCHANGED",
                    change_reason="Exact text match across regulation versions.",
                    change_significance="minor_wording"
                )
                change_logs.append(log)
            else:
                # Step 4: Text diff found -> run LLM verification
                llm_res = _verify_clause_change_llm(old_c.clause_text, new_c.clause_text)
                log = ClauseChangeLog(
                    old_clause_id=old_c.id,
                    new_clause_id=new_c.id,
                    regulation_id=new_regulation_id,
                    change_type="MODIFIED",
                    change_reason=llm_res.get("change_reason", "Textual modification detected."),
                    change_significance=llm_res.get("change_significance", "significant_change")
                )
                change_logs.append(log)

    # STEP 3: Semantic fallback for unmatched clauses
    unmatched_old = [c for c in old_clauses if c.id not in matched_old_ids]
    unmatched_new = [c for c in new_clauses if c.id not in matched_new_ids]

    for new_c in unmatched_new:
        best_match_old = None
        best_score = 0.0

        for old_c in unmatched_old:
            if old_c.id in matched_old_ids:
                continue
            # Cosine overlap check
            v_store = SimpleVectorStore()
            v_store.add_chunks(1, 1, old_c.clause_text)
            res = v_store.search(new_c.clause_text, top_k=1)
            score = res[0]["similarity_score"] if res else 0.0
            if score > best_score and score >= 0.75:
                best_score = score
                best_match_old = old_c

        if best_match_old:
            matched_old_ids.add(best_match_old.id)
            matched_new_ids.add(new_c.id)
            llm_res = _verify_clause_change_llm(best_match_old.clause_text, new_c.clause_text)
            log = ClauseChangeLog(
                old_clause_id=best_match_old.id,
                new_clause_id=new_c.id,
                regulation_id=new_regulation_id,
                change_type="MODIFIED",
                change_reason=llm_res.get("change_reason", "Semantic fallback match detected clause modification."),
                change_significance=llm_res.get("change_significance", "significant_change")
            )
            change_logs.append(log)
        else:
            # ADDED clause
            matched_new_ids.add(new_c.id)
            log = ClauseChangeLog(
                old_clause_id=None,
                new_clause_id=new_c.id,
                regulation_id=new_regulation_id,
                change_type="ADDED",
                change_reason="Newly introduced clause in regulation version.",
                change_significance="significant_change"
            )
            change_logs.append(log)

    for old_c in unmatched_old:
        if old_c.id not in matched_old_ids:
            log = ClauseChangeLog(
                old_clause_id=old_c.id,
                new_clause_id=None,
                regulation_id=new_regulation_id,
                change_type="REMOVED",
                change_reason="Clause removed in new regulation version.",
                change_significance="significant_change"
            )
            change_logs.append(log)

    # Persist log records to database
    db.add_all(change_logs)
    db.commit()

    return {
        "old_regulation_id": old_regulation_id,
        "new_regulation_id": new_regulation_id,
        "total_changes": len(change_logs),
        "unchanged": sum(1 for c in change_logs if c.change_type == "UNCHANGED"),
        "modified": sum(1 for c in change_logs if c.change_type == "MODIFIED"),
        "added": sum(1 for c in change_logs if c.change_type == "ADDED"),
        "removed": sum(1 for c in change_logs if c.change_type == "REMOVED"),
        "significant_changes": sum(1 for c in change_logs if c.change_significance == "significant_change")
    }

def _verify_clause_change_llm(old_text: str, new_text: str) -> Dict[str, Any]:
    """
    Step 4: LLM Verification to determine if text change is minor_wording or significant_change.
    """
    prompt = f"""You are a regulatory legal expert analyzing changes between two versions of a clause.

Old Clause Text:
{old_text}

New Clause Text:
{new_text}

CRITICAL VERIFICATION RULE:
Old: 'Delete customer data within 30 days.' New: 'Delete customer data within 3 days.' These are textually similar but represent a MAJOR compliance change — focus on whether the obligated party's actual duty changed (deadlines, thresholds, scope, exceptions, penalties), not sentence similarity.
Minor typos, formatting, or synonym swaps are "minor_wording".

Output strict JSON:
{{
  "meaning_changed": true/false,
  "change_reason": "...",
  "change_significance": "minor_wording" | "significant_change"
}}
"""
    return llm_service.call_llm_json(prompt, fallback_type="change_verification")

def propagate_impact(new_regulation_id: int, db: Session) -> Dict[str, Any]:
    """
    Phase 8 function: TARGETED impact propagation.
    Flags only obligations/compliance_records tied to modified/removed clauses with significant_change.
    """
    from app.db import Obligation, ComplianceRecord
    from app.core.state_manager import state_manager
    from app.agents.extraction_agent import extract_obligations

    change_logs = db.query(ClauseChangeLog).filter(
        ClauseChangeLog.regulation_id == new_regulation_id,
        ClauseChangeLog.change_significance == "significant_change"
    ).all()

    flagged_records = []
    added_obligations = []

    for log in change_logs:
        if log.change_type in ["MODIFIED", "REMOVED"] and log.old_clause_id:
            # Find obligations linked to old_clause_id
            obligations = db.query(Obligation).filter(Obligation.source_clause_id == log.old_clause_id).all()
            for ob in obligations:
                rec = db.query(ComplianceRecord).filter(ComplianceRecord.obligation_id == ob.id).first()
                if rec:
                    state_manager.trigger_reevaluation(
                        compliance_record_id=rec.id,
                        reason=log.change_reason or "Regulation clause updated with significant compliance impact.",
                        db=db
                    )
                    flagged_records.append(rec.id)

        elif log.change_type == "ADDED" and log.new_clause_id:
            new_obs = extract_obligations(clause_id=log.new_clause_id, db=db)
            for ob in new_obs:
                added_obligations.append(ob.id)

    return {
        "new_regulation_id": new_regulation_id,
        "flagged_compliance_records": list(set(flagged_records)),
        "flagged_count": len(set(flagged_records)),
        "new_obligations_created": added_obligations
    }

def run_targeted_reassessment(compliance_record_ids: List[int], db: Session) -> Dict[str, Any]:
    """
    Phase 8 function: runs evidence re-assessment on specified flagged compliance record IDs.
    """
    from app.db import ComplianceRecord
    from app.agents.evidence_agent import assess_obligation
    from app.core.state_manager import state_manager

    reassessed_results = []
    for rec_id in compliance_record_ids:
        rec = db.query(ComplianceRecord).filter(ComplianceRecord.id == rec_id).first()
        if rec:
            assessment = assess_obligation(obligation_id=rec.obligation_id, db=db)
            res = state_manager.record_assessment(
                obligation_id=rec.obligation_id,
                assessment_result=assessment,
                db=db
            )
            reassessed_results.append(res)

    return {
        "reassessed_count": len(reassessed_results),
        "results": reassessed_results
    }

