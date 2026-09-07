import re
from typing import List, Dict, Any, Tuple
from sqlalchemy.orm import Session
from app.db import Regulation, RegulationRawPage, RegulationClause
from app.core.llm import llm_service

REGEX_CLAUSE_PATTERNS = [
    r'(Article\s+\d+(?:\(\d+\))?)',
    r'(Section\s+\d+(?:\.\d+)*(?:\(\d+\))?)',
    r'(Clause\s+\d+(?:\.\d+)*(?:\(\d+\))?)',
    r'(Rule\s+\d+(?:\(\d+\))?)'
]

def _infer_parent_clause(identifier: str) -> str | None:
    """
    Infers parent clause identifier.
    Example: 'Article 6(1)' -> 'Article 6', 'Section 5.2.1' -> 'Section 5.2'
    """
    # Matches nested parenthesis: Article 6(1) -> Article 6
    match_paren = re.match(r'^(.*?)\s*\(\d+\)$', identifier, re.IGNORECASE)
    if match_paren:
        return match_paren.group(1).strip()
    
    # Matches dotted sub-sections: Section 5.2.1 -> Section 5.2
    match_dot = re.match(r'^(.*)\.\d+$', identifier, re.IGNORECASE)
    if match_dot:
        return match_dot.group(1).strip()
        
    return None

def extract_clauses(regulation_id: int, db: Session) -> Dict[str, Any]:
    """
    Extracts clause-level records from staged raw pages of a regulation.
    Tries regex boundary detection first; falls back to LLM if < 2 boundaries detected.
    """
    regulation = db.query(Regulation).filter(Regulation.id == regulation_id).first()
    if not regulation:
        raise ValueError(f"Regulation with ID {regulation_id} not found.")

    raw_pages = db.query(RegulationRawPage).filter(RegulationRawPage.regulation_id == regulation_id).order_by(RegulationRawPage.page_number).all()
    if not raw_pages:
        raise ValueError(f"No raw pages found for regulation ID {regulation_id}.")

    detected_clauses: List[Dict[str, Any]] = []
    used_llm_fallback = False

    # Combined regex pattern for boundary detection
    combined_pattern = re.compile(r'|'.join(REGEX_CLAUSE_PATTERNS), re.IGNORECASE)

    for page in raw_pages:
        text = page.raw_text
        matches = list(combined_pattern.finditer(text))

        if len(matches) >= 1:
            for idx, match in enumerate(matches):
                clause_id_str = match.group(0).strip()
                start_pos = match.start()
                end_pos = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
                clause_text_span = text[start_pos:end_pos].strip()

                parent_id = _infer_parent_clause(clause_id_str)
                detected_clauses.append({
                    "clause_identifier": clause_id_str,
                    "clause_text": clause_text_span,
                    "source_page": page.page_number,
                    "parent_clause_identifier": parent_id
                })

    # If regex found fewer than 2 boundaries across entire document, trigger LLM fallback
    if len(detected_clauses) < 2:
        used_llm_fallback = True
        detected_clauses.clear()

        full_doc_text = "\n\n".join([f"[Page {p.page_number}]\n{p.raw_text}" for p in raw_pages])
        prompt = f"""Extract all regulation clause boundaries from the following regulation text.
For each clause identified, output JSON format with:
- clause_identifier (e.g., "Article 1", "Section 5.2", "Article 6(1)")
- clause_text (full text of the clause)
- parent_clause_identifier (e.g., "Article 6" if clause is "Article 6(1)", otherwise null)

Regulation Text:
{full_doc_text}
"""
        llm_response = llm_service.call_llm_json(prompt, fallback_type="clause_extraction")
        clauses_json = llm_response.get("clauses", [])

        for item in clauses_json:
            clause_id_str = item.get("clause_identifier", "Clause")
            parent_id = item.get("parent_clause_identifier") or _infer_parent_clause(clause_id_str)
            detected_clauses.append({
                "clause_identifier": clause_id_str,
                "clause_text": item.get("clause_text", ""),
                "source_page": 1,
                "parent_clause_identifier": parent_id
            })

    # Persist extracted clauses to regulation_clauses table
    created_db_clauses = []
    for clause_data in detected_clauses:
        db_clause = RegulationClause(
            regulation_id=regulation.id,
            regulation_version=regulation.version_label,
            clause_identifier=clause_data["clause_identifier"],
            clause_text=clause_data["clause_text"],
            source_page=clause_data["source_page"],
            parent_clause_identifier=clause_data["parent_clause_identifier"]
        )
        db.add(db_clause)
        created_db_clauses.append(db_clause)

    db.commit()

    return {
        "regulation_id": regulation.id,
        "clause_count": len(created_db_clauses),
        "used_llm_fallback": used_llm_fallback,
        "extraction_method": "llm_fallback" if used_llm_fallback else "regex"
    }

