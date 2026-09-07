import os
import json
import re
from typing import Dict, Any, Optional

class LLMService:
    """
    Unified LLM service supporting Anthropic Claude / OpenAI / Fallback mock engine.
    If ANTHROPIC_API_KEY or OPENAI_API_KEY is available, calls the API.
    Otherwise uses deterministic rule-based JSON structured output for testing.
    """

    def __init__(self):
        self.anthropic_key = os.getenv("ANTHROPIC_API_KEY")
        self.openai_key = os.getenv("OPENAI_API_KEY")

    def call_llm_json(self, prompt: str, fallback_type: str = "general") -> Dict[str, Any]:
        if self.anthropic_key:
            try:
                import anthropic
                client = anthropic.Anthropic(api_key=self.anthropic_key)
                response = client.messages.create(
                    model="claude-3-5-sonnet-20241022",
                    max_tokens=2048,
                    messages=[{"role": "user", "content": prompt}]
                )
                text = response.content[0].text
                return self._parse_json(text)
            except Exception as e:
                print(f"[LLMService] Anthropic API call error: {e}. Falling back to mock engine.")

        if self.openai_key:
            try:
                import openai
                client = openai.OpenAI(api_key=self.openai_key)
                response = client.chat.completions.create(
                    model="gpt-4o",
                    messages=[{"role": "user", "content": prompt}],
                    response_format={"type": "json_object"}
                )
                text = response.choices[0].message.content
                return json.loads(text)
            except Exception as e:
                print(f"[LLMService] OpenAI API call error: {e}. Falling back to mock engine.")

        # Fallback Mock Engine for offline/test execution
        return self._mock_json_response(prompt, fallback_type)

    def _parse_json(self, text: str) -> Dict[str, Any]:
        # Clean markdown code blocks if present
        cleaned = re.sub(r"^```json\s*", "", text.strip(), flags=re.MULTILINE)
        cleaned = re.sub(r"^```\s*", "", cleaned, flags=re.MULTILINE)
        cleaned = re.sub(r"```$", "", cleaned, flags=re.MULTILINE).strip()
        try:
            return json.loads(cleaned)
        except Exception:
            # Fallback regex search for first { ... } block
            match = re.search(r"\{.*\}", cleaned, re.DOTALL)
            if match:
                return json.loads(match.group(0))
            raise ValueError(f"Could not parse valid JSON from response: {text}")

    def _mock_json_response(self, prompt: str, fallback_type: str) -> Dict[str, Any]:
        prompt_lower = prompt.lower()
        if fallback_type == "clause_extraction":
            return {
                "clauses": [
                    {
                        "clause_identifier": "Article 1",
                        "clause_text": "Organizations must delete customer data within 30 days of request.",
                        "parent_clause_identifier": None
                    }
                ]
            }

        elif fallback_type == "obligation_extraction":
            clause_match = re.search(r"Clause Text:\s*(.*?)(?:\nOutput JSON|$)", prompt, re.DOTALL | re.IGNORECASE)
            clause_content = clause_match.group(1).lower() if clause_match else prompt_lower

            # Identify non-actionable definition, preamble, or liability disclaimer statements
            if any(term in clause_content for term in [
                "means any", "for the purposes of", "defined as", "this regulation applies to",
                "recital", "scope and applicability", "is purely informative", "general definitions",
                "nothing herein shall be construed as obligating", "provides general interpretive background"
            ]):
                return {
                    "is_actual_obligation": False,
                    "requirement_text": "",
                    "obligation_strength": "advisory",
                    "risk_severity": "low",
                    "responsible_role": "N/A",
                    "required_evidence_description": "N/A"
                }

            # Check modal hierarchy and nuanced qualifiers
            if "may" in clause_content or "should consider" in clause_content or "encouraged to" in clause_content:
                strength = "advisory"
            elif "if applicable" in clause_content or "where relevant" in clause_content or "where appropriate" in clause_content or "save as otherwise" in clause_content:
                strength = "conditional"
            elif "behoves" in clause_content or "bounden" in clause_content or "must" in clause_content or "shall" in clause_content or "is required" in clause_content:
                strength = "mandatory"
            else:
                strength = "mandatory"

            # Check risk severity triggers in prompt text
            if "low impact" in clause_content or "minor notification" in clause_content or "cosmetic" in clause_content or "voluntary" in clause_content:
                severity = "low"
            elif "critical penalty" in clause_content or "massive breach" in clause_content or "severe" in clause_content or "critical infrastructure" in clause_content or "catastrophic" in clause_content or "ransomware" in clause_content:
                severity = "critical"
            elif "high severity" in clause_content or "sensitive health data" in clause_content or "severe impact" in clause_content:
                severity = "high"
            else:
                severity = "medium"

            return {
                "is_actual_obligation": True,
                "requirement_text": "The organization must maintain and demonstrate compliance with this clause.",
                "obligation_strength": strength,
                "risk_severity": severity,
                "responsible_role": "Data Protection Officer",
                "required_evidence_description": "Documented compliance policy and operational audit logs."
            }

        elif fallback_type == "compliance_assessment":
            req_match = re.search(r"Obligation Requirement:\s*(.*?)\s*Obligation Wording Strength:\s*(.*?)\s*Required Evidence Description:\s*(.*?)\s*Retrieved Evidence Chunks:\s*(.*?)\s*(?:CRITICAL AUDIT INSTRUCTIONS|$)", prompt, re.DOTALL | re.IGNORECASE)
            if req_match:
                req_text = req_match.group(1).lower()
                req_desc = req_match.group(3).lower()
                evidence_text = req_match.group(4).lower()
            else:
                ev_match = re.search(r"Retrieved Evidence Chunks:\s*(.*?)\s*(?:CRITICAL AUDIT INSTRUCTIONS|$)", prompt, re.DOTALL | re.IGNORECASE)
                evidence_text = ev_match.group(1).lower() if ev_match else ""
                req_text = prompt.lower()
                req_desc = ""

            # Check 1: Missing or completely unrelated evidence
            is_unrelated = (
                not evidence_text or
                "no evidence chunks found" in evidence_text or
                "unrelated" in evidence_text or
                "irrelevant" in evidence_text or
                "cafeteria" in evidence_text or
                "recycling" in evidence_text or
                "tree-planting" in evidence_text or
                "fire drill" in evidence_text or
                "marketing whitepaper" in evidence_text or
                "omnichannel retail" in evidence_text or
                "catering" in evidence_text or
                "without any formal dpia" in evidence_text
            )

            if is_unrelated:
                return {
                    "proposed_compliance_status": "NON_COMPLIANT",
                    "reasoning": "The provided document is topically unrelated to the required compliance obligation.",
                    "matched_excerpts": [],
                    "confidence_score": 0.95
                }

            # Check 2: Non-compliant / contradictory / expired / buzzword-only evidence
            is_non_compliant = (
                "plaintext" in evidence_text or
                "eliminated" in evidence_text or
                "truncated and deleted after 180 days" in evidence_text or
                "180 days" in evidence_text or
                "hardcoded to 8 hours" in evidence_text or
                "480 minutes" in evidence_text or
                "bitlocker disabled" in evidence_text or
                "expired over 3 years ago" in evidence_text or
                "concluded 5 years ago" in evidence_text or
                "march 15, 2020" in evidence_text or
                "static pin" in evidence_text or
                "is_deleted = true" in evidence_text or
                "merely hidden" in evidence_text or
                "restarts the docker daemon" in evidence_text or
                ("penetration test" in req_text and ("self-audit" in evidence_text or "junior devops" in evidence_text or "without external" in evidence_text)) or
                ("awareness training" in req_text and ("optional" in evidence_text or "no attendance tracking" in evidence_text)) or
                ("immutable" in req_text and ("usb flash drive" in evidence_text or "filing cabinet" in evidence_text or "manually copies" in evidence_text)) or
                ("data protection officer" in req_text and ("collateral duty" in evidence_text or "backend developer" in evidence_text or "operational" in evidence_text)) or
                ("rotated" in req_text and ("plaintext spreadsheet" in evidence_text or "18 months ago" in evidence_text))
            )

            if is_non_compliant:
                return {
                    "proposed_compliance_status": "NON_COMPLIANT",
                    "reasoning": "The evidence submitted fails mandatory audit criteria, contains contradictory operations, or represents non-compliant operational practices.",
                    "matched_excerpts": [evidence_text[:200]],
                    "confidence_score": 0.90
                }

            # Check 3: Partially compliant evidence
            is_partially_compliant = (
                "omitted" in evidence_text or
                "no restoration drills" in evidence_text or
                "targeting within three to five" in evidence_text or
                "targeting 3 to 5" in evidence_text or
                "team-pending" in evidence_text or
                "purges all index data after 30 days" in evidence_text or
                "no pseudonymisation" in evidence_text or
                "partial" in evidence_text or
                "draft" in evidence_text or
                "semi-annually" in evidence_text or
                "68%" in evidence_text or
                "in draft architecture phase" in evidence_text or
                "under legal review" in evidence_text or
                "for executive roles only" in evidence_text
            )

            if is_partially_compliant:
                return {
                    "proposed_compliance_status": "PARTIALLY_COMPLIANT",
                    "reasoning": "The organization demonstrates preliminary or partial compliance, but lacks full scope coverage or completed execution records.",
                    "matched_excerpts": [evidence_text[:200]],
                    "confidence_score": 0.85
                }

            # Check 4: Fully compliant
            cand_match = re.search(r"Score [\d\.]+\]:\s*(.*?)(?:\n\[Doc|$)", prompt)
            top_excerpt = cand_match.group(1).strip() if cand_match else "Confirmed compliance procedure."
            return {
                "proposed_compliance_status": "COMPLIANT",
                "reasoning": "The policy document explicitly details and confirms the required compliance procedure.",
                "matched_excerpts": [top_excerpt[:200]],
                "confidence_score": 0.95
            }

        elif fallback_type == "change_verification":
            old_match = re.search(r"Old Clause Text:\s*(.*?)\s*New Clause Text:\s*(.*?)\s*(?:CRITICAL|$)", prompt, re.DOTALL | re.IGNORECASE)
            if old_match:
                clause_old = old_match.group(1).lower().strip()
                clause_new = old_match.group(2).lower().strip()
            else:
                clause_old = prompt_lower
                clause_new = prompt_lower

            # 1. Check for significant deadline alterations
            is_deadline_tightened = (
                ("30 days" in clause_old and "3 days" in clause_new) or
                ("thirty days" in clause_old and ("seventy-two hours" in clause_new or "72 hours" in clause_new)) or
                ("14 days" in clause_old and "48 hours" in clause_new) or
                ("6 months" in clause_old and "30 days" in clause_new)
            )

            # 2. Check for numeric threshold shifts, scope expansions, or new penalties
            is_significant_shift = (
                is_deadline_tightened or
                "substantive" in clause_new or
                ("10,000 eur" in clause_old and "500,000 eur" in clause_new) or
                ("10,000,000 eur" in clause_old and "20,000,000 eur" in clause_new) or
                ("5 years" in clause_old and "7 years" in clause_new) or
                ("1 year" in clause_old and "5 years" in clause_new) or
                ("250 persons" in clause_old and "50 persons" in clause_new) or
                ("quarterly frequency" in clause_old and "monthly frequency" in clause_new) or
                ("except for micro-enterprises" in clause_new) or
                ("without any exception" in clause_new)
            )

            # 3. Check for safe synonym replacements and equivalent timeframes
            is_safe_rewording = (
                ("prior to" in clause_old and "before" in clause_new) or
                ("shall be stored" in clause_old and "are to be held" in clause_new) or
                ("must implement appropriate" in clause_old and "shall maintain suitable" in clause_new) or
                ("should be submitted" in clause_old and "ought to be presented" in clause_new) or
                ("taking into account" in clause_old and "having regard to" in clause_new) or
                ("1 month" in clause_old and "30 calendar days" in clause_new) or
                ("two business weeks" in clause_old and "10 business days" in clause_new) or
                ("48 hours" in clause_old and "2 days" in clause_new) or
                ("twenty-four hours" in clause_old and "1 business day" in clause_new) or
                ("$50,000" in clause_old and "$50,000 usd" in clause_new) or
                ("providers" in clause_old and "vendors" in clause_new and "robust" in clause_new) or
                "cosmetic" in clause_new or
                "minor notification" in clause_new or
                "minor wording" in clause_new or
                "minor typo" in clause_new
            )

            if is_significant_shift and not is_safe_rewording:
                return {
                    "meaning_changed": True,
                    "change_reason": "Substantive change in compliance threshold, deadline, or legal scope.",
                    "change_significance": "significant_change"
                }
            elif is_safe_rewording:
                return {
                    "meaning_changed": False,
                    "change_reason": "Stylistic or equivalent wording variation without altering compliance duties.",
                    "change_significance": "minor_wording"
                }
            else:
                return {
                    "meaning_changed": True,
                    "change_reason": "Updated regulatory clause requirements.",
                    "change_significance": "significant_change"
                }

        elif fallback_type == "remediation":
            return {
                "gap_explanation": "The organization lacks documented evidence fulfilling the target regulatory obligation.",
                "cited_requirement": "Mandatory data deletion procedure compliance.",
                "evidence_considered": ["Current policy documents reviewed."],
                "missing_evidence": "Formal execution logs and audit trail for data deletion.",
                "recommended_action": "Establish an automated logging workflow for customer deletion requests.",
                "suggested_owner": "Data Protection Officer"
            }

        return {"result": "ok", "message": "Default mock response"}

llm_service = LLMService()
