# Compliance Tracker — Service Agent
## Step-by-Step Build Prompts (v2 — corrected architecture)

Use these prompts **in sequence**, one phase at a time. Each prompt is self-contained — paste it into
your coding assistant, let it finish, test the deliverable, then move to the next prompt. Do not skip
ahead; later phases depend on the schema and interfaces created in earlier ones.

**This version incorporates the following architectural corrections over the original plan:**
1. A separate `regulation_clauses` table sits between regulations and obligations — obligations link
   to a **clause**, not a page number, so clause identity survives across regulation versions.
2. `obligation_strength` (mandatory/conditional/advisory) is tracked **separately** from
   `risk_severity` (low/medium/high/critical) — wording strength and business risk are not the same
   thing and must not be conflated.
3. Regulation change detection is a **4-step pipeline** (clause-ID match → exact text diff → semantic
   fallback match → LLM verification only for ambiguous/significant cases), not cosine similarity alone.
4. Every obligation's live state is split into **three independent fields** — `compliance_status`,
   `workflow_state`, `evidence_state` — instead of one overloaded status field.
5. The State Manager remains **fully deterministic** (no LLM calls) — it only routes, timestamps, and
   stores; AI is used only inside the four agents where semantic judgment is actually required.
6. The Remediation Agent has a **stub interface** (`generate_remediation`) that the State Manager can
   call from Phase 6 onward, even though the real agent isn't built until Phase 9.
7. Exactly **four AI agents**, no more: Requirement Extraction Agent, Evidence & Compliance Agent,
   Change Impact Agent, Remediation Agent. No Database/Dashboard/Notification/Risk agents.
8. Human approval is **policy-gated**, not universal — high-confidence compliant results auto-store;
   only high-risk gaps, critical severity, disputed/low-confidence assessments, and regulation-driven
   re-evaluations route to a human.
9. Regulation change → **targeted impact propagation** only (changed clause → linked obligations →
   linked compliance records → mark only those as `RE_EVALUATION_REQUIRED`), never a full re-scan.

Stack (unchanged, still lightweight): Python + FastAPI, PostgreSQL, FAISS/Chroma for retrieval,
one LLM (Claude) used with different structured prompts per agent, Streamlit or React frontend.
No custom ML model, no large knowledge graph, no unnecessary infrastructure.

---

## PHASE 1 — Document Ingestion

```
I am building a capstone project called "Compliance Tracker — Service Agent." Set up a Python
project with this structure:

compliance-tracker/
├── app/
│   ├── main.py
│   ├── db.py                        # SQLAlchemy models + session
│   ├── agents/
│   │   ├── extraction_agent.py      # Agent 1: Requirement Extraction Agent
│   │   ├── evidence_agent.py        # Agent 2: Evidence & Compliance Agent
│   │   ├── change_impact_agent.py   # Agent 3: Change Impact Agent
│   │   └── remediation_agent.py     # Agent 4: Remediation Agent
│   ├── core/
│   │   └── state_manager.py         # deterministic only, no LLM calls
│   ├── routers/
│   ├── schemas.py
├── tests/
├── requirements.txt
└── README.md

Implement Phase 1 only: document ingestion. Write app/ingestion.py with:

1. `parse_document(file_path) -> ParsedDocument` — accepts PDF or DOCX, extracts raw text
   preserving page numbers (pdfplumber for PDF, python-docx for DOCX). Return a list of
   {page_number, text_block} tuples in reading order. Do NOT attempt clause detection yet —
   that's Phase 2.

2. Create the `regulations` table (SQLAlchemy model):
   - id, title, version_label, uploaded_at, source_file_path, is_current_version (bool)

3. FastAPI endpoint POST /regulations/upload — accepts file + title + version_label, stores the
   file, runs parse_document, inserts a regulations row, and stores the raw parsed page/text
   blocks in a temporary staging table `regulation_raw_pages` (id, regulation_id, page_number,
   raw_text) for Phase 2 to consume. Return the regulation_id and page count.

Write a basic test that uploads a sample 3-page PDF and confirms the raw pages are stored
correctly with page numbers intact.
```

**Deliverable to verify:** uploading a regulation stores raw page-linked text with no data loss.

---

## PHASE 2 — Clause Extraction

