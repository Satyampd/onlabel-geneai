import json
import os
import re
import tempfile
from datetime import datetime
import streamlit as st
from google.genai import types

import config
import templates
import pipeline
import review
import source_view

st.set_page_config(
    page_title="OnLabel · KESIMPTA Patient Information",
    page_icon="🛡️",
    layout="wide",
)

st.markdown("""
<style>
/* Make Streamlit chat bubbles look cleaner */
.stChatMessage { border-radius: 12px; padding: 12px; margin-bottom: 12px; }
div[data-testid="stChatMessageContent"] { font-size: 1.05rem; }
/* Hide standard Streamlit header elements for a cleaner UI */
header[data-testid="stHeader"] { display: none; }
</style>
""", unsafe_allow_html=True)

PLACEHOLDER_RE = re.compile(r"\[[^\]]+\]")


def _atomic_write(path: str, write_fn):
    """Write to a temp file in the same directory, then os.replace it over `path`,
    so a crash or concurrent reader never sees a half-written file."""
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp_", suffix=os.path.basename(path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            write_fn(f)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


# Items cache keyed on the file's mtime. st.cache_resource returns the same object
# (no copy of the ~32 MB dict on every rerun); a plain global in the Streamlit main
# script would be reset on each rerun, so the resource cache is the module-level store.
@st.cache_resource(max_entries=1, show_spinner=False)
def _load_items_at(mtime: float):
    with open(config.ITEMS_JSON, "r", encoding="utf-8") as f:
        return json.load(f)


def load_all_items_data():
    if not os.path.exists(config.ITEMS_JSON):
        return {"items": [], "built_at": "", "build_seconds": 0}
    try:
        return _load_items_at(os.path.getmtime(config.ITEMS_JSON))
    except Exception as e:
        st.error(f"Error loading items.json: {e}")
        return {"items": [], "built_at": "", "build_seconds": 0}


def save_all_items_data(data):
    try:
        _atomic_write(config.ITEMS_JSON, lambda f: json.dump(data, f))
    finally:
        # Invalidate either way: on failure the in-memory edit is dropped and disk wins.
        _load_items_at.clear()


@st.cache_data
def render_pdf_page(doc_name: str, pdf_page: int, parts: tuple = (), snippet: bool = False) -> bytes:
    """Source page (or a crop around the passage) with the answer highlighted by code."""
    try:
        return source_view.render(doc_name, pdf_page, list(parts) or None, snippet=snippet)
    except Exception as e:
        print(f"Error rendering PDF page {pdf_page} of {doc_name}: {e}")
        return b""


