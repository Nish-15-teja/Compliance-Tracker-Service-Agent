import os
import sys
from datetime import datetime, timedelta, timezone

# Add parent directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.db import (
    init_db, SessionLocal, Regulation, RegulationRawPage, RegulationClause,
    Obligation, EvidenceDocument, ComplianceRecord, EvidenceLink
)
from app.agents.extraction_agent import extract_clauses, extract_all_obligations_for_regulation
from app.agents.change_impact_agent import detect_changes, propagate_impact
from app.agents.evidence_agent import index_evidence_document, assess_obligation
from app.core.state_manager import state_manager

def seed_demo_data():
    init_db()
    db = SessionLocal()

    print("Seeding Compliance Tracker demonstration dataset...")

    # 1. Create Regulations
    reg_v1 = Regulation(
        title="EU General Data Protection Regulation (GDPR)",
        version_label="v1.0",
        source_file_path="uploads/regulations/v1.0_GDPR.pdf",
        is_current_version=False
    )
    reg_v2 = Regulation(
        title="EU General Data Protection Regulation (GDPR)",
        version_label="v2.0",
        source_file_path="uploads/regulations/v2.0_GDPR.pdf",
        is_current_version=True
    )
    db.add_all([reg_v1, reg_v2])
    db.commit()

    # 2. Raw pages for Regulation v1.0
    raw_v1_p1 = RegulationRawPage(
        regulation_id=reg_v1.id,
        page_number=1,
        raw_text="""Article 5 Principles relating to processing of personal data.
Personal data shall be processed lawfully, fairly and in a transparent manner.

Article 17 Right to erasure ('right to be forgotten').
The controller shall have the obligation to erase personal data without undue delay, and at the latest within 30 days of request.

Article 17(1) Erasure conditions.
The personal data are no longer necessary in relation to the purposes for which they were collected or otherwise processed."""
    )
    db.add(raw_v1_p1)

    # Raw pages for Regulation v2.0
    raw_v2_p1 = RegulationRawPage(
        regulation_id=reg_v2.id,
        page_number=1,
        raw_text="""Article 5 Principles relating to processing of personal data.
Personal data shall be processed lawfully, fairly and in a transparent manner (minor cosmetic notice).

Article 17 Right to erasure ('right to be forgotten').
The controller shall have the obligation to erase personal data without undue delay, and at the latest within 3 days of request.

Article 17(1) Erasure conditions.
The personal data are no longer necessary in relation to the purposes for which they were collected or otherwise processed.

Article 35 High risk processing AI impact assessment.
Controllers must execute formal risk impact assessments prior to deploying automated decision-making engines."""
    )
    db.add(raw_v2_p1)
    db.commit()

    # 3. Extract Clauses & Obligations for v1.0
    print("[1/5] Extracting Clauses & Obligations for Regulation v1.0...")
    c_res1 = extract_clauses(regulation_id=reg_v1.id, db=db)
    o_res1 = extract_all_obligations_for_regulation(regulation_id=reg_v1.id, db=db)

    # 4. Extract Clauses & Obligations for v2.0
    print("[2/5] Extracting Clauses & Obligations for Regulation v2.0...")
    c_res2 = extract_clauses(regulation_id=reg_v2.id, db=db)
    o_res2 = extract_all_obligations_for_regulation(regulation_id=reg_v2.id, db=db)

    # 5. Create & Index Evidence Document
    ev_path = "uploads/evidence/sample_deletion_sop.txt"
    os.makedirs("uploads/evidence", exist_ok=True)
    with open(ev_path, "w", encoding="utf-8") as f:
        f.write("""Acme Corp Data Deletion Standard Operating Procedure.
Section 1: Data Erasure Request Processing.
All customer erasure requests received via support portal are processed, confirmed, and purged from production databases within 30 days of receipt.""")

    ev_doc = EvidenceDocument(
        org_name="Acme Corp",
        title="Customer Data Erasure Standard Operating Procedure",
        source_file_path=ev_path,
        expiry_date=datetime.now(timezone.utc) + timedelta(days=180),
        evidence_type="policy"
    )
    db.add(ev_doc)
    db.commit()
    db.refresh(ev_doc)

    index_evidence_document(evidence_document_id=ev_doc.id, file_path=ev_path, db=db)

    # 6. Run Initial Assessment for v1.0 Obligations
    print("[3/5] Running initial evidence assessments...")
    v1_obs = db.query(Obligation).join(RegulationClause).filter(RegulationClause.regulation_id == reg_v1.id).all()
    for ob in v1_obs:
        assessment = assess_obligation(obligation_id=ob.id, db=db)
        state_manager.record_assessment(obligation_id=ob.id, assessment_result=assessment, db=db)

    # 7. Run 4-Step Regulation Change Detection & Targeted Impact Propagation
    print("[4/5] Running 4-Step Regulation Change Detection (v1.0 -> v2.0)...")
    change_report = detect_changes(old_regulation_id=reg_v1.id, new_regulation_id=reg_v2.id, db=db)
    print("[5/5] Running Targeted Impact Propagation...")
    impact_summary = propagate_impact(new_regulation_id=reg_v2.id, db=db)

    print("\nDemo dataset seeded successfully!")
    print(f"- Regulations: 2 versions seeded")
    print(f"- Detected Changes: {change_report['total_changes']} clause changes")
    print(f"- Flagged Records for Re-evaluation: {impact_summary['flagged_count']}")

if __name__ == "__main__":
    seed_demo_data()