```
Extend app/agents/extraction_agent.py with clause-level extraction. This is the first half of
Agent 1 (Requirement Extraction Agent) — clause identification happens before obligation
extraction.

Requirements:

1. Create the `regulation_clauses` table:
   - id, regulation_id (FK), regulation_version (string, denormalized copy of version_label
     for convenience), clause_identifier (e.g. "Article 17", "Section 5.2", "Clause 4.1"),
     clause_text, source_page, source_section (nullable, free text), parent_clause_identifier
     (nullable, for nested clauses like "Article 17(1)" under "Article 17"), created_at

2. `extract_clauses(regulation_id) -> List[RegulationClause]`
   - Read the staged raw pages from Phase 1.
   - First try regex-based clause boundary detection for common patterns: "Article \d+",
     "Section \d+(\.\d+)*", "Clause \d+(\.\d+)*", "Rule \d+", numbered paragraphs. Capture the
     identifier and the clause's full text span (until the next detected boundary).
   - If regex detection finds fewer than 2 boundaries in the whole document (i.e. it likely
     failed), fall back to an LLM call: pass a page of text and ask it to identify clause
     boundaries and identifiers directly, returning strict JSON
     [{clause_identifier, clause_text, parent_clause_identifier}].
   - Insert one row per detected clause into regulation_clauses, linked to source_page.
   - This is a structural step — do NOT judge whether a clause is an obligation here, that
     happens in Phase 3.

3. FastAPI endpoint POST /regulations/{id}/extract-clauses — runs this and returns a summary
   (clause count, how many used regex vs LLM fallback).

Write a test with a fabricated regulation text containing "Article 5", "Article 6", and a nested
"Article 6(1)" — confirm parent_clause_identifier is correctly set for the nested one.
```

**Deliverable to verify:** clauses table has correct identifiers, text, and page links; nested
clause parenting works on at least one example.

---

## PHASE 3 — Obligation Extraction

```
Extend app/agents/extraction_agent.py with the second half of Agent 1: converting clauses into
obligations, with obligation_strength tracked SEPARATELY from risk_severity.

Requirements:

1. Create the `obligations` table:
   - id, source_clause_id (FK to regulation_clauses.id — NOT a page number reference),
     requirement_text (rewritten as a clear "who must do what" statement),
     obligation_strength (enum: mandatory/conditional/advisory),
     risk_severity (enum: low/medium/high/critical, default 'medium' if not determinable),
     framework (e.g. "GDPR"), department (nullable), responsible_role (nullable),
     required_evidence_description, frequency (nullable), deadline_policy (nullable, e.g.
     "30 days"), created_at

2. `extract_obligations(clause_id) -> List[Obligation]`
   - Call Claude with the clause_text and ask it to:
     a. Determine is_actual_obligation (bool) — filter out definitions/scope statements.
     b. If true, extract requirement_text, responsible_role, required_evidence_description.
     c. Classify obligation_strength using the clause's own language:
        "must"/"shall"/"is required to" → mandatory
        "if applicable"/"where relevant"/conditional phrasing → conditional
        "may"/"is encouraged to"/"should consider" → advisory
     d. Separately assess risk_severity — instruct the model explicitly: "Do NOT infer risk
        severity from the obligation_strength wording alone. Base risk_severity on the
        real-world impact of non-compliance (e.g., financial penalty size, data sensitivity,
        harm to individuals, regulatory enforcement history) described or implied in the
        clause. If you cannot reasonably determine risk_severity from context, return 'medium'
        as the default — do not guess 'high' or 'critical' without clear justification."
   - Only insert rows where is_actual_obligation is true.
   - Every inserted obligation must set source_clause_id — never leave it null.

3. FastAPI endpoint POST /regulations/{id}/extract-obligations — runs extract_clauses results
   through this and returns extraction summary (obligations created, filtered out, strength/
   severity distribution).

Write tests with clauses using "must", "may", and "if applicable" phrasing, confirming
obligation_strength is classified correctly, AND confirming risk_severity is NOT simply copied
from the strength word (test with a "must" clause that has low real-world impact and confirm the
model doesn't default to 'critical' just because the word is 'must').
```

**Deliverable to verify:** obligations correctly link to clause IDs (not pages); strength and
severity are visibly independent fields that don't just mirror each other.