def load_logs():
    if not os.path.exists(config.LOG_JSONL):
        return []
    logs = []
    try:
        with open(config.LOG_JSONL, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    logs.append(json.loads(line.strip()))
    except Exception as e:
        print(f"Error loading logs: {e}")
    return logs


def save_logs(logs):
    def _write(f):
        for entry in logs:
            f.write(json.dumps(entry) + "\n")
    _atomic_write(config.LOG_JSONL, _write)


# Sidebar
with st.sidebar:
    st.title("🛡️ OnLabel Control")
    reviewer_name = st.text_input("Your Name / Session", value="", key="reviewer_name").strip()
    show_why = st.toggle("Show decision details ('why' line)", value=True, key="show_why")

    if st.button("🔄 Refresh Data"):
        st.cache_data.clear()
        _load_items_at.clear()
        st.rerun()

    st.markdown("---")
    st.markdown("### 📋 Important Safety Info")
    if os.path.exists(config.SAFETY_PANEL_TXT):
        with open(config.SAFETY_PANEL_TXT, "r", encoding="utf-8") as f:
            safety_text = f.read()
        with st.expander("View Safety Panel", expanded=False):
            st.markdown(f"```text\n{safety_text}\n```")

# One-shot confirmation from the previous run (set right before st.rerun()).
_flash = st.session_state.pop("flash", None)
if _flash:
    st.toast(_flash)

# Main Page Tabs
tab_review, tab_chat, tab_insights = st.tabs(["📝 Review Screen", "💬 Live Chat", "📊 Insights & Reports"])

# ==============================================================================
# TAB 1: REVIEW
# ==============================================================================
with tab_review:
    items_data = load_all_items_data()
    all_items = items_data.get("items", [])

    pending_count = sum(1 for it in all_items if it.get("status") == "pending")
    approved_count = sum(1 for it in all_items if it.get("status") == "approved")
    rejected_count = sum(1 for it in all_items if it.get("status") == "rejected")

    c1, c2, c3, c4 = st.columns([1, 1, 1, 2])
    c1.metric("⏳ Pending Review", pending_count)
    c2.metric("✅ Approved", approved_count)
    c3.metric("❌ Rejected", rejected_count)
    c4.write(f"**Total items:** {len(all_items)} | **Build time:** {items_data.get('build_seconds', 0)}s")

    st.markdown("---")

    if not all_items:
        st.info("No items loaded. Please run `build_items.py` first to generate items.")
    else:
        # Pending first, then brochure (the primary approved material) before the Medication Guide
        sorted_items = sorted(
            all_items,
            key=lambda x: (
                0 if x.get("status") == "pending" else (1 if x.get("status") == "approved" else 2),
                0 if x.get("doc") == "brochure" else 1,
            ),
        )

        # Select item
        def make_label(it):
            v = it.get("judge", {}).get("verdict", "concern").upper()
            status_icon = "⏳" if it.get("status") == "pending" else ("✅" if it.get("status") == "approved" else "❌")
            return f"[{status_icon} {it.get('status', '').upper()}] [{v}] {it.get('id')}: {it.get('question')[:60]}"

        # Select by item id (not list position), so after a decision re-sorts the list
        # the same item stays selected and shows its new status.
        item_ids = [it.get("id") for it in sorted_items]
        items_by_id = {it.get("id"): it for it in sorted_items}
        item_labels = {it.get("id"): make_label(it) for it in sorted_items}
        prev_id = st.session_state.get("review_selected_id")
        sel_index = item_ids.index(prev_id) if prev_id in item_ids else 0
        selected_id = st.selectbox(
            "Select Item to Inspect & Review", item_ids, index=sel_index,
            format_func=lambda i: item_labels.get(i, str(i)),
        )
        st.session_state["review_selected_id"] = selected_id
        selected_item = items_by_id[selected_id]

        col_left, col_right = st.columns([3, 2])

        with col_left:
            st.subheader(f"Item: `{selected_item.get('id')}`")
            rv = selected_item.get("review") or {}
            if selected_item.get("status") in ("approved", "rejected") and rv:
                status_line = f"**Status:** {selected_item.get('status', '').upper()} · **Reviewer:** {rv.get('reviewer') or '—'}"
                if rv.get("reason_code"):
                    status_line += f" · **Reason code:** `{rv.get('reason_code')}`"
                if rv.get("ts"):
                    status_line += f" · {rv.get('ts')}"
                (st.success if selected_item.get("status") == "approved" else st.error)(status_line)
            else:
                st.markdown(f"**Status:** {selected_item.get('status', '').upper()}")
            st.markdown(f"**Document:** `{selected_item.get('doc')}` | **Topic:** `{selected_item.get('topic')}`")
            st.markdown(f"### ❓ Patient Question:\n**{selected_item.get('question')}**")

            with st.expander("Alternate Patient Paraphrases", expanded=True):
                for p in selected_item.get("paraphrases", []):
                    st.markdown(f"- *{p}*")

            st.markdown("### 💬 Verified Answer (Character-for-Character):")
            chk = selected_item.get("checks", {})
            jdg = selected_item.get("judge", {})
            answer_text = selected_item.get("answer", "")
            # Shown as plain text so line breaks, bullets and asterisks are not re-rendered.
            st.code(answer_text, language=None, wrap_lines=True)
            if chk.get("placeholder"):
                st.markdown(":red-background[:red[**Placeholder found**]]")
                found_ph = PLACEHOLDER_RE.findall(answer_text)
                if found_ph:
                    st.text("\n".join(found_ph))

            cite = selected_item.get("citation", {})
            st.markdown(f"**Citation:** `{cite.get('doc_title')}` · Section: *{cite.get('section')}* · PDF Page: {cite.get('pdf_page')} (Printed: {cite.get('printed_pages')})")

            # Large Evidence Panel
            st.markdown("### 🔍 Evidence & Quality Gate Panel")

            col_ev1, col_ev2 = st.columns(2)
            with col_ev1:
                if chk.get("found_in_source"):
                    st.success("✅ **Found Word-for-Word in Source**")
                else:
                    st.error("❌ **NOT Found in Source**")
                    if chk.get("not_found_parts"):
                        st.caption(f"Missing parts: {chk.get('not_found_parts')}")

                if chk.get("placeholder"):
                    st.warning("⚠️ **Contains Placeholder [brackets]**")
                else:
                    st.success("✅ **Clean (No Placeholders)**")

            with col_ev2:
                r_test = chk.get("retrieval_self_test", {})
                p_rate = f"{r_test.get('passed', 0)} / {r_test.get('total', 0)}"
                st.write(f"🎯 **Retrieval Self-Test:** {p_rate} paraphrases matched")
                if r_test.get("misses"):
                    with st.expander("Self-Test Misses"):
                        for m in r_test.get("misses"):
                            st.caption(f"'{m.get('paraphrase')}' -> matched {m.get('best_item')} (score {m.get('score')})")

                v = jdg.get("verdict", "concern").upper()
                if v == "PASS":
                    st.success(f"🤖 **Judge Verdict: {v}**")
                elif v == "CONCERN":
                    st.warning(f"🤖 **Judge Verdict: {v}**")
                else:
                    st.error(f"🤖 **Judge Verdict: {v}**")
                st.caption(f"**Reason:** {jdg.get('reason', '')}")
                if jdg.get("suggestion"):
                    st.caption(f"**Suggestion:** {jdg.get('suggestion')}")

            # Actions: Approve / Reject
            st.markdown("---")
            st.subheader("Human Decision")
            item_id = selected_item.get("id")
            block_reason = review.block_reason(selected_item, reviewer_name)
            can_approve = not block_reason
            reject_code_key = f"reject_code_{item_id}"
            reject_note_key = f"reject_note_{item_id}"

            def _record_decision(decision: str, reason_code: str, note: str) -> bool:
                selected_item["status"] = decision
                selected_item["review"] = {
                    "reviewer": reviewer_name,
                    "decision": decision,
                    "reason_code": reason_code,
                    "note": note,
                    "ts": datetime.now().isoformat(),
                }
                try:
                    with st.spinner("Saving…"):
                        save_all_items_data(items_data)
                except Exception as e:
                    st.error(f"Could not save the decision ({type(e).__name__}). Nothing was changed.")
                    return False
                st.session_state["review_selected_id"] = item_id
                st.session_state.pop(reject_code_key, None)
                st.session_state.pop(reject_note_key, None)
                return True

            col_act1, col_act2 = st.columns(2)
            with col_act1:
                if st.button("✅ APPROVE ITEM", type="primary", disabled=(not can_approve), use_container_width=True):
                    if _record_decision("approved", "", ""):
                        st.session_state["flash"] = f"✅ {item_id} approved by {reviewer_name}"
                        st.rerun()
                if not can_approve:
                    st.caption(f"⚠️ Cannot approve: {block_reason}.")

            with col_act2:
                reject_code = st.selectbox(
                    "Reject Reason Code",
                    review.REJECT_CODES,
                    key=reject_code_key,
                )
                reject_note = st.text_input("Reviewer Note (optional)", key=reject_note_key)
                if st.button("❌ REJECT ITEM", disabled=(not reviewer_name), use_container_width=True):
                    if _record_decision("rejected", reject_code, reject_note):
                        st.session_state["flash"] = f"❌ {item_id} rejected by {reviewer_name} ({reject_code})"
                        st.rerun()
                if not reviewer_name:
                    st.caption("⚠️ Cannot reject: Enter your name in the sidebar.")

        with col_right:
            st.markdown("### 📄 Where this answer is in the source")
            p_num = cite.get("pdf_page", 1)
            d_name = selected_item.get("doc", "medication_guide")
            parts = tuple(selected_item.get("answer_parts") or ())
            found = selected_item.get("checks", {}).get("found_in_source") is True
            snip = render_pdf_page(d_name, p_num, parts, snippet=True) if found and parts else b""
            if snip:
                st.image(snip, caption="Passage highlighted by code on the approved page", use_container_width=True)
            img_bytes = render_pdf_page(d_name, p_num, parts if found else ())
            if img_bytes:
                with st.expander(f"Full page · {cite.get('doc_title') or d_name} · PDF page {p_num}", expanded=not snip):
                    st.image(img_bytes, use_container_width=True)
            else:
                st.info("PDF page render unavailable.")

# ==============================================================================
# TAB 2: LIVE CHAT (FALLBACK UI)
# ==============================================================================
with tab_chat:
    st.warning(templates.BANNER)

    # Session messages
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []
    if "session_id" not in st.session_state:
        st.session_state.session_id = f"sess-{datetime.now().strftime('%H%M%S')}"

    # Starters
    st.write("**Suggested Starters:**")
    sc1, sc2, sc3, sc4 = st.columns(4)
    starter_cols = [sc1, sc2, sc3, sc4]
    for idx, s in enumerate(templates.STARTERS):
        if starter_cols[idx].button(s, key=f"starter_{idx}", use_container_width=True):
            st.session_state.chat_history.append({"role": "user", "text": s})
            with st.spinner("Classifying and checking approved content..."):
                res = pipeline.answer_turn(s, session_id=st.session_state.session_id)
            st.session_state.chat_history.append({"role": "assistant", "turn": res})
            st.rerun()

    st.markdown("---")

    # Render History
    for msg in st.session_state.chat_history:
        if msg["role"] == "user":
            with st.chat_message("user", avatar="👤"):
                st.write(msg["text"])
        else:
            turn = msg["turn"]
            with st.chat_message("assistant", avatar="🛡️"):
                # Style by kind
                kind = turn.get("kind", "")
                reply = turn.get("reply_text", "")

                # Reply text is shown exactly as served (no markdown re-rendering).
                if kind.startswith("red_"):
                    st.error("🚨 **Safety Escalation:**")
                    with st.expander("📋 Submit Adverse Event (AE) Intake Form (Demo)", expanded=False):
                        with st.form(key=f"ae_form_{turn.get('latency_ms')}_{len(st.session_state.chat_history)}"):
                            rep_name = st.text_input("Patient Name / Initials", value="")
                            rep_role = st.selectbox("Reporter Role", ["Patient", "Caregiver / Family", "Healthcare Provider"])
                            rep_sev = st.selectbox("Severity", ["Mild", "Moderate", "Severe", "Urgent / Emergency"], index=1)
                            user_prev = st.session_state.chat_history[-2]["text"] if len(st.session_state.chat_history) >= 2 else ""
                            rep_desc = st.text_area("Symptom Description", value=user_prev)
                            if st.form_submit_button("Submit AE Report"):
                                review.record_ae_form(
                                    rid=turn.get("report_id"),
                                    form_data={
                                        "reporter_type": rep_role,
                                        "patient_name": rep_name,
                                        "severity": rep_sev,
                                        "description": rep_desc,
                                        "submitted_at": datetime.now().isoformat(timespec="seconds"),
                                    },
                                    session_id=st.session_state.session_id,
                                )
                                st.success("Adverse Event Report submitted to safety queue!")
                elif kind == "advice":
                    st.warning("ℹ️ **Guidance Note:**")
                st.code(reply, language=None, wrap_lines=True)
                if turn.get("citation"):
                    st.caption(turn["citation"])
                found_ph = PLACEHOLDER_RE.findall(turn.get("answer") or "")
                if found_ph:
                    st.markdown(":red-background[:red[**Placeholder found**]]")
                    st.text("\n".join(found_ph))

                # Show why line as cleaner expander
                if show_why:
                    why = turn.get("why", {})
                    with st.expander("🔍 Traceability & Reasoning", expanded=False):
                        st.markdown(f"""
                        - **Zone:** `{why.get('zone')}`
                        - **Intent:** `{why.get('intent')}`
                        - **Matched ID:** `{why.get('matched_id')}`
                        - **Score:** `{why.get('score')}`
                        - **Latency:** `{turn.get('latency_ms')}ms`
                        """)
                        if why.get("scan_terms"):
                            st.markdown(f"- **Safety Words Detected:** `{why.get('scan_terms')}`")

                # Source page expander
                src = turn.get("source_page")
                if src:
                    with st.expander("📄 View Source Page Preview"):
                        img_b = render_pdf_page(src.get("doc"), src.get("pdf_page"))
                        if img_b:
                            st.image(img_b, caption=f"{src.get('doc')} · Page {src.get('pdf_page')}", width=400)

    # Chat Input
    if user_prompt := st.chat_input("Ask a question about KESIMPTA..."):
        st.session_state.chat_history.append({"role": "user", "text": user_prompt})
        with st.spinner("Classifying and checking approved content..."):
            res = pipeline.answer_turn(user_prompt, session_id=st.session_state.session_id)
        st.session_state.chat_history.append({"role": "assistant", "turn": res})
        st.rerun()

# ==============================================================================
# TAB 3: INSIGHTS & REPORTS
# ==============================================================================
with tab_insights:
    st.header("Safety Reports & Content Gaps")
    logs = load_logs()

    # Section 1: Safety reports
    st.subheader("🚨 Safety Reports (Escalated Red Queries)")
    red_reports = [l for l in logs if l.get("report_status") is not None and not l.get("eval")]

    if not red_reports:
        st.info("No safety reports logged yet. (Ask an urgent question, symptom, or pen complaint in Chat to trigger).")
    else:
        st.write(f"Total escalated reports: **{len(red_reports)}**")
        for rep in reversed(red_reports):
            status = rep.get("report_status")
            status_badge = "🔴 OPEN" if status == "open" else "🟢 ACKNOWLEDGED"
            with st.container(border=True):
                rc1, rc2, rc3 = st.columns([3, 1, 1])
                rc1.write(f"**Query:** \"{rep.get('message')}\"")
                rc1.caption(f"**Type:** `{rep.get('red_type')}` | **Terms:** `{rep.get('scan_terms')}` | **Time:** {rep.get('ts')}")
                if rep.get("ae_form"):
                    ae = rep["ae_form"]
                    with rc1.expander("📋 Patient Adverse Event Intake Form (Submitted)", expanded=True):
                        st.markdown(f"**Reporter:** {ae.get('patient_name', 'Anonymous')} ({ae.get('reporter_type', 'Patient')})")
                        if ae.get("contact"):
                            st.markdown(f"**Contact:** {ae.get('contact')}")
                        st.markdown(f"**Onset:** {ae.get('onset_date', '—')} · **Severity:** `{ae.get('severity', '—')}` · **HCP Contacted:** {ae.get('doctor_contacted', '—')}")
                        st.markdown(f"**Description:** {ae.get('description', '—')}")
                        if ae.get("product_pen_issue"):
                            st.markdown(f"**Pen/Lot:** {ae.get('product_pen_issue')}")
                        if ae.get("submitted_at"):
                            st.caption(f"Submitted: {ae.get('submitted_at')}")
                rc2.write(f"**Status:** {status_badge}")
                if rep.get("ack_by"):
                    rc2.caption(f"Ack by: {rep.get('ack_by')} at {rep.get('ack_ts')}")

                if status == "open":
                    ack_clicked = rc3.button(
                        "Acknowledge", key=f"ack_{rep.get('ts')}_{rep.get('session_id')}",
                        disabled=(not reviewer_name),
                    )
                    if not reviewer_name:
                        rc3.caption("Enter your name in the sidebar")
                    if ack_clicked:
                        # Re-read right before rewriting so lines appended since this page
                        # loaded (new chat turns) are not dropped.
                        fresh_logs = load_logs()
                        for entry in fresh_logs:
                            if entry.get("ts") == rep.get("ts") and entry.get("session_id") == rep.get("session_id"):
                                entry["report_status"] = "acknowledged"
                                entry["ack_by"] = reviewer_name
                                entry["ack_ts"] = datetime.now().isoformat()
                        try:
                            save_logs(fresh_logs)
                        except Exception as e:
                            st.error(f"Could not save the acknowledgement ({type(e).__name__}).")
                        else:
                            st.session_state["flash"] = "Report acknowledged!"
                            st.rerun()

    st.markdown("---")

    # Section 2: Content Gaps
    st.subheader("💡 Content Gaps Analysis")
    st.caption("Internal analytics — AI-generated, for content planning only. Never shown to patients.")

    unanswered_msgs = [
        l.get("message") for l in logs
        if l.get("route") in ["no_answer", "related"] and not l.get("eval")
    ]
    st.write(f"Logged unanswered or related queries: **{len(unanswered_msgs)}**")

    if st.button("🔍 Find Content Gaps", type="primary"):
        if not unanswered_msgs:
            sample_gaps = [
                "Can I drink alcohol while taking Kesimpta?",
                "Does Kesimpta affect my fertility?",
                "Can I take Kesimpta if I have dental surgery coming up?",
                "How do I travel internationally with my pen?",
                "Can I take my pen in checked luggage?",
            ]
            msgs_to_cluster = sample_gaps
            st.info("Using sample gap questions for demonstration:")
        else:
            msgs_to_cluster = unanswered_msgs

        PROMPT_GAPS = """These are questions users asked a KESIMPTA patient information assistant that it could not answer from its approved content. Group them into themes for the content team. Do not answer the questions.
Return ONLY valid JSON: {"themes":[{"label":"short theme name","count":0,"example_messages":["…"],"suggested_content":"what kind of approved content or source document could cover this"}]}
Questions:
{MESSAGES}"""

        with st.spinner("Gemini is grouping unanswered questions…"):
            try:
                client = pipeline.get_genai_client()
                resp = client.models.generate_content(
                    model=config.MODEL_FLASH,
                    contents=PROMPT_GAPS.replace("{MESSAGES}", "\n".join(f"- {m}" for m in msgs_to_cluster)),
                    config=types.GenerateContentConfig(
                        temperature=0,
                        response_mime_type="application/json",
                    ),
                )
                parsed_gaps = json.loads(pipeline.clean_json_text(resp.text))
                themes = parsed_gaps.get("themes", [])
                if not isinstance(themes, list):
                    raise ValueError("themes is not a list")
                st.session_state["gap_themes"] = themes
                st.session_state.pop("gap_error", None)
            except Exception as e:
                st.session_state["gap_error"] = f"Could not group the questions right now ({type(e).__name__}). Please try again."

    if st.session_state.get("gap_error"):
        st.error(st.session_state["gap_error"])

    themes = st.session_state.get("gap_themes")
    if themes is not None:
        st.write(f"Found **{len(themes)}** content gap themes:")
        for th in themes:
            if not isinstance(th, dict):
                continue
            with st.expander(f"📌 {th.get('label')} (Count: {th.get('count', len(th.get('example_messages', [])))})", expanded=True):
                st.write("**Examples:**")
                for eg in th.get("example_messages", []):
                    st.markdown(f"- *{eg}*")
                st.info(f"**Suggested Content Plan:** {th.get('suggested_content')}")