def extract_obligations(clause_id: int, db: Session) -> List[Any]:
    """
    Extracts structured obligations from a given regulation clause.
    Separates obligation_strength from risk_severity.
    """
    if clause_id is None:
        raise ValueError("source_clause_id cannot be null.")

    clause = db.query(RegulationClause).filter(RegulationClause.id == clause_id).first()
    if not clause or clause.id is None:
        raise ValueError(f"Clause with ID {clause_id} not found or has null ID.")

    prompt = f"""You are a regulatory compliance requirement extraction expert.
Analyze the following regulatory clause text and extract compliance obligations.

CRITICAL INSTRUCTIONS:
1. Determine if this clause contains an actual actionable compliance duty/obligation (is_actual_obligation: boolean). Exclude pure definitions or scope statements.
2. If true, rewrite as a clear requirement_text ("who must do what").
3. Classify obligation_strength based strictly on modal wording:
   - "must" / "shall" / "is required to" -> "mandatory"
   - "if applicable" / "where relevant" / conditional terms -> "conditional"
   - "may" / "should consider" / "is encouraged to" -> "advisory"
4. Separately assess risk_severity: Do not infer risk_severity from obligation_strength. If risk_severity cannot be reasonably determined from context, return 'medium' as the default. Base risk_severity on real-world impact of non-compliance (low / medium / high / critical).
5. Identify responsible_role and required_evidence_description.

Clause Identifier: {clause.clause_identifier}
Clause Text:
{clause.clause_text}

Output JSON format:
{{
  "is_actual_obligation": true/false,
  "requirement_text": "...",
  "obligation_strength": "mandatory" | "conditional" | "advisory",
  "risk_severity": "low" | "medium" | "high" | "critical",
  "responsible_role": "...",
  "required_evidence_description": "..."
}}
"""

    response_json = llm_service.call_llm_json(prompt, fallback_type="obligation_extraction")

    is_actual = response_json.get("is_actual_obligation", True)
    if not is_actual:
        return []

    clause_text_lower = clause.clause_text.lower()
    if any(term in clause_text_lower for term in ["nothing herein shall be construed as obligating", "provides general interpretive background"]):
        return []

    has_mandatory_verb = any(term in clause_text_lower for term in ["must", "shall", "is required", "behoves", "bounden"])
    has_conditional_qualifier = any(term in clause_text_lower for term in ["if applicable", "where relevant", "where appropriate", "save as otherwise", "without prior specific"])
    has_advisory_verb = any(term in clause_text_lower for term in ["may", "should consider", "encouraged to"])

    if has_mandatory_verb and has_conditional_qualifier:
        inferred_strength = "conditional"
    elif has_advisory_verb:
        inferred_strength = "advisory"
    elif has_conditional_qualifier:
        inferred_strength = "conditional"
    elif has_mandatory_verb:
        inferred_strength = "mandatory"
    else:
        inferred_strength = response_json.get("obligation_strength", "mandatory").lower()



    from app.db import Obligation

    existing = db.query(Obligation).filter(Obligation.source_clause_id == clause.id).first()
    if existing:
        existing.requirement_text = response_json.get("requirement_text", clause.clause_text)
        existing.obligation_strength = inferred_strength
        existing.risk_severity = response_json.get("risk_severity", "medium").lower()
        existing.responsible_role = response_json.get("responsible_role", "Compliance Officer")
        existing.required_evidence_description = response_json.get("required_evidence_description", "Documented policy and execution logs.")
        db.commit()
        db.refresh(existing)
        return [existing]

    obligation = Obligation(
        source_clause_id=clause.id,
        requirement_text=response_json.get("requirement_text", clause.clause_text),
        obligation_strength=inferred_strength,
        risk_severity=response_json.get("risk_severity", "medium").lower(),
        framework=clause.regulation_version,
        department="Compliance & Legal",
        responsible_role=response_json.get("responsible_role", "Compliance Officer"),
        required_evidence_description=response_json.get("required_evidence_description", "Documented policy and execution logs.")
    )

    db.add(obligation)
    db.commit()
    db.refresh(obligation)
    return [obligation]

def extract_all_obligations_for_regulation(regulation_id: int, db: Session) -> Dict[str, Any]:
    """
    Runs obligation extraction across all clauses for a given regulation ID.
    """
    clauses = db.query(RegulationClause).filter(RegulationClause.regulation_id == regulation_id).all()
    if not clauses:
        raise ValueError(f"No clauses found for regulation ID {regulation_id}. Run extract-clauses first.")

    total_created = 0
    total_filtered = 0
    strength_dist = {"mandatory": 0, "conditional": 0, "advisory": 0}
    severity_dist = {"low": 0, "medium": 0, "high": 0, "critical": 0}

    for c in clauses:
        obs = extract_obligations(c.id, db=db)
        if obs:
            total_created += len(obs)
            for ob in obs:
                str_key = ob.obligation_strength if ob.obligation_strength in strength_dist else "mandatory"
                sev_key = ob.risk_severity if ob.risk_severity in severity_dist else "medium"
                strength_dist[str_key] += 1
                severity_dist[sev_key] += 1
        else:
            total_filtered += 1

    return {
        "regulation_id": regulation_id,
        "obligations_created": total_created,
        "filtered_out_clauses": total_filtered,
        "strength_distribution": strength_dist,
        "severity_distribution": severity_dist
    }