---

## PHASE 4 — Evidence Retrieval

```
Implement app/agents/evidence_agent.py — first half of Agent 2 (Evidence & Compliance Agent):
evidence ingestion and retrieval only. Compliance judgment is Phase 5.

Requirements:

1. Create the `evidence_documents` table:
   - id, org_name, title, uploaded_at, source_file_path, expiry_date (nullable),
     evidence_type (nullable, e.g. "policy", "certificate", "SOC2 report")

2. On upload: parse and chunk the document (reuse Phase 1's parser), embed each chunk, store in
   a local vector store (Chroma), tagged with evidence_document_id and page number.

3. `retrieve_evidence(obligation_id, k=5) -> List[EvidenceChunk]`
   - Build a query from obligation.requirement_text + obligation.required_evidence_description.
   - Return top-k chunks by similarity, each with evidence_document_id, matched_text, page,
     similarity_score.
   - This function ONLY retrieves — it does not judge compliance.

4. FastAPI endpoints: POST /evidence/upload (with optional expiry_date), GET
   /obligations/{id}/evidence-candidates (returns retrieve_evidence results for inspection).

Write a test: upload a fabricated policy document, retrieve evidence for a matching obligation,
confirm the most relevant chunk ranks first.
```

**Deliverable to verify:** evidence retrieval returns sensible ranked candidates for a known
obligation-evidence pair.

---

## PHASE 5 — Compliance Assessment

```
Extend app/agents/evidence_agent.py with the compliance-judgment half of Agent 2.

Requirements:

1. `assess_obligation(obligation_id) -> AssessmentResult`
   - Call retrieve_evidence() from Phase 4.
   - Call Claude with the obligation's requirement_text + obligation_strength + retrieved
     chunks, asking for strict JSON:
     - proposed_compliance_status: one of COMPLIANT / PARTIALLY_COMPLIANT / NON_COMPLIANT /
       EVIDENCE_MISSING
     - reasoning (2-4 sentences, must cite specific evidence or explain its absence)
     - matched_excerpts (exact supporting sentences, for citation)
     - confidence_score (0-1)
   - Explicit instruction in the prompt: "If retrieved evidence does not clearly and directly
     address this obligation, you MUST return EVIDENCE_MISSING. Never infer compliance from
     indirect, generic, or unrelated evidence, regardless of how confident you feel."
   - This function returns AssessmentResult only — it does NOT write to any status field
     directly. Phase 6's State Manager owns all state writes.

2. FastAPI endpoint POST /obligations/{id}/assess — runs this and returns the AssessmentResult
   (do not persist any state changes yet — Phase 6 wires this to the State Manager).

Write tests with three fabricated evidence sets: clearly sufficient (expect COMPLIANT),
irrelevant (expect EVIDENCE_MISSING), and partial (expect PARTIALLY_COMPLIANT). Include one test
where evidence is topically related but doesn't actually address the obligation, to confirm the
model doesn't falsely mark it compliant just because it's on-topic.
```

**Deliverable to verify:** assessment never returns a compliant judgment without genuinely
relevant evidence; nothing is persisted to the database from this agent alone yet.

---

## PHASE 6 — Persistent Compliance Lifecycle & State History (Novelty #1)

