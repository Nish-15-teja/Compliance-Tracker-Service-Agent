# Compliance-Tracker based on pdf and other documents-Service-Agent

Autonomous regulatory compliance, change-impact tracking, and human-in-the-loop remediation
platform. Extracts obligations from regulatory documents (PDF/DOCX/TXT), matches them against an
organization's internal documents as evidence, and — unlike one-shot compliance checkers —
maintains a **persistent, evolving compliance record per obligation** that survives regulation
changes, evidence expiry, and remediation cycles, with every meaningful state change routed
through an auditable, policy-gated human-approval workflow.

---

## Why this exists

Most compliance-AI tools stop at:

```
document → compliance result
```

This system tracks the full lifecycle instead:

```
document → clause → obligation → evidence → compliance state → risk → remediation → owner
    → deadline → re-verification → audit history
```

No status is ever silently overwritten — every transition is timestamped, reasoned, and appended
to a permanent history per obligation.

---

## Core Novelty Mechanisms

| # | Mechanism | What it does |
|---|---|---|
| 1 | **Persistent Compliance Lifecycle** | Every obligation has a live `ComplianceRecord` with a full, append-only `StateTransition` history — not a one-time report. |
| 2 | **Regulation Change Detection & Impact Propagation** | Detects clause-level changes between regulation versions and cascades re-evaluation *only* to the obligations actually affected by a significant change. |
| 3 | **Agentic Remediation with Human Approval** | On a compliance gap, an agent proposes a structured fix (action, owner, deadline, priority) — routed to a human review queue before any status is finalized. |
| 4 | **Evidence Freshness & Expiry Monitoring** | Evidence expiry is tracked independently of the compliance judgment it once supported, automatically flagging records for re-evaluation without silently downgrading past decisions. |

---

## Architecture

Four AI agents, one fully deterministic State Manager — no more, no less.

```
Input Documents (PDF / DOCX / TXT)
        │
        ▼
┌────────────────────────┐
│ Requirement Extraction  │  app/agents/extraction_agent.py
│ Agent                   │  clause detection → obligation extraction →
│                          │  obligation_strength (mandatory/conditional/advisory)
│                          │  classified separately from risk_severity (low–critical)
└────────────┬─────────────┘
             ▼
┌────────────────────────┐
│ Evidence & Compliance   │  app/agents/evidence_agent.py
│ Agent                   │  evidence retrieval + compliance judgment + reasoning
└────────────┬─────────────┘
             ▼
┌────────────────────────┐
│     State Manager        │  app/core/state_manager.py — ZERO LLM calls.
│  (deterministic only)    │  Owns every status write, approval routing,
│                           │  history, and policy decisions.
└────────────┬─────────────┘
             │
   ┌─────────┴──────────┐
   ▼                     ▼
┌───────────────┐  ┌──────────────────┐
│ Change Impact  │  │ Remediation      │  app/agents/change_impact_agent.py
│ Agent          │  │ Agent            │  app/agents/remediation_agent.py
└───────────────┘  └──────────────────┘
             │
             ▼
      Human Approval Queue  (app/routers/review.py)
             │
             ▼
   Compliance Tracker + Append-Only Audit Trail
```

### Change detection pipeline (Agent 3)

`detect_changes()` matches clauses by stable `clause_identifier` first, diffs exact text on
matched pairs, falls back to similarity matching for renamed/restructured clauses, and only calls
the LLM (`_verify_clause_change_llm`) to judge `change_significance` (minor_wording vs
significant_change) on clauses that were actually flagged as changed — not on every clause. Only
`significant_change` clauses trigger downstream re-evaluation via `propagate_impact()`, which
flags just the affected `ComplianceRecord`s rather than re-scanning the full registry;
`run_targeted_reassessment()` then re-runs Agent 2 only on those flagged records.

### Data model

- `regulations` → `regulation_clauses` → `obligations` → `compliance_records` → `evidence_links`
  / `state_transitions` / `remediation_proposals`. Obligations link to a clause via
  `source_clause_id`, not a page number, so identity survives across regulation versions.
- `obligation_strength` (mandatory/conditional/advisory) and `risk_severity`
  (low/medium/high/critical) are tracked as **independent fields** — extraction logic never
  derives one from the other.
- Every `ComplianceRecord` carries **three independent state fields**: `compliance_status`,
  `workflow_state`, `evidence_state` — e.g. a record can be `COMPLIANT` +
  `RE_EVALUATION_REQUIRED` + `EXPIRED` simultaneously, meaning "previously compliant, but its
  evidence lapsed and it now needs review."
- `state_transitions` is append-only — nothing is ever overwritten, only added to.

### Human approval policy (deterministic, in `state_manager.py`)

- **Auto-applied** (no review needed): status is `COMPLIANT`/`PARTIALLY_COMPLIANT`, confidence
  ≥ 0.85, and `risk_severity` is low or medium.
- **Always routed to human review**: `NON_COMPLIANT` or `EVIDENCE_MISSING`, confidence < 0.85, or
  `risk_severity` is high/critical — regardless of what the status says.
- Every decision — auto-applied or human-decided — is recorded in `state_transitions`.

---

## Tech Stack

- **Backend:** FastAPI + SQLAlchemy
- **Database:** SQLite by default (`DATABASE_URL` env override for Postgres)
- **Document parsing:** pdfplumber (PDF), python-docx (DOCX)
- **Retrieval:** lightweight in-process term-overlap vector store (`app/core/vector_store.py`) —
  no external vector DB dependency
