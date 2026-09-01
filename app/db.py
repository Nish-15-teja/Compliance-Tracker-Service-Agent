import os
from datetime import datetime, timezone
from sqlalchemy import (
    create_engine, Column, Integer, String, Text, Boolean, DateTime, ForeignKey, Float, Enum, JSON
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

from sqlalchemy.pool import StaticPool

from sqlalchemy import event

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./compliance_tracker.db")

connect_args = {}
engine_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False
    connect_args["timeout"] = 30
    if ":memory:" in DATABASE_URL or os.getenv("TESTING") == "1":
        engine_args["poolclass"] = StaticPool

engine = create_engine(DATABASE_URL, connect_args=connect_args, **engine_args)

@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    if DATABASE_URL.startswith("sqlite"):
        try:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.close()
        except Exception:
            pass

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Phase 1 Models
class Regulation(Base):
    __tablename__ = "regulations"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    version_label = Column(String, nullable=False)
    uploaded_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    source_file_path = Column(String, nullable=False)
    is_current_version = Column(Boolean, default=True)

    raw_pages = relationship("RegulationRawPage", back_populates="regulation", cascade="all, delete-orphan")
    clauses = relationship("RegulationClause", back_populates="regulation", cascade="all, delete-orphan")

class RegulationRawPage(Base):
    __tablename__ = "regulation_raw_pages"

    id = Column(Integer, primary_key=True, index=True)
    regulation_id = Column(Integer, ForeignKey("regulations.id", ondelete="CASCADE"), nullable=False)
    page_number = Column(Integer, nullable=False)
    raw_text = Column(Text, nullable=False)

    regulation = relationship("Regulation", back_populates="raw_pages")

# Phase 2 Models
class RegulationClause(Base):
    __tablename__ = "regulation_clauses"

    id = Column(Integer, primary_key=True, index=True)
    regulation_id = Column(Integer, ForeignKey("regulations.id", ondelete="CASCADE"), nullable=False)
    regulation_version = Column(String, nullable=False)
    clause_identifier = Column(String, nullable=False)
    clause_text = Column(Text, nullable=False)
    source_page = Column(Integer, nullable=False)
    source_section = Column(String, nullable=True)
    parent_clause_identifier = Column(String, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    regulation = relationship("Regulation", back_populates="clauses")
    obligations = relationship("Obligation", back_populates="source_clause", cascade="all, delete-orphan")

# Phase 3 Models
class Obligation(Base):
    __tablename__ = "obligations"

    id = Column(Integer, primary_key=True, index=True)
    source_clause_id = Column(Integer, ForeignKey("regulation_clauses.id", ondelete="CASCADE"), nullable=False)
    requirement_text = Column(Text, nullable=False)
    obligation_strength = Column(String, nullable=False) # mandatory / conditional / advisory
    risk_severity = Column(String, nullable=False, default="medium") # low / medium / high / critical
    framework = Column(String, nullable=True, default="General Regulatory Framework")
    department = Column(String, nullable=True)
    responsible_role = Column(String, nullable=True)
    required_evidence_description = Column(Text, nullable=False)
    frequency = Column(String, nullable=True)
    deadline_policy = Column(String, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    source_clause = relationship("RegulationClause", back_populates="obligations")
    compliance_record = relationship("ComplianceRecord", back_populates="obligation", uselist=False, cascade="all, delete-orphan")

# Phase 4 Models
class EvidenceDocument(Base):
    __tablename__ = "evidence_documents"

    id = Column(Integer, primary_key=True, index=True)
    org_name = Column(String, nullable=False)
    title = Column(String, nullable=False)
    uploaded_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    source_file_path = Column(String, nullable=False)
    expiry_date = Column(DateTime, nullable=True)
    evidence_type = Column(String, nullable=True)

    links = relationship("EvidenceLink", back_populates="evidence_document")

# Phase 6 Models
class ComplianceRecord(Base):
    __tablename__ = "compliance_records"

    id = Column(Integer, primary_key=True, index=True)
    obligation_id = Column(Integer, ForeignKey("obligations.id", ondelete="CASCADE"), unique=True, nullable=False)
    compliance_status = Column(String, nullable=False, default="NOT_CHECKED") # NOT_CHECKED / COMPLIANT / PARTIALLY_COMPLIANT / NON_COMPLIANT / EVIDENCE_MISSING
    workflow_state = Column(String, nullable=False, default="ACTIVE") # ACTIVE / RE_EVALUATION_REQUIRED / PENDING_HUMAN_REVIEW / REMEDIATION_IN_PROGRESS / CLOSED
    evidence_state = Column(String, nullable=False, default="VALID") # VALID / EXPIRING_SOON / EXPIRED
    confidence_score = Column(Float, nullable=True)
    last_assessed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    obligation = relationship("Obligation", back_populates="compliance_record")
    evidence_links = relationship("EvidenceLink", back_populates="compliance_record", cascade="all, delete-orphan")
    transitions = relationship("StateTransition", back_populates="compliance_record", cascade="all, delete-orphan")
    remediations = relationship("RemediationProposal", back_populates="compliance_record", cascade="all, delete-orphan")

class EvidenceLink(Base):
    __tablename__ = "evidence_links"

    id = Column(Integer, primary_key=True, index=True)
    compliance_record_id = Column(Integer, ForeignKey("compliance_records.id", ondelete="CASCADE"), nullable=False)
    evidence_document_id = Column(Integer, ForeignKey("evidence_documents.id", ondelete="CASCADE"), nullable=False)
    matched_excerpt = Column(Text, nullable=False)
    confidence_score = Column(Float, nullable=False)
    linked_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    compliance_record = relationship("ComplianceRecord", back_populates="evidence_links")
    evidence_document = relationship("EvidenceDocument", back_populates="links")

class StateTransition(Base):
    __tablename__ = "state_transitions"

    id = Column(Integer, primary_key=True, index=True)
    compliance_record_id = Column(Integer, ForeignKey("compliance_records.id", ondelete="CASCADE"), nullable=False)
    field_changed = Column(String, nullable=False) # compliance_status / workflow_state / evidence_state
    old_value = Column(String, nullable=True)
    new_value = Column(String, nullable=False)
    trigger_type = Column(String, nullable=False) # initial_check / new_evidence / regulation_change / evidence_expired / human_override / remediation_approved
    trigger_description = Column(Text, nullable=True)
    evidence_ids = Column(JSON, nullable=True)
    reasoning = Column(Text, nullable=True)
    confidence_score = Column(Float, nullable=True)
    required_human_approval = Column(Boolean, default=False)
    approved_by = Column(String, nullable=True)
    approval_status = Column(String, default="auto_applied") # auto_applied / pending / approved / rejected
    remediation_stub_note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    decided_at = Column(DateTime, nullable=True)

    compliance_record = relationship("ComplianceRecord", back_populates="transitions")
    remediation_proposal = relationship("RemediationProposal", back_populates="state_transition", uselist=False)

# Phase 7 Models
class ClauseChangeLog(Base):
    __tablename__ = "clause_change_log"

    id = Column(Integer, primary_key=True, index=True)
    old_clause_id = Column(Integer, ForeignKey("regulation_clauses.id", ondelete="SET NULL"), nullable=True)
    new_clause_id = Column(Integer, ForeignKey("regulation_clauses.id", ondelete="SET NULL"), nullable=True)
    regulation_id = Column(Integer, ForeignKey("regulations.id", ondelete="CASCADE"), nullable=False)
    change_type = Column(String, nullable=False) # UNCHANGED / MODIFIED / ADDED / REMOVED
    change_reason = Column(Text, nullable=True)
    change_significance = Column(String, nullable=True) # minor_wording / significant_change
    detected_timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))

# Phase 9 Models
class RemediationProposal(Base):
    __tablename__ = "remediation_proposals"

    id = Column(Integer, primary_key=True, index=True)
    compliance_record_id = Column(Integer, ForeignKey("compliance_records.id", ondelete="CASCADE"), nullable=False)
    state_transition_id = Column(Integer, ForeignKey("state_transitions.id", ondelete="CASCADE"), nullable=False)
    gap_explanation = Column(Text, nullable=False)
    cited_requirement = Column(Text, nullable=False)
    evidence_considered = Column(JSON, nullable=True)
    missing_evidence = Column(Text, nullable=False)
    recommended_action = Column(Text, nullable=False)
    suggested_owner = Column(String, nullable=False)
    suggested_deadline = Column(DateTime, nullable=False)
    priority = Column(String, nullable=False) # low / medium / high / critical
    status = Column(String, default="pending") # pending / approved / rejected / edited
    human_edit_notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    decided_at = Column(DateTime, nullable=True)

    compliance_record = relationship("ComplianceRecord", back_populates="remediations")
    state_transition = relationship("StateTransition", back_populates="remediation_proposal")

def init_db():
    Base.metadata.create_all(bind=engine)