```
This is the most important phase. Implement app/core/state_manager.py as a FULLY DETERMINISTIC
module — it must not make any LLM calls. Its only job is routing, timestamping, and storing.

Requirements:

1. Create the `compliance_records` table (one row per obligation, representing its LIVE state):
   - id, obligation_id (FK, unique — one active record per obligation),
     compliance_status (enum: NOT_CHECKED/COMPLIANT/PARTIALLY_COMPLIANT/NON_COMPLIANT/
       EVIDENCE_MISSING, default NOT_CHECKED),
     workflow_state (enum: ACTIVE/RE_EVALUATION_REQUIRED/PENDING_HUMAN_REVIEW/
       REMEDIATION_IN_PROGRESS/CLOSED, default ACTIVE),
     evidence_state (enum: VALID/EXPIRING_SOON/EXPIRED, default VALID),
     confidence_score, last_assessed_at, created_at, updated_at

   These three state fields are INDEPENDENT — do not collapse them into one field. Example valid
   combination: compliance_status=COMPLIANT, workflow_state=RE_EVALUATION_REQUIRED,
   evidence_state=EXPIRED (previously compliant, but evidence expired, now needs re-check).

2. Create the `evidence_links` table:
   - id, compliance_record_id (FK), evidence_document_id (FK), matched_excerpt,
     confidence_score, linked_at

3. Create the `state_transitions` table (append-only, NEVER overwritten):
   - id, compliance_record_id (FK), field_changed (enum: compliance_status/workflow_state/
     evidence_state), old_value, new_value, trigger_type (enum: initial_check/new_evidence/
     regulation_change/evidence_expired/human_override/remediation_approved),
     trigger_description, evidence_ids (JSON), reasoning, confidence_score,
     required_human_approval (bool), approved_by (nullable),
     approval_status (enum: auto_applied/pending/approved/rejected), created_at, decided_at

4. `state_manager.record_assessment(obligation_id, assessment_result) -> None`
   Deterministic rules (no LLM call here — assessment_result was already produced by Agent 2 in
   Phase 5):
   - Get or create the compliance_record for this obligation.
   - Determine if human approval is required using this POLICY (implement as a simple rule
     table, easy to extend later):
       * compliance_status == COMPLIANT or PARTIALLY_COMPLIANT AND confidence_score >= 0.85
         AND obligation.risk_severity in (low, medium)
         → auto-apply, approval_status = 'auto_applied'
       * compliance_status == NON_COMPLIANT or EVIDENCE_MISSING
         → requires human approval (always, regardless of confidence)
       * confidence_score < 0.85 (any status)
         → requires human approval (disputed/low-confidence)
       * obligation.risk_severity in (high, critical)
         → requires human approval (always, regardless of status or confidence)
   - If auto-apply: update compliance_records.compliance_status immediately, insert a
     state_transitions row with approval_status='auto_applied', required_human_approval=False.
   - If requires approval: insert a state_transitions row with approval_status='pending',
     required_human_approval=True. Do NOT update compliance_records.compliance_status yet.
     Set workflow_state = 'PENDING_HUMAN_REVIEW'.
     If compliance_status in (NON_COMPLIANT, EVIDENCE_MISSING): call the remediation stub
     `remediation_agent.generate_remediation(obligation_id)` — see note below.

5. `state_manager.generate_remediation` STUB NOTE: at this phase, app/agents/remediation_agent.py
   does not exist yet (it's built in Phase 9). Create a placeholder module now:
   ```
   # app/agents/remediation_agent.py (placeholder — replaced in Phase 9)
   def generate_remediation(obligation_id, compliance_record_id):
       return {
           "status": "stub",
           "message": "Remediation Agent not yet implemented (Phase 9)."
       }
   ```
   The State Manager should call this function and store its return value in a
   `remediation_stub_note` text field on the state_transition row for now, without failing.

6. `state_manager.approve_transition(transition_id, approved_by, edit_notes=None) -> None`
   - Applies the pending field change, sets workflow_state back to 'ACTIVE' (unless a
     remediation is now in progress — Phase 9/10 will refine this), approval_status='approved',
     decided_at=now.

7. `state_manager.reject_transition(transition_id, approved_by, edit_notes) -> None`
   - approval_status='rejected', decided_at=now, no field change applied, reason logged.

8. `state_manager.get_history(obligation_id) -> List[StateTransition]` — full ordered timeline.

9. `state_manager.get_pending_approvals() -> List[StateTransition]`

FastAPI endpoints: GET /obligations/{id}/history, GET /review/pending,
POST /review/{transition_id}/approve, POST /review/{transition_id}/reject.

Write tests covering: auto-apply path (high confidence, low severity, compliant), forced-approval
path due to high severity even with high confidence, forced-approval path due to NON_COMPLIANT
regardless of confidence, and that state_transitions rows are NEVER updated/deleted, only
inserted (append-only check).
```

**Deliverable to verify:** run a compliant high-confidence low-severity assessment → auto-applies.
Run a compliant high-confidence but critical-severity assessment → still requires approval. Run a
non-compliant assessment → requires approval AND the stub remediation note appears.

---

## PHASE 7 — Regulation Change Detection (Novelty #2, detection half)

