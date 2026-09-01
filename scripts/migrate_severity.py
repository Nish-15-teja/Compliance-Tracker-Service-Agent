import os
import sys
import logging

# Add parent directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.db import SessionLocal, Obligation
from app.core.llm import llm_service

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("MigrateSeverity")

def migrate_severity():
    db = SessionLocal()
    try:
        obligations = db.query(Obligation).all()
        logger.info(f"Retrieved {len(obligations)} obligations for strength/severity migration.")

        migrated_count = 0
        flagged_count = 0

        for ob in obligations:
            old_severity = ob.risk_severity
            clause_text = ob.source_clause.clause_text if ob.source_clause else ""
            req_text = ob.requirement_text

            prompt = f"""You are a regulatory compliance auditor.
Analyze the following regulatory requirement and its source clause text to independently classify:
1. obligation_strength (mandatory, conditional, advisory) based strictly on modal wording:
   - "must" / "shall" / "is required to" -> "mandatory"
   - "if applicable" / "where relevant" / conditional terms -> "conditional"
   - "may" / "should consider" / "is encouraged to" -> "advisory"
2. risk_severity (low, medium, high, critical) based strictly on the real-world impact of non-compliance (financial penalties, data sensitivity, enforcement history).
Do not infer risk_severity from obligation_strength. If risk_severity cannot be reasonably determined from context, return 'medium' as the default.

Source Clause Text: {clause_text}
Requirement Text: {req_text}

Output strict JSON:
{{
  "obligation_strength": "mandatory" | "conditional" | "advisory",
  "risk_severity": "low" | "medium" | "high" | "critical"
}}
"""
            try:
                res = llm_service.call_llm_json(prompt, fallback_type="obligation_extraction")
                new_strength = res.get("obligation_strength", "mandatory").lower()
                new_severity = res.get("risk_severity", "medium").lower()

                ob.obligation_strength = new_strength
                ob.risk_severity = new_severity
                db.commit()

                # Flagging condition: if old severity was 'critical' and strength was 'mandatory'
                # but now it's classified differently or fits the warning case.
                # Specifically: "every 'must' clause marked 'critical'"
                # Let's flag if old_severity was 'critical' and new_strength is 'mandatory'
                if old_severity == "critical" and new_strength == "mandatory":
                    logger.warning(f"[FLAG FOR SPOT-CHECK] Obligation ID {ob.id}: old severity was 'critical' and wording strength is 'mandatory'. Requirement: '{req_text}'")
                    flagged_count += 1

                migrated_count += 1
            except Exception as e:
                db.rollback()
                logger.error(f"Failed to migrate Obligation ID {ob.id}: {e}")

        logger.info(f"Migration completed. Migrated: {migrated_count}, Flagged for spot-check: {flagged_count}")
    finally:
        db.close()

if __name__ == "__main__":
    migrate_severity()
