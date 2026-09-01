import os
import sys
import logging
from sqlalchemy import text

# Add parent directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.db import SessionLocal, Obligation, ComplianceRecord

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("MigrateStates")

def migrate_states():
    db = SessionLocal()
    try:
        # Check if the obligations table has a 'status' column in the physical database
        conn = db.bind.raw_connection()
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(obligations)")
        columns = [row[1] for row in cursor.fetchall()]
        
        has_legacy_status = "status" in columns
        logger.info(f"Checking for legacy 'status' column in obligations: {has_legacy_status}")

        obligations = db.query(Obligation).all()
        migrated_count = 0

        for ob in obligations:
            # Check if a ComplianceRecord already exists
            record = db.query(ComplianceRecord).filter(ComplianceRecord.obligation_id == ob.id).first()
            
            legacy_status = "NOT_CHECKED"
            if has_legacy_status:
                # Query it dynamically via text to bypass model restrictions
                res = db.execute(text(f"SELECT status FROM obligations WHERE id = {ob.id}")).fetchone()
                if res and res[0]:
                    legacy_status = res[0]

            if not record:
                # Map legacy status to compliance_status
                mapped_status = "NOT_CHECKED"
                mapped_wf = "ACTIVE"
                mapped_ev = "VALID"

                if legacy_status in ["COMPLIANT", "PARTIALLY_COMPLIANT", "NON_COMPLIANT", "EVIDENCE_MISSING", "NOT_CHECKED"]:
                    mapped_status = legacy_status
                
                # Setup defaults
                if mapped_status in ["NON_COMPLIANT", "EVIDENCE_MISSING"]:
                    mapped_wf = "PENDING_HUMAN_REVIEW"
                
                record = ComplianceRecord(
                    obligation_id=ob.id,
                    compliance_status=mapped_status,
                    workflow_state=mapped_wf,
                    evidence_state=mapped_ev,
                    confidence_score=0.0
                )
                db.add(record)
                db.commit()
                migrated_count += 1
                logger.info(f"Created ComplianceRecord for Obligation ID {ob.id} with status {mapped_status}")
            else:
                # Record exists, ensure it is aligned
                if has_legacy_status and legacy_status != "NOT_CHECKED" and record.compliance_status == "NOT_CHECKED":
                    record.compliance_status = legacy_status
                    db.commit()
                    migrated_count += 1
                    logger.info(f"Updated ComplianceRecord for Obligation ID {ob.id} to match legacy status {legacy_status}")

        logger.info(f"State migration completed. Affected: {migrated_count} records.")
    except Exception as e:
        logger.error(f"Migration error: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    migrate_states()