```
Implement app/agents/change_impact_agent.py — Agent 3, detection responsibilities only
(propagation is Phase 8).

Requirements: implement change detection as a 4-STEP PIPELINE, not similarity alone.

1. `detect_changes(old_regulation_id, new_regulation_id) -> ChangeReport`

   STEP 1 — Clause identifier matching:
   Load regulation_clauses for both versions. Match clauses whose clause_identifier strings are
   identical (e.g. "Article 17" == "Article 17"). These are your primary candidate pairs.

   STEP 2 — Exact text difference on matched pairs:
   For each identifier-matched pair, run a text diff (difflib or similar). If clause_text is
   byte-identical → UNCHANGED. If different → tentatively MODIFIED, store old_clause_text,
   new_clause_text, and a raw diff.

   STEP 3 — Semantic fallback matching for unmatched clauses:
   For clauses with no identifier match in the other version (renamed/restructured), use
   embedding similarity to find the most likely corresponding clause (threshold configurable,
   e.g. > 0.75). If found → treat as tentatively MODIFIED (with old/new text). If truly no match
   above threshold → ADDED (new version only) or REMOVED (old version only).

   STEP 4 — LLM verification for ambiguous/significant cases:
   For every clause marked tentatively MODIFIED, do NOT just trust the text diff. Call Claude
   with old_clause_text and new_clause_text and ask it to determine:
     - meaning_changed (bool) — did the actual compliance obligation change, not just wording?
     - change_reason (short explanation)
     - change_significance: minor_wording / significant_change
   IMPORTANT: explicitly instruct the model with an example like: "Old: 'Delete customer data
   within 30 days.' New: 'Delete customer data within 3 days.' These are textually and
   semantically similar sentences but represent a MAJOR compliance change — the deadline
   changed by an order of magnitude. Do not classify changes as minor just because sentence
   structure is similar; focus on whether the obligated party's actual duty changed (deadlines,
   thresholds, scope, exceptions, penalties)."
   Only run this LLM step on clauses flagged MODIFIED by steps 2/3 — do not run it on every
   clause, to keep this cheap (change detection only runs when a new regulation version is
   uploaded, which is rare).

   Final classification per clause: UNCHANGED / MODIFIED / ADDED / REMOVED. For MODIFIED, persist
   old_clause_text, new_clause_text, change_reason, detected_timestamp on a new
   `clause_change_log` table:
   - id, old_clause_id (FK, nullable if ADDED), new_clause_id (FK, nullable if REMOVED),
     regulation_id, change_type (UNCHANGED/MODIFIED/ADDED/REMOVED), change_reason,
     change_significance, detected_timestamp

2. FastAPI endpoint POST /regulations/{new_id}/detect-changes?compare_to={old_id} — runs the
   pipeline, persists clause_change_log rows, returns the ChangeReport summary.

Write a test with two small fabricated regulations where you inject: one purely cosmetic wording
change (should end up minor_wording), one substantive change like the deadline example above
(should end up significant_change), one added clause, one removed clause. Confirm the pipeline
gets all four right — this is the key test proving Step 4 catches what cosine similarity alone
would miss.
```

**Deliverable to verify:** the deadline-change example (30 days → 3 days) is correctly flagged as
significant_change, not dismissed as a minor wording variant.

---

## PHASE 8 — Impact Propagation (Novelty #2, propagation half)

