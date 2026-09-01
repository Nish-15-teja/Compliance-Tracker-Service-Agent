import os
import sys
import logging

# Add parent directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.db import SessionLocal, Obligation, RegulationClause, Regulation

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("MigrateClauses")

def migrate_clauses():
    db = SessionLocal()
    try:
        obligations = db.query(Obligation).all()
        logger.info(f"Retrieved {len(obligations)} obligations for clause layer check/backfill.")

        backfilled_count = 0
        failed_count = 0

        # Ensure we have at least one default regulation if we need to assign clauses
        default_reg = db.query(Regulation).order_by(Regulation.id.asc()).first()

        for ob in obligations:
            # Check if source_clause_id is missing (or 0/null in SQLite)
            # Since source_clause_id has a NOT NULL constraint in our current db.py,
            # this would happen if there are legacy obligations from a schema without it,
            # or if the database contains records with 0/null due to bypassed constraints.
            try:
                if not ob.source_clause_id or ob.source_clause is None:
                    logger.warning(f"Obligation ID {ob.id} lacks a source_clause_id connection. Attempting backfill...")
                    
                    reg_id = None
                    reg_version = "UNSPECIFIED"
                    
                    if default_reg:
                        reg_id = default_reg.id
                        reg_version = default_reg.version_label
                    else:
                        # Create a placeholder regulation if none exists
                        placeholder_reg = Regulation(
                            title="Placeholder Regulation for Migrated Clauses",
                            version_label="v1.0",
                            source_file_path="dummy_placeholder.pdf",
                            is_current_version=True
                        )
                        db.add(placeholder_reg)
                        db.commit()
                        db.refresh(placeholder_reg)
                        default_reg = placeholder_reg
                        reg_id = default_reg.id
                        reg_version = default_reg.version_label

                    # Create a best-effort clause
                    clause_ident = f"UNSPECIFIED-{ob.id}"
                    best_effort_clause = RegulationClause(
                        regulation_id=reg_id,
                        regulation_version=reg_version,
                        clause_identifier=clause_ident,
                        clause_text=ob.requirement_text[:200] + "..." if len(ob.requirement_text) > 200 else ob.requirement_text,
                        source_page=1,
                        source_section="UNSPECIFIED",
                        parent_clause_identifier=None
                    )
                    db.add(best_effort_clause)
                    db.commit()
                    db.refresh(best_effort_clause)

                    # Update obligation linkage
                    ob.source_clause_id = best_effort_clause.id
                    db.commit()
                    backfilled_count += 1
                    logger.info(f"Successfully backfilled Obligation ID {ob.id} with Clause ID {best_effort_clause.id}")
            except Exception as e:
                db.rollback()
                failed_count += 1
                logger.error(f"Failed to cleanly backfill Obligation ID {ob.id if ob else 'unknown'}: {e}")

        logger.info(f"Migration completed. Backfilled: {backfilled_count}, Failed/Manual review required: {failed_count}")
    finally:
        db.close()

if __name__ == "__main__":
    migrate_clauses()
