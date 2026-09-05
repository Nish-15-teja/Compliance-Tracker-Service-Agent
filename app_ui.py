import streamlit as st
import requests
import json
import os
from datetime import datetime
import pandas as pd

API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000")

st.set_page_config(
    page_title="Compliance Tracker — Service Agent",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom Styling
st.markdown("""
<style>
    .main-title {
        font-size: 2.2rem;
        font-weight: 700;
        color: #1E293B;
        margin-bottom: 0.2rem;
    }
    .sub-title {
        font-size: 1.05rem;
        color: #64748B;
        margin-bottom: 1.5rem;
    }
    .metric-card {
        background: #F8FAFC;
        border: 1px solid #E2E8F0;
        border-radius: 8px;
        padding: 12px 16px;
        text-align: center;
    }
    .stButton>button {
        border-radius: 6px;
        font-weight: 600;
    }
</style>
""", unsafe_allow_html=True)

st.markdown('<div class="main-title">🛡️ Compliance Tracker — Service Agent</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-title">Autonomous Regulatory Compliance, Change Impact Tracking & Human-in-the-Loop Remediation Platform</div>', unsafe_allow_html=True)

# Helper function to fetch regulations
def get_regulations():
    try:
        res = requests.get(f"{API_BASE_URL}/regulations", timeout=10)
        if res.status_code == 200:
            return res.json()
    except Exception:
        pass
    return []

# Helper function to fetch obligations with optional regulation filter
def get_obligations(regulation_id=None):
    try:
        url = f"{API_BASE_URL}/obligations"
        if regulation_id is not None:
            url += f"?regulation_id={regulation_id}"
        res = requests.get(url, timeout=10)
        if res.status_code == 200:
            return res.json()
    except Exception:
        pass
    return []

tabs = st.tabs([
    "📑 Regulation Upload & Explorer",
    "📁 Evidence Upload & Index",
    "📊 Obligation Dashboard",
    "⚖️ Review Queue",
    "🔄 Regulation Version Compare"
])

# ==============================================================================
# TAB 1: Regulation Upload & Explorer
# ==============================================================================
with tabs[0]:
    st.header("📑 Upload & Inspect Regulation Documents")
    
    col_up, col_view = st.columns([1, 1], gap="large")
    
    with col_up:
        st.subheader("1. Upload New Regulation")
        reg_title = st.text_input("Regulation Title", value="EU GDPR Regulation", help="e.g. EU GDPR Regulation, HIPAA, PCI-DSS")
        version_label = st.text_input("Version Label", value="v1.0", help="e.g. v1.0, 2026-Rev1")
        uploaded_file = st.file_uploader("Upload Document (PDF, DOCX, TXT)", type=["pdf", "docx", "txt"])
        
        upload_btn = st.button("🚀 Upload & Process Regulation", type="primary", use_container_width=True)
        
        if upload_btn:
            if not uploaded_file:
                st.warning("⚠️ Please select a regulation file to upload.")
            else:
                with st.status("🔄 Processing Regulation Document...", expanded=True) as status_box:
                    # Step 1: Upload and Stage Raw Pages
                    status_box.write("📄 **Step 1/3**: Uploading file and staging raw page blocks...")
                    file_mime = uploaded_file.type or "application/octet-stream"
                    files = {"file": (uploaded_file.name, uploaded_file.getvalue(), file_mime)}
                    data = {"title": reg_title, "version_label": version_label}
                    
                    try:
                        upload_res = requests.post(f"{API_BASE_URL}/regulations/upload", data=data, files=files, timeout=60)
                        if upload_res.status_code != 201:
                            status_box.update(label="❌ Document upload failed", state="error")
                            st.error(f"Upload failed: {upload_res.text}")
                        else:
                            upload_info = upload_res.json()
                            reg_id = upload_info["regulation_id"]
                            st.session_state["selected_reg_id"] = reg_id
                            status_box.write(f"✅ Document staged successfully! Regulation ID: **#{reg_id}** ({upload_info.get('page_count', 0)} pages parsed)")
                            
                            # Step 2: Extract Clauses
                            status_box.write("🔍 **Step 2/3**: Performing clause boundary detection & extraction...")
                            clause_res = requests.post(f"{API_BASE_URL}/regulations/{reg_id}/extract-clauses", timeout=60)
                            if clause_res.status_code == 200:
                                clause_data = clause_res.json()
                                c_count = clause_data.get("clause_count", 0)
                                status_box.write(f"✅ Clause extraction complete! **{c_count}** clauses identified.")
                            else:
                                status_box.write(f"⚠️ Clause extraction warning: {clause_res.text}")
                                
                            # Step 3: Extract Obligations
                            status_box.write("⚖️ **Step 3/3**: Extracting atomic obligations, risk severities & roles...")
                            ob_res = requests.post(f"{API_BASE_URL}/regulations/{reg_id}/extract-obligations", timeout=90)
                            if ob_res.status_code == 200:
                                ob_data = ob_res.json()
                                o_count = ob_data.get("obligations_created", 0)
                                status_box.write(f"✅ Obligation extraction complete! **{o_count}** obligations created and indexed.")
                                status_box.update(label="🎉 Regulation Processing Complete!", state="complete", expanded=False)
                                st.success(f"Successfully processed **{reg_title} ({version_label})** — {c_count} clauses, {o_count} obligations.")
                            else:
                                status_box.update(label="⚠️ Extraction completed with warnings", state="complete")
                                st.warning(f"Obligation extraction note: {ob_res.text}")
                    except Exception as e:
                        status_box.update(label="❌ Request error", state="error")
                        st.error(f"Error connecting to backend: {e}")

    with col_view:
        st.subheader("2. Staged Regulations & Extracted Data")
        regulations_list = get_regulations()
        
        if not regulations_list:
            st.info("No regulations found in database yet. Use the upload form on the left to upload a regulation.")
        else:
            reg_options = {f"#{r['id']} — {r['title']} ({r['version_label']})": r['id'] for r in regulations_list}
            
            # Default selection
            default_index = 0
            if "selected_reg_id" in st.session_state:
                for idx, (label, rid) in enumerate(reg_options.items()):
                    if rid == st.session_state["selected_reg_id"]:
                        default_index = idx
                        break
                        
            selected_label = st.selectbox("Select Regulation to Inspect", options=list(reg_options.keys()), index=default_index)
            selected_id = reg_options[selected_label]
            
            selected_reg = next((r for r in regulations_list if r['id'] == selected_id), None)
            if selected_reg:
                m1, m2, m3, m4 = st.columns(4)
                with m1:
                    st.metric("Reg ID", f"#{selected_reg['id']}")
                with m2:
                    st.metric("Pages", selected_reg.get('page_count', 0))
                with m3:
                    st.metric("Clauses", selected_reg.get('clause_count', 0))
                with m4:
                    st.metric("Obligations", selected_reg.get('obligation_count', 0))
                    
                # Fetch clauses for selected regulation
                try:
                    c_resp = requests.get(f"{API_BASE_URL}/regulations/{selected_id}/clauses", timeout=10)
                    if c_resp.status_code == 200:
                        clauses = c_resp.json()
                        with st.expander(f"📋 View Extracted Clauses ({len(clauses)})", expanded=True):
                            if clauses:
                                clause_rows = []
                                for c in clauses:
                                    clause_rows.append({
                                        "ID": c["id"],
                                        "Clause Identifier": c["clause_identifier"],
                                        "Page": c["source_page"],
                                        "Parent": c["parent_clause_identifier"] or "-",
                                        "Obligations": c["obligation_count"],
                                        "Snippet": (c["clause_text"][:120] + "...") if len(c["clause_text"]) > 120 else c["clause_text"]
                                    })
                                st.dataframe(pd.DataFrame(clause_rows), use_container_width=True, hide_index=True)
                            else:
                                st.write("No clauses extracted for this regulation.")
                except Exception as e:
                    st.error(f"Error fetching clauses: {e}")

# ==============================================================================
# TAB 2: Evidence Upload & Vector Index
# ==============================================================================
with tabs[1]:
    st.header("📁 Upload & Index Evidence Documents")
    st.markdown("Upload internal compliance policies, audit logs, SOPs, and security certifications to vectorize and link against regulatory obligations.")
    
    col_ev1, col_ev2 = st.columns(2)
    with col_ev1:
        st.subheader("1. Upload Evidence File")
        org_name = st.text_input("Organization Name", value="Acme Corp")
        ev_title = st.text_input("Document Title", value="Data Deletion Procedure and Verification Log")
        ev_type = st.selectbox("Evidence Type", ["policy", "procedure", "log", "certificate", "SOC2 report", "audit_log"])
        expiry_date = st.date_input("Expiry Date (Optional)")
        ev_file = st.file_uploader("Upload Evidence Document (PDF, DOCX, TXT)", type=["pdf", "docx", "txt"], key="ev_upload_input")
        
        if st.button("📤 Upload & Index Evidence", type="primary", use_container_width=True):
            if not ev_file:
                st.warning("Please select an evidence file.")
            else:
                with st.spinner("Uploading, chunking, and indexing evidence document into vector search..."):
                    file_mime = ev_file.type or "application/octet-stream"
                    files = {"file": (ev_file.name, ev_file.getvalue(), file_mime)}
                    data = {
                        "org_name": org_name,
                        "title": ev_title,
                        "evidence_type": ev_type,
                        "expiry_date": expiry_date.strftime("%Y-%m-%d") if expiry_date else None
                    }
                    try:
                        res = requests.post(f"{API_BASE_URL}/evidence/upload", data=data, files=files, timeout=60)
                        if res.status_code == 201:
                            ev_data = res.json()
                            st.success(f"✅ Evidence uploaded and indexed successfully! Document ID: **#{ev_data['evidence_document_id']}**")
                            st.json(ev_data)
                        else:
                            st.error(f"Upload failed: {res.text}")
                    except Exception as e:
                        st.error(f"Error connecting to backend: {e}")

    with col_ev2:
        st.subheader("2. Evidence Expiry & Health Monitoring")
        warning_days = st.slider("Expiry Warning Window (Days)", min_value=7, max_value=90, value=30)
        if st.button("🔍 Check Evidence Expiry & Trigger Impact"):
            with st.spinner("Scanning evidence documents for expiration..."):
                try:
                    exp_res = requests.post(f"{API_BASE_URL}/evidence/check-expiry?warning_days={warning_days}", timeout=20)
                    if exp_res.status_code == 200:
                        st.success("Evidence expiry check completed!")
                        st.json(exp_res.json())
                    else:
                        st.error(f"Error: {exp_res.text}")
                except Exception as e:
                    st.error(f"Connection error: {e}")

# ==============================================================================
# TAB 3: Obligation Dashboard
# ==============================================================================
with tabs[2]:
    st.header("📊 Obligation & Compliance Lifecycle Dashboard")
    st.markdown("Live tracking of obligations with **Three-Axis Independent State Representation** (`compliance_status`, `workflow_state`, `evidence_state`).")
    
    reg_list = get_regulations()
    
    # Top Control Bar: Regulation Selection & Refresh
    ctrl_col1, ctrl_col2 = st.columns([3, 1])
    with ctrl_col1:
        reg_filter_options = ["ALL — All Regulations"] + [f"#{r['id']} — {r['title']} ({r['version_label']}) [{r.get('obligation_count', 0)} obligations]" for r in reg_list]
        selected_reg_filter = st.selectbox("🎯 Filter by Regulation Source", options=reg_filter_options, index=1 if len(reg_list) > 0 else 0)
    with ctrl_col2:
        st.write("")
        st.write("")
        if st.button("🔄 Refresh Data", use_container_width=True):
            st.rerun()
            
    # Determine regulation ID filter
    active_reg_id = None
    if not selected_reg_filter.startswith("ALL"):
        active_reg_id = int(selected_reg_filter.split("—")[0].replace("#", "").strip())
        target_reg = next((r for r in reg_list if r['id'] == active_reg_id), None)
        if target_reg:
            st.caption(f"🎯 Filtered to: **{target_reg['title']} ({target_reg['version_label']})** — Total Obligations: **{target_reg.get('obligation_count', 0)}**")

    try:
        obligations_list = get_obligations(regulation_id=active_reg_id)
        if not obligations_list:
            st.info("No obligations found. Upload a regulation in Tab 1 to extract obligations.")
        else:
            # Metrics summary for the currently selected regulation
            total_obs = len(obligations_list)
            compliant_cnt = sum(1 for o in obligations_list if o['compliance_status'] == 'COMPLIANT')
            partial_cnt = sum(1 for o in obligations_list if o['compliance_status'] == 'PARTIALLY_COMPLIANT')
            non_comp_cnt = sum(1 for o in obligations_list if o['compliance_status'] == 'NON_COMPLIANT')
            missing_cnt = sum(1 for o in obligations_list if o['compliance_status'] == 'EVIDENCE_MISSING')
            uncheck_cnt = sum(1 for o in obligations_list if o['compliance_status'] == 'NOT_CHECKED')
            
            m1, m2, m3, m4, m5, m6 = st.columns(6)
            m1.metric("Total Obligations", total_obs)
            m2.metric("Compliant", compliant_cnt)
            m3.metric("Partial", partial_cnt)
            m4.metric("Non-Compliant", non_comp_cnt)
            m5.metric("Evidence Missing", missing_cnt)
            m6.metric("Not Checked", uncheck_cnt)
            
            st.divider()
            
            # Filters
            col_f1, col_f2, col_f3 = st.columns(3)
            with col_f1:
                status_filter = st.multiselect(
                    "Filter Compliance Status",
                    options=["ALL", "NOT_CHECKED", "COMPLIANT", "PARTIALLY_COMPLIANT", "NON_COMPLIANT", "EVIDENCE_MISSING"],
                    default=["ALL"]
                )
            with col_f2:
                workflow_filter = st.multiselect(
                    "Filter Workflow State",
                    options=["ALL", "ACTIVE", "RE_EVALUATION_REQUIRED", "PENDING_HUMAN_REVIEW", "REMEDIATION_IN_PROGRESS", "CLOSED"],
                    default=["ALL"]
                )
            with col_f3:
                evidence_filter = st.multiselect(
                    "Filter Evidence State",
                    options=["ALL", "VALID", "EXPIRING_SOON", "EXPIRED"],
                    default=["ALL"]
                )
                
            filtered_obs = []
            for ob in obligations_list:
                if "ALL" not in status_filter and ob["compliance_status"] not in status_filter:
                    continue
                if "ALL" not in workflow_filter and ob["workflow_state"] not in workflow_filter:
                    continue
                if "ALL" not in evidence_filter and ob["evidence_state"] not in evidence_filter:
                    continue
                filtered_obs.append(ob)
                
            st.write(f"Showing **{len(filtered_obs)}** matching obligations:")
            
            display_limit = st.selectbox("Display Limit", [10, 25, 50, 100, len(filtered_obs)], index=0)
            displayed_obs = filtered_obs[:display_limit]
            
            status_colors = {
                "COMPLIANT": "green",
                "PARTIALLY_COMPLIANT": "orange",
                "NON_COMPLIANT": "red",
                "EVIDENCE_MISSING": "red",
                "NOT_CHECKED": "gray"
            }
            
            for ob in displayed_obs:
                with st.container(border=True):
                    head_col, btn_col = st.columns([4, 1])
                    with head_col:
                        title_str = f"🔍 **{ob['clause_identifier']}**"
                        if ob.get('source_page'):
                            title_str += f" *(Page {ob['source_page']} — {ob.get('regulation_title', 'Regulation')} {ob.get('regulation_version', '')} — Role: {ob.get('responsible_role', 'DPO')})*"
                        st.markdown(title_str)
                    with btn_col:
                        if st.button(f"⚡ Assess #{ob['id']}", key=f"btn_assess_{ob['id']}", use_container_width=True):
                            with st.spinner("Retrieving evidence & auditing obligation..."):
                                assess_res = requests.post(f"{API_BASE_URL}/obligations/{ob['id']}/assess?record_state=true")
                                if assess_res.status_code == 200:
                                    res_json = assess_res.json()
                                    prop = res_json['assessment_result']['proposed_compliance_status']
                                    reasoning = res_json['assessment_result'].get('reasoning', '')
                                    conf = res_json['assessment_result'].get('confidence_score', 0.0)
                                    top_doc = res_json['assessment_result'].get('top_evidence_document_id')
                                    top_score = res_json['assessment_result'].get('top_similarity_score', 0.0)
                                    excerpts = res_json['assessment_result'].get('matched_excerpts', [])
                                    st.session_state[f"last_eval_{ob['id']}"] = {
                                        "status": prop,
                                        "reasoning": reasoning,
                                        "confidence": conf,
                                        "top_doc": top_doc,
                                        "top_score": top_score,
                                        "excerpts": excerpts
                                    }
                                    st.rerun()
                                else:
                                    st.error("Assessment failed.")
                                    
                    st.write(f"**Requirement:** {ob['requirement_text']}")
                    st.write(f"**Required Evidence:** {ob['required_evidence_description']}")
                    
                    c1, c2, c3, c4 = st.columns(4)
                    c1.markdown(f"**Strength:** `{ob['obligation_strength'].upper()}`")
                    c2.markdown(f"**Risk Severity:** `{ob['risk_severity'].upper()}`")
                    color = status_colors.get(ob["compliance_status"], "gray")
                    c3.markdown(f"**Compliance Status:** :{color}[**{ob['compliance_status']}**]")
                    c4.markdown(f"**Workflow / Evidence:** `{ob['workflow_state']}` / `{ob['evidence_state']}`")

                    with st.expander(f"📜 Audit History Timeline — Obligation #{ob['id']}"):
                        try:
                            h_res = requests.get(f"{API_BASE_URL}/obligations/{ob['id']}/history", timeout=5)
                            if h_res.status_code == 200:
                                h_list = h_res.json().get("history", [])
                                if not h_list:
                                    st.caption("No state transitions recorded yet.")
                                else:
                                    for h_item in h_list:
                                        ts = h_item.get('created_at', '')[:19].replace('T', ' ')
                                        st.markdown(f"**{ts}** — `{h_item['field_changed']}`: `{h_item['old_value']}` ➔ `{h_item['new_value']}` *(Trigger: `{h_item['trigger_type']}`, Status: `{h_item['approval_status']}`)*")
                                        if h_item.get('reasoning'):
                                            st.caption(f"Reason: {h_item['reasoning']}")
                            else:
                                st.caption("Could not load history.")
                        except Exception as e:
                            st.caption(f"History query error: {e}")
                    
                    if f"last_eval_{ob['id']}" in st.session_state:
                        last_ev = st.session_state[f"last_eval_{ob['id']}"]
                        with st.expander("📋 Latest Assessment Output & Evidence Retrieval", expanded=True):
                            st.markdown(f"**Proposed Status:** `{last_ev['status']}` | **Confidence Score:** `{last_ev['confidence']}` | **Top Evidence Doc:** `#{last_ev['top_doc']}` (Similarity Score: `{last_ev['top_score']}`)")
                            st.write(f"**Auditor Reasoning:** {last_ev['reasoning']}")
                            if last_ev.get("excerpts"):
                                st.markdown(f"**Matched Evidence Excerpt:** *\"{last_ev['excerpts'][0]}\"*")
                            if last_ev['status'] in ['EVIDENCE_MISSING', 'NON_COMPLIANT']:
                                st.warning("⚠️ Remediation generated. Human approval queued in **Tab 4 (⚖️ Review Queue)**.")
                            elif last_ev['status'] == 'COMPLIANT':
                                st.success("✅ Requirement verified against uploaded evidence.")
    except Exception as e:
        st.error(f"Error loading obligations: {e}")

# ==============================================================================
# TAB 4: Review Queue
# ==============================================================================
with tabs[3]:
    st.header("⚖️ Human-in-the-Loop Review Queue")
    st.markdown("Review agent-generated compliance state transitions and action plans requiring human sign-off.")
    
    # Entity Relationship Guide
    with st.expander("ℹ️ Understanding System Identifiers & Review Workflow Hierarchy", expanded=False):
        st.markdown("""
        - 📜 **Regulation**: The statutory framework (e.g. *EU GDPR Regulation v1.0*).
        - 🔍 **Clause / Article**: A specific section in the regulation (e.g. *Article 5(1)(e)* on Page 36).
        - ⚡ **Obligation ID (`#ID`)**: An atomic, actionable compliance requirement extracted from a clause (e.g. *#1227*).
        - 🗂️ **Compliance Record (`#ID`)**: The live, persistent compliance tracking state record tied 1:1 to that obligation (e.g. *#1*).
        - ⚖️ **State Transition (`#ID`)**: An immutable audit record of a proposed state change awaiting human sign-off (e.g. *#18*).
        """)
    
    if st.button("🔄 Refresh Review Queue"):
        st.rerun()
        
    try:
        rev_res = requests.get(f"{API_BASE_URL}/review/pending", timeout=10)
        if rev_res.status_code == 200:
            review_data = rev_res.json()
            st.write(f"Total Pending Reviews: **{review_data.get('pending_count', 0)}**")
            
            items = review_data.get("items", [])
            if not items:
                st.success("✅ No pending reviews in queue! All compliance transitions are up to date.")
            else:
                for item in items:
                    with st.container(border=True):
                        st.subheader(f"⚖️ Transition #{item['transition_id']}")
                        st.caption(f"Linked: **Compliance Record #{item['compliance_record_id']}** ➔ **Obligation #{item.get('obligation_id', 'N/A')}** ➔ **{item.get('clause_identifier', 'Article')}**")
                        st.divider()
                        
                        col_r1, col_r2 = st.columns(2)
                        with col_r1:
                            st.markdown(f"**Regulation:** `{item.get('regulation_title', 'EU GDPR Regulation')}`")
                            st.markdown(f"**Obligation ID:** `#{item.get('obligation_id', 'N/A')}`")
                        with col_r2:
                            st.markdown(f"**Version:** `{item.get('regulation_version', 'v1.0')}`")
                            st.markdown(f"**Article / Clause:** `{item.get('clause_identifier', 'Article')}` *(Page {item.get('source_page', 'N/A')})*")
                            
                        st.markdown(f"**📋 Requirement:**\n{item.get('requirement_text', 'N/A')}")
                        st.markdown(f"**📂 Required Evidence:**\n{item.get('required_evidence_description', 'N/A')}")
                        st.markdown(f"**📄 Evidence Assessed:**\n`{item.get('evidence_assessed', 'No matching evidence chunks found')}`")
                        
                        status_colors = {
                            "COMPLIANT": "green",
                            "PARTIALLY_COMPLIANT": "orange",
                            "NON_COMPLIANT": "red",
                            "EVIDENCE_MISSING": "red",
                            "NOT_CHECKED": "gray"
                        }
                        old_val = item.get('old_value', 'NOT_CHECKED')
                        new_val = item.get('proposed_new_value', 'EVIDENCE_MISSING')
                        old_color = status_colors.get(old_val, "gray")
                        new_color = status_colors.get(new_val, "red")
                        
                        col_s1, col_s2, col_s3 = st.columns(3)
                        col_s1.markdown(f"**Current Status:** :{old_color}[**{old_val}**]")
                        col_s2.markdown(f"**Proposed Status:** :{new_color}[**{new_val}**]")
                        col_s3.markdown(f"**Confidence Score:** `{item.get('confidence_score', 0.0)}` *(Risk: {item.get('risk_severity', 'medium').upper()})*")
                        
                        st.info(f"**🔍 Auditor Reasoning:** {item.get('reasoning', 'No reasoning provided.')}")
                        
                        if item.get("remediation_proposal"):
                            rem = item["remediation_proposal"]
                            with st.expander(f"🛠️ Remediation Proposal #{rem['id']} (Review & Edit)", expanded=True):
                                st.caption(f"**Gap Explanation:** {rem.get('gap_explanation', 'Compliance gap identified.')}")
                                
                                edit_action = st.text_area(f"Recommended Action #{item['transition_id']}", value=rem.get("recommended_action", ""), key=f"act_{item['transition_id']}")
                                
                                col_e1, col_e2, col_e3 = st.columns(3)
                                with col_e1:
                                    edit_owner = st.text_input(f"Suggested Owner #{item['transition_id']}", value=rem.get("suggested_owner", ""), key=f"own_{item['transition_id']}")
                                with col_e2:
                                    default_date = None
                                    if rem.get("suggested_deadline"):
                                        try:
                                            default_date = datetime.fromisoformat(rem["suggested_deadline"]).date()
                                        except Exception:
                                            pass
                                    edit_deadline = st.date_input(f"Suggested Deadline #{item['transition_id']}", value=default_date, key=f"dead_{item['transition_id']}")
                                with col_e3:
                                    prio_opts = ["low", "medium", "high", "critical"]
                                    curr_prio = rem.get("priority", "medium").lower()
                                    prio_idx = prio_opts.index(curr_prio) if curr_prio in prio_opts else 1
                                    edit_priority = st.selectbox(f"Priority #{item['transition_id']}", prio_opts, index=prio_idx, key=f"prio_{item['transition_id']}")
                                    
                                if st.button(f"💾 Save Edits #{item['transition_id']}", key=f"save_btn_{item['transition_id']}", use_container_width=True):
                                    edit_payload = {
                                        "recommended_action": edit_action,
                                        "suggested_owner": edit_owner,
                                        "suggested_deadline": edit_deadline.strftime("%Y-%m-%d") if edit_deadline else None,
                                        "priority": edit_priority,
                                        "human_edit_notes": "Updated by reviewer in web console"
                                    }
                                    save_res = requests.put(f"{API_BASE_URL}/remediation/{rem['id']}/edit", json=edit_payload)
                                    if save_res.status_code == 200:
                                        st.success("Edits saved successfully.")
                                        st.rerun()
                                    else:
                                        st.error(f"Failed to save edits: {save_res.text}")
                            
                        b1, b2 = st.columns(2)
                        with b1:
                            if st.button(f"✅ Approve Transition #{item['transition_id']}", key=f"app_btn_{item['transition_id']}", use_container_width=True):
                                app_res = requests.post(f"{API_BASE_URL}/review/{item['transition_id']}/approve", json={"approved_by": "Compliance Officer", "resolution_confirmed": True})
                                if app_res.status_code == 200:
                                    st.success("Approved successfully!")
                                    st.rerun()
                        with b2:
                            if st.button(f"❌ Reject Transition #{item['transition_id']}", key=f"rej_btn_{item['transition_id']}", use_container_width=True):
                                rej_res = requests.post(f"{API_BASE_URL}/review/{item['transition_id']}/reject", json={"approved_by": "Compliance Officer"})
                                if rej_res.status_code == 200:
                                    st.info("Rejected.")
                                    st.rerun()

        else:
            st.error("Failed to fetch review queue.")
    except Exception as e:
        st.error(f"Error fetching review queue: {e}")

# ==============================================================================
# TAB 5: Regulation Compare
# ==============================================================================
with tabs[4]:
    st.header("🔄 Regulation Version Change Detection & Impact Propagation")
    st.markdown("Compare baseline regulation version with a newly uploaded version to perform 4-step change detection and automated impact propagation.")
    
    reg_list = get_regulations()
    if len(reg_list) < 2:
        st.info("Upload at least two versions of a regulation in Tab 1 to enable version comparison.")
    else:
        reg_dict = {f"#{r['id']} — {r['title']} ({r['version_label']})": r['id'] for r in reg_list}
        col_v1, col_v2 = st.columns(2)
        with col_v1:
            old_choice = st.selectbox("Old Regulation (Baseline)", options=list(reg_dict.keys()), index=min(1, len(reg_dict)-1))
            old_id = reg_dict[old_choice]
        with col_v2:
            new_choice = st.selectbox("New Regulation (Target)", options=list(reg_dict.keys()), index=0)
            new_id = reg_dict[new_choice]
            
        if st.button("🚀 Detect Changes & Propagate Impact", type="primary"):
            with st.spinner("Running 4-step change detection & propagating impact..."):
                try:
                    det_res = requests.post(f"{API_BASE_URL}/regulations/{new_id}/detect-changes?compare_to={old_id}", timeout=60)
                    if det_res.status_code == 200:
                        st.success("✅ 4-Step Change Detection Completed!")
                        st.json(det_res.json())
                        
                    prop_res = requests.post(f"{API_BASE_URL}/regulations/{new_id}/propagate-impact", timeout=60)
                    if prop_res.status_code == 200:
                        st.info("✅ Targeted Impact Propagation Completed!")
                        st.json(prop_res.json())
                except Exception as e:
                    st.error(f"Error during comparison: {e}")