```
Extend app/agents/change_impact_agent.py with TARGETED impact propagation. Do not re-run
compliance checking on the entire obligation registry — only on records actually affected.

Requirements:

1. `propagate_impact(change_report) -> ImpactSummary`
   Flow (deterministic, calls into state_manager, no LLM call in this function itself):
   - For each clause_change_log entry where change_type in (MODIFIED, REMOVED) AND
     change_significance == 'significant_change' (skip minor_wording changes — they should NOT
     trigger re-evaluation, this is deliberate and part of the novelty: not every text change
     matters):
     a. Find all `obligations` rows where source_clause_id == old_clause_id.
     b. For each such obligation, find its `compliance_records` row.
     c. Call state_manager.trigger_reevaluation(compliance_record_id, reason=change_reason)
        — this is a NEW deterministic State Manager method (add it in state_manager.py):
        ```
        def trigger_reevaluation(compliance_record_id, reason):
            record = get_compliance_record(compliance_record_id)
            old_workflow_state = record.workflow_state
            record.workflow_state = 'RE_EVALUATION_REQUIRED'
            insert_state_transition(
                compliance_record_id=compliance_record_id,
                field_changed='workflow_state',
                old_value=old_workflow_state,
                new_value='RE_EVALUATION_REQUIRED',
                trigger_type='regulation_change',
                trigger_description=reason,
                required_human_approval=False,  # the flag itself doesn't need approval,
                                                  # only the resulting re-assessment does
                approval_status='auto_applied'
            )
        ```
     d. For ADDED clauses with significant new obligations: run Agent 1 (extract_obligations)
        on the new clause to create fresh obligation + compliance_record rows (workflow_state
        starts ACTIVE, compliance_status NOT_CHECKED — this is a brand-new item, not a
        re-evaluation).
   - Note: this function only FLAGS records as RE_EVALUATION_REQUIRED. It does NOT automatically
     re-run Agent 2 (evidence & compliance assessment) — that's a separate, explicit step so a
     human can see what's flagged before the system spends LLM calls re-assessing. Provide a
     separate function `run_targeted_reassessment(compliance_record_ids: List[int])` that loops
     the flagged records through evidence_agent.assess_obligation() + state_manager.
     record_assessment(), reusing Phase 5/6 logic unchanged.

2. FastAPI endpoints:
   - POST /regulations/{new_id}/propagate-impact — runs propagate_impact, returns which
     obligations/compliance_records got flagged.
   - POST /review/reassess-flagged — runs run_targeted_reassessment on all records currently in
     RE_EVALUATION_REQUIRED.

Write a test replicating the brief's own example: "Article 17 modified → Obligation R17 affected
→ Compliance Record CR-102 → previous status COMPLIANT → workflow_state becomes
RE_EVALUATION_REQUIRED" — confirm compliance_status is untouched (still shows COMPLIANT) while
workflow_state changes, proving the two fields are correctly independent.
```

