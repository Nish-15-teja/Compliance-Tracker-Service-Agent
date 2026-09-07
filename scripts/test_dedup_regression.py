import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.db import SessionLocal, init_db, Regulation, RegulationRawPage, RegulationClause, Obligation
from app.agents.extraction_agent import extract_clauses, extract_all_obligations_for_regulation

def run_test():
    init_db()
    db = SessionLocal()

    # Create temporary regulation for regression testing
    reg = Regulation(title="Dedup Regression Test Regulation", version_label="v1.0", source_file_path="dedup_test.txt")
    db.add(reg)
    db.commit()

    raw_p = RegulationRawPage(
        regulation_id=reg.id,
        page_number=1,
        raw_text=(
            "Article 1 Access Control.\n"
            "All enterprise personnel must use multi-factor authentication for cloud console access.\n\n"
            "Article 2 Data Retention.\n"
            "Financial audit records shall be retained for a minimum duration of seven years.\n\n"
            "Article 3 Cryptographic Controls.\n"
            "All customer data at rest must be encrypted using AES-256 or equivalent standards."
        )
    )
    db.add(raw_p)
    db.commit()

    # Step 1: Extract clauses
    clause_summary = extract_clauses(reg.id, db)
    clauses = db.query(RegulationClause).filter(RegulationClause.regulation_id == reg.id).all()
    print(f"Clauses extracted: {len(clauses)}")

    # Run 1
    r1 = extract_all_obligations_for_regulation(reg.id, db)
    c1 = db.query(Obligation).filter(Obligation.source_clause_id.in_([c.id for c in clauses])).count()
    print(f"Run 1 -> Result: {r1['obligations_created']} obligations, Total DB Obligation Count: {c1}")

    # Run 2
    r2 = extract_all_obligations_for_regulation(reg.id, db)
    c2 = db.query(Obligation).filter(Obligation.source_clause_id.in_([c.id for c in clauses])).count()
    print(f"Run 2 -> Result: {r2['obligations_created']} obligations, Total DB Obligation Count: {c2}")

    # Run 3
    r3 = extract_all_obligations_for_regulation(reg.id, db)
    c3 = db.query(Obligation).filter(Obligation.source_clause_id.in_([c.id for c in clauses])).count()
    print(f"Run 3 -> Result: {r3['obligations_created']} obligations, Total DB Obligation Count: {c3}")

    assert c1 == 3, f"Expected 3 after Run 1, got {c1}"
    assert c2 == 3, f"Expected 3 after Run 2, got {c2}"
    assert c3 == 3, f"Expected 3 after Run 3, got {c3}"
    print("\nSUCCESS: Obligation count remained invariant at exactly 3 across all 3 extraction runs.")

if __name__ == "__main__":
    run_test()