- **LLM:** unified service (`app/core/llm.py`) — calls Claude (`claude-3-5-sonnet-20241022`) if
  `ANTHROPIC_API_KEY` is set, falls back to OpenAI (`gpt-4o`) if `OPENAI_API_KEY` is set instead,
  and falls back further to a deterministic mock JSON engine when neither key is present (keeps
  tests and offline demos runnable without API access)
- **Frontend:** Streamlit (`app_ui.py`) — 5 tabs: Regulation Upload, Evidence Upload, Obligation
  Dashboard, Review Queue, Regulation Version Compare
- **Scheduling / freshness:** on-demand expiry check (`app/core/evidence_monitor.py`)

---

## Getting Started

```bash
git clone https://github.com/<your-username>/compliance-tracker.git
cd compliance-tracker
pip install -r requirements.txt

# optional — without these the LLM calls fall back to a deterministic mock engine
export ANTHROPIC_API_KEY=your_key_here
# or: export OPENAI_API_KEY=your_key_here

# start the API
uvicorn app.main:app --reload

# in a separate terminal — start the dashboard
streamlit run app_ui.py
```

The API is served at `http://127.0.0.1:8000`, the Streamlit dashboard at
`http://127.0.0.1:8501` (default `API_BASE_URL` env var points the UI at the local API).

### Seed demo data

```bash
python scripts/seed_demo.py
```

### Run tests

```bash
pytest
```

### Run the evaluation harness

```bash
python scripts/evaluate.py
```

---

## Project Structure

```
compliance-tracker/
├── app/
│   ├── main.py                      # FastAPI entrypoint
│   ├── db.py                        # SQLAlchemy models
│   ├── ingestion.py                 # PDF/DOCX parsing
│   ├── schemas.py
│   ├── agents/
│   │   ├── extraction_agent.py      # Agent 1 — clauses + obligations
│   │   ├── evidence_agent.py        # Agent 2 — retrieval + compliance judgment
│   │   ├── change_impact_agent.py   # Agent 3 — version diff + targeted propagation
│   │   └── remediation_agent.py     # Agent 4 — gap remediation proposals
│   ├── core/
│   │   ├── state_manager.py         # deterministic — zero LLM calls
│   │   ├── evidence_monitor.py      # evidence expiry checks
│   │   ├── vector_store.py          # lightweight retrieval
│   │   └── llm.py                   # Claude / OpenAI / mock fallback service
│   └── routers/
│       ├── regulations.py
│       ├── evidence.py
│       ├── obligations.py
│       └── review.py                # approval queue endpoints
├── app_ui.py                        # Streamlit dashboard
├── scripts/
│   ├── evaluate.py
│   └── seed_demo.py
├── tests/                           # test_phase1.py – test_phase12.py
├── uploads/
│   ├── regulations/
│   └── evidence/
├── evaluation_report.md
├── requirements.txt
└── README.md
```

---

## API Overview

| Endpoint | Purpose |
|---|---|
| `POST /regulations/upload` | Upload a regulation document |
| `POST /regulations/{id}/extract-clauses` | Run clause extraction |
| `POST /regulations/{id}/extract-obligations` | Run obligation extraction |
| `POST /regulations/{new_id}/detect-changes` | Compare against a prior regulation version |
| `POST /regulations/{new_id}/propagate-impact` | Cascade targeted re-evaluation flags |
| `POST /evidence/upload` | Upload an organizational evidence document |
| `POST /evidence/check-expiry` | Run the evidence freshness check |
| `GET /obligations/{id}/evidence-candidates` | Inspect retrieved evidence for an obligation |
| `POST /obligations/{id}/assess` | Run compliance assessment |
| `GET /obligations/{id}/history` | Full state-transition timeline for an obligation |
| `GET /review/pending` | Pending human-approval queue |
| `PUT /remediation/{proposal_id}/edit` | Edit a remediation proposal before approving |
| `POST /review/{transition_id}/approve` | Approve a pending transition |
| `POST /review/{transition_id}/reject` | Reject a pending transition |
| `POST /review/reassess-flagged` | Re-run assessment on all `RE_EVALUATION_REQUIRED` records |

---

## Evaluation Results

From `evaluation_report.md`, comparing the proposed architecture against naive baselines with sample-size qualified metrics across benchmark fixtures:

| Domain | Metric | Proposed Architecture | Baseline |
|---|---|---|---|
| Change Detection | Deadline change accuracy | **100.0% on 4 deadline change cases (N=4)** | 25.0% on 4 cases (N=4) |
| Change Detection | Overall accuracy | **100.0% on our 28-case benchmark suite (N=28)** | 50.0% on 28 cases (N=28) |
| Compliance Assessment | False positive rate | **0.0% on 32 benchmark cases (N=32)** | 18.5% on 32 cases (N=32) |
| Obligation Extraction | Strength vs. severity separation | **100.0% on 32 clause cases (N=32)** | 0.0% on 32 cases (N=32) |
| Human Workload | Auto-applied ratio | **39.5% on 38 review events (N=38)** | 0.0% on 38 events (N=38) |

The deadline-change cases (textually similar but substantively major changes — e.g. "delete within 30
days" → "delete within 3 days", "14 days" → "48 hours") provide clear evidence for why change detection needs the LLM
verification step rather than embedding similarity alone: the baseline achieves only 25.0% on N=4.



---

## Related Work / Research Gap

Grounded in a literature review spanning legal-text NLP, RAG-based legal QA, compliance gap
analysis, and multi-agent governance systems. The consistent pattern across reviewed systems:
each automates a single stage — extraction, retrieval-based QA, or point-in-time gap detection —
independently. None maintains a persistent compliance state that survives regulatory change or
evidence expiry, and none gates status changes through an auditable, human-approved remediation
loop. This project closes that gap.