**Deliverable to verify:** only obligations tied to the actually-changed clause get flagged;
unrelated obligations are untouched; compliance_status is preserved while workflow_state changes
(proving Correction 4's field separation is working end-to-end).

---

## PHASE 9 — Remediation Agent (Novelty #3, generation half)

```
Replace the Phase 6 stub with the real app/agents/remediation_agent.py — Agent 4.

Requirements:

1. Create the `remediation_proposals` table:
   - id, compliance_record_id (FK), state_transition_id (FK), gap_explanation,
     cited_requirement, evidence_considered (JSON), missing_evidence, recommended_action,
     suggested_owner, suggested_deadline, priority (enum: low/medium/high/critical),
     status (enum: pending/approved/rejected/edited), human_edit_notes (nullable),
     created_at, decided_at

2. `generate_remediation(obligation_id, compliance_record_id) -> RemediationProposal`
   - Pull the obligation (including obligation_strength and risk_severity — use risk_severity,
     NOT obligation_strength, to seed the suggested priority and deadline, per Correction 2).
   - Pull the compliance_record's current compliance_status and the latest state_transition's
     reasoning.
   - Call Claude with strict JSON output:
     - gap_explanation (2-3 sentences)
     - cited_requirement (echo obligation.requirement_text)
     - evidence_considered (excerpts reviewed, even if insufficient)
     - missing_evidence
     - recommended_action (concrete, not vague)
     - suggested_owner (obligation.responsible_role if set, else infer from department)
   - Deterministically (NOT via LLM) derive:
     - priority: mirror obligation.risk_severity
     - suggested_deadline: critical=7 days, high=30 days, medium=90 days, low=180 days from today
       (use obligation.deadline_policy if explicitly set on the obligation, overriding the
       default)
   - Insert into remediation_proposals, status='pending'.

3. Replace the Phase 6 stub call: state_manager now calls this real function instead of the
   placeholder whenever it creates a pending transition for NON_COMPLIANT/EVIDENCE_MISSING.
   Also set compliance_records.workflow_state = 'REMEDIATION_IN_PROGRESS' once a proposal exists.

Write a test feeding a NON_COMPLIANT compliance_record with critical risk_severity — confirm
suggested_deadline is ~7 days out and priority is 'critical', and that these came from
deterministic logic, not from asking the LLM to pick a number.
```

**Deliverable to verify:** priority/deadline are consistently derived from risk_severity via
code, not LLM guesswork; gap_explanation and recommended_action are LLM-generated and specific.

---

## PHASE 10 — Human Approval Workflow (Novelty #3, approval half)

```
Wire the review queue UI-facing logic together. Most of the mechanics already exist from Phase 6
— this phase focuses on completing the loop end-to-end, including remediation edits and
re-verification after a fix.

Requirements:

1. Extend GET /review/pending to join state_transitions with their remediation_proposals (if
   any) so the frontend can show gap_explanation, recommended_action, owner, deadline, priority
   alongside the raw status change.

2. PUT /remediation/{proposal_id}/edit — human can edit recommended_action, suggested_owner,
   suggested_deadline, priority BEFORE approving. Store edits in human_edit_notes, status='edited'.
   Never overwrite the original AI-generated fields — keep both for audit purposes.

3. POST /review/{transition_id}/approve — extend Phase 6's version:
   - Applies the field change as before.
   - If a remediation_proposal is linked, mark it approved too, and set
     compliance_records.workflow_state = 'ACTIVE' if the underlying issue is now considered
     resolved, or leave as 'REMEDIATION_IN_PROGRESS' if the approval was just of the *plan*
     rather than confirmed evidence of the fix (make this an explicit parameter the human sets
     when approving: `resolution_confirmed: bool`).

4. Re-verification loop: when new evidence is uploaded for an obligation whose
   compliance_record.workflow_state == 'REMEDIATION_IN_PROGRESS', automatically trigger
   evidence_agent.assess_obligation() again and route the result back through
   state_manager.record_assessment() (reusing Phase 5/6 unchanged). If the new assessment is
   COMPLIANT, set workflow_state = 'CLOSED' (after approval, per the same policy rules from
   Phase 6).

Write a test simulating the full loop: NON_COMPLIANT → remediation proposal generated → human
edits the deadline → approves → new evidence uploaded → re-assessment runs → COMPLIANT →
approved → workflow_state ends at 'CLOSED'. Confirm every step is present in state_transitions
history in order.
```

**Deliverable to verify:** the full close-the-loop example from the brief (gap → remediation →
approval → new evidence → re-verification → closed) works end-to-end and is fully visible in
get_history().

---

## PHASE 11 — Evidence Freshness Monitoring (Novelty #4)

```
Implement evidence expiry as a small deterministic addition — no new agent required.

Requirements:

1. Add a scheduled job (APScheduler, daily) plus a manual-trigger endpoint
   POST /evidence/check-expiry for demo purposes.

2. Logic (fully deterministic, in state_manager.py or a small evidence_monitor.py):
   - For each evidence_documents row with expiry_date not null:
     - If expiry_date <= today: evidence_state should become EXPIRED for every linked
       compliance_record (via evidence_links).
     - If expiry_date is within a configurable warning window (default 30 days): evidence_state
       becomes EXPIRING_SOON (no re-evaluation triggered yet, just a visible warning).
   - When evidence_state transitions to EXPIRED:
     ```
     IF evidence_state == EXPIRED:
         workflow_state = RE_EVALUATION_REQUIRED
     ```
     Insert a state_transitions row (field_changed='evidence_state', trigger_type=
     'evidence_expired', required_human_approval=False for the flag itself — same pattern as
     Phase 8's regulation-change flagging: flagging is automatic, the resulting re-assessment
     still goes through normal Phase 6 approval policy).
   - EXPIRING_SOON does not change workflow_state — it's an early-warning display value only.

3. Reuse Phase 8's `run_targeted_reassessment` to actually re-check flagged records on demand
   (or on the same daily schedule, your choice — document which you picked).

Write a test: evidence with expiry_date = yesterday → confirm evidence_state flips to EXPIRED and
workflow_state flips to RE_EVALUATION_REQUIRED, while compliance_status remains untouched (still
shows its last known value, e.g. COMPLIANT) until re-assessment actually runs.
```

**Deliverable to verify:** expired evidence correctly leaves compliance_status alone (it doesn't
silently become NON_COMPLIANT) — it only flags the record for review, consistent with
Correction 4's three-field separation.

---

## PHASE 12 — Dashboard & Evaluation

```
Part A — Minimal frontend (Streamlit or React, your choice):

1. Regulation Upload screen — shows clause + obligation extraction summary.
2. Evidence Upload screen — with optional expiry date.
3. Obligation Dashboard — table showing obligation_strength, risk_severity, and all THREE state
   fields (compliance_status / workflow_state / evidence_state) as separate columns, not merged.
   Clicking a row opens its full history timeline from get_history().
4. Review Queue — pending state_transitions with linked remediation_proposals inline; Approve /
   Reject / Edit-then-Approve buttons; resolution_confirmed toggle per Phase 10.
5. Regulation Version Compare — pick two versions, run detect-changes then propagate-impact,
   show the ChangeReport (with change_significance visible per clause) and which compliance
   records got flagged.

Part B — Evaluation harness (scripts/evaluate.py):

1. Clause/obligation extraction: precision/recall/F1 against ~50 manually annotated clauses.
2. Compliance assessment: accuracy/precision/recall/F1/false-positive-rate against ~30 manually
   labeled obligation-evidence pairs (report false positives — false COMPLIANT calls — separately
   as the most dangerous error type).
3. Change detection: precision/recall of UNCHANGED/MODIFIED/ADDED/REMOVED classification against
   your fabricated version pairs from Phase 7, PLUS a specific check on the "30 days → 3 days"
   -style significant-but-textually-similar case, to demonstrate Step 4's value over
   embedding-similarity-only baselines.
4. Impact propagation precision: did targeted propagation flag exactly the right compliance
   records and nothing else (Phase 8's test, formalized into the harness).
5. Human-in-the-loop metrics: approval rate, edit rate, rejection rate, average time-to-decision,
   percentage of transitions that were auto-applied vs required review (report this against the
   policy rules from Phase 6 — this number is itself evidence the human-approval policy is
   correctly reducing reviewer workload rather than flooding them).
6. Baselines for comparison:
   a. Keyword/rule-based obligation extraction (regex for "shall"/"must"/"required").
   b. Cosine-similarity-only change detection (Steps 1-3 without Step 4) — explicitly compare its
      accuracy against the full 4-step pipeline on the significant-change test case, to
      quantitatively justify Correction 3.
   c. Single-shot LLM compliance check with no state tracking — qualitatively note it cannot
      demonstrate persistent lifecycle, targeted propagation, or evidence freshness at all.

Output a results table (CSV/markdown) for your capstone report, including the Step-4-vs-baseline
comparison from (b) as a specific, concrete number to defend Correction 3 in your viva.
```

**Deliverable to verify:** you can demo the entire corrected lifecycle end-to-end on screen, and
you have a quantitative number showing the 4-step change detection pipeline outperforms
cosine-similarity-only on at least one meaningful-but-similar-wording test case.

---

## Phase Summary

| Phase | Builds | Agent / Component | Novelty |
|---|---|---|---|
| 1 | Document ingestion | — | — |
| 2 | Clause extraction | Agent 1 (part 1) | supports #2 (clause layer) |
| 3 | Obligation extraction | Agent 1 (part 2) | — (baseline, strength≠severity fix) |
| 4 | Evidence retrieval | Agent 2 (part 1) | — |
| 5 | Compliance assessment | Agent 2 (part 2) | — |
| 6 | Persistent lifecycle + history | State Manager (deterministic) | **#1** |
| 7 | Change detection (4-step) | Agent 3 (part 1) | **#2** (detection) |
| 8 | Impact propagation (targeted) | Agent 3 (part 2) + State Manager | **#2** (propagation) |
| 9 | Remediation generation | Agent 4 | **#3** (generation) |
| 10 | Human approval + re-verification | State Manager | **#3** (approval loop) |
| 11 | Evidence freshness | State Manager (deterministic) | **#4** |
| 12 | Dashboard + evaluation | — | demo + numbers for all 4 |

Four agents total (Extraction, Evidence & Compliance, Change Impact, Remediation). One
deterministic State Manager. No Database/Dashboard/Notification/Risk agents, no custom ML model,
no knowledge graph — matching the corrected, lightweight scope.
