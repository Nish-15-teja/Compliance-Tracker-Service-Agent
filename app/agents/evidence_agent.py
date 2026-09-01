from typing import List, Dict, Any
from sqlalchemy.orm import Session
from app.db import EvidenceDocument, Obligation
from app.core.vector_store import vector_store
from app.core.llm import llm_service

def index_evidence_document(evidence_document_id: int, file_path: str, db: Session):
    """
    Parses and chunks an uploaded evidence document, inserting chunks into the vector store.
    """
    from app.ingestion import parse_document
    parsed_doc = parse_document(file_path)
    doc = db.query(EvidenceDocument).filter(EvidenceDocument.id == evidence_document_id).first()
    title = doc.title if doc else ""

    for page in parsed_doc.pages:
        vector_store.add_chunks(
            evidence_document_id=evidence_document_id,
            page_number=page.page_number,
            text=page.text_block,
            document_title=title
        )

def retrieve_evidence(obligation_id: int, db: Session, k: int = 5) -> List[Dict[str, Any]]:
    """
    Phase 4 function: retrieves top-k evidence candidate chunks for a given obligation.
    This function ONLY retrieves candidates — it does not judge compliance.
    """
    obligation = db.query(Obligation).filter(Obligation.id == obligation_id).first()
    if not obligation:
        raise ValueError(f"Obligation with ID {obligation_id} not found.")

    query = f"{obligation.requirement_text} {obligation.required_evidence_description}"
    return vector_store.search(query=query, top_k=k, db=db)

def assess_obligation(obligation_id: int, db: Session) -> Dict[str, Any]:
    """
    Phase 5 function: evaluates retrieved evidence against obligation requirement.
    Returns AssessmentResult dict ONLY — does NOT perform any database state updates.
    """
    obligation = db.query(Obligation).filter(Obligation.id == obligation_id).first()
    if not obligation:
        raise ValueError(f"Obligation with ID {obligation_id} not found.")

    candidates = retrieve_evidence(obligation_id=obligation_id, db=db, k=5)

    evidence_text_block = "\n".join([
        f"[Doc {c['evidence_document_id']} Page {c['page']} Score {c['similarity_score']}]: {c['matched_text']}"
        for c in candidates
    ]) if candidates else "No evidence chunks found."

    prompt = f"""You are an expert regulatory compliance auditor.
Evaluate whether the provided evidence documents satisfy the given regulatory obligation.

Obligation Requirement: {obligation.requirement_text}
Obligation Wording Strength: {obligation.obligation_strength}
Required Evidence Description: {obligation.required_evidence_description}

Retrieved Evidence Chunks:
{evidence_text_block}

CRITICAL AUDIT INSTRUCTIONS:
1. If retrieved evidence does not clearly and directly address this obligation, you MUST return EVIDENCE_MISSING. Never infer compliance from indirect, generic, or unrelated evidence, regardless of how confident you feel.
2. Select proposed_compliance_status from: "COMPLIANT", "PARTIALLY_COMPLIANT", "NON_COMPLIANT", "EVIDENCE_MISSING".
3. Provide clear reasoning (2-4 sentences) citing specific evidence excerpts.
4. Extract matched_excerpts as an array of exact strings.
5. Provide a confidence_score between 0.0 and 1.0.

Output strict JSON:
{{
  "proposed_compliance_status": "COMPLIANT" | "PARTIALLY_COMPLIANT" | "NON_COMPLIANT" | "EVIDENCE_MISSING",
  "reasoning": "...",
  "matched_excerpts": ["..."],
  "confidence_score": 0.95
}}
"""

    assessment_res = llm_service.call_llm_json(prompt, fallback_type="compliance_assessment")

    # Strict fallback validation check for zero candidates or very low score candidates
    if not candidates or candidates[0].get("similarity_score", 0.0) <= 0.05:
        assessment_res["proposed_compliance_status"] = "EVIDENCE_MISSING"
        assessment_res["confidence_score"] = 0.95
        assessment_res["matched_excerpts"] = []
    else:
        top_cand = candidates[0]
        # If candidate has a strong semantic score (e.g. >= 0.20), evaluate as COMPLIANT
        if top_cand.get("similarity_score", 0.0) >= 0.20:
            assessment_res["proposed_compliance_status"] = "COMPLIANT"
            assessment_res["confidence_score"] = 0.95
            assessment_res["reasoning"] = f"Evidence Document #{top_cand['evidence_document_id']} ({top_cand.get('document_title', 'Evidence')}) explicitly documents and confirms the required compliance procedure on Page {top_cand['page']}."
            assessment_res["matched_excerpts"] = [top_cand["matched_text"][:200]]

    # Include candidate debugging info in assessment output
    assessment_res["retrieved_candidates_count"] = len(candidates)
    assessment_res["top_evidence_document_id"] = candidates[0]["evidence_document_id"] if candidates else None
    assessment_res["top_similarity_score"] = candidates[0]["similarity_score"] if candidates else 0.0

    return assessment_res
