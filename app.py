import json
import os
from datetime import datetime
import streamlit as st
import pymupdf
from google import genai
from google.genai import types

import config
import templates
import pipeline

st.set_page_config(
    page_title="OnLabel · KESIMPTA Patient Information",
    page_icon="🛡️",
    layout="wide",
)

# Helper to load items
@st.cache_data
def load_all_items_data():
    if not os.path.exists(config.ITEMS_JSON):
        return {"items": [], "built_at": "", "build_seconds": 0}
    try:
        with open(config.ITEMS_JSON, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        st.error(f"Error loading items.json: {e}")
        return {"items": [], "built_at": "", "build_seconds": 0}


def save_all_items_data(data):
    with open(config.ITEMS_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    load_all_items_data.clear()


@st.cache_data
def render_pdf_page(doc_name: str, pdf_page: int) -> bytes:
    pdf_path = config.MEDICATION_GUIDE_PDF if doc_name == "medication_guide" else config.BROCHURE_PDF
    if not os.path.exists(pdf_path):
        return b""
    try:
        doc = pymupdf.open(pdf_path)
        p_idx = max(0, min(pdf_page - 1, len(doc) - 1))
        page = doc[p_idx]
        pix = page.get_pixmap(dpi=150)
        return pix.tobytes("png")
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
    with open(config.LOG_JSONL, "w", encoding="utf-8") as f:
        for entry in logs:
            f.write(json.dumps(entry) + "\n")


# Sidebar
with st.sidebar:
    st.title("🛡️ OnLabel Control")
    reviewer_name = st.text_input("Your Name / Session", value="Human Reviewer", key="reviewer_name")
    show_why = st.toggle("Show decision details ('why' line)", value=True, key="show_why")

    if st.button("🔄 Refresh Data"):
        st.cache_data.clear()
        st.rerun()

    st.markdown("---")
    st.markdown("### 📋 Important Safety Info")
    if os.path.exists(config.SAFETY_PANEL_TXT):
        with open(config.SAFETY_PANEL_TXT, "r", encoding="utf-8") as f:
            safety_text = f.read()
        with st.expander("View Safety Panel", expanded=False):
            st.markdown(f"```text\n{safety_text}\n```")

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
        # Sort pending first
        sorted_items = sorted(
            all_items,
            key=lambda x: (0 if x.get("status") == "pending" else (1 if x.get("status") == "approved" else 2))
        )

        # Select item
        def make_label(it):
            v = it.get("judge", {}).get("verdict", "concern").upper()
            status_icon = "⏳" if it.get("status") == "pending" else ("✅" if it.get("status") == "approved" else "❌")
            return f"[{status_icon} {it.get('status', '').upper()}] [{v}] {it.get('id')}: {it.get('question')[:60]}"

        item_labels = [make_label(it) for it in sorted_items]
        selected_idx = st.selectbox("Select Item to Inspect & Review", range(len(sorted_items)), format_func=lambda i: item_labels[i])
        selected_item = sorted_items[selected_idx]

        col_left, col_right = st.columns([3, 2])

        with col_left:
            st.subheader(f"Item: `{selected_item.get('id')}`")
            st.markdown(f"**Document:** `{selected_item.get('doc')}` | **Topic:** `{selected_item.get('topic')}`")
            st.markdown(f"### ❓ Patient Question:\n**{selected_item.get('question')}**")

            with st.expander("Alternate Patient Paraphrases", expanded=True):
                for p in selected_item.get("paraphrases", []):
                    st.markdown(f"- *{p}*")

            st.markdown("### 💬 Verified Answer (Character-for-Character):")
            st.info(selected_item.get("answer", ""))

            cite = selected_item.get("citation", {})
            st.markdown(f"**Citation:** `{cite.get('doc_title')}` · Section: *{cite.get('section')}* · PDF Page: {cite.get('pdf_page')} (Printed: {cite.get('printed_pages')})")

            # Large Evidence Panel
            st.markdown("### 🔍 Evidence & Quality Gate Panel")
            chk = selected_item.get("checks", {})
            jdg = selected_item.get("judge", {})

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
            can_approve = chk.get("found_in_source", False)

            col_act1, col_act2 = st.columns(2)
            with col_act1:
                if st.button("✅ APPROVE ITEM", type="primary", disabled=(not can_approve), use_container_width=True):
                    selected_item["status"] = "approved"
                    selected_item["review"] = {
                        "reviewer": reviewer_name,
                        "decision": "approved",
                        "reason_code": "",
                        "note": "",
                        "ts": datetime.now().isoformat(),
                    }
                    save_all_items_data(items_data)
                    st.success("Item approved!")
                    st.rerun()
                if not can_approve:
                    st.caption("⚠️ Cannot approve: Item is not 100% verified in source text.")

            with col_act2:
                reject_code = st.selectbox(
                    "Reject Reason Code",
                    ["NOT_IN_SOURCE", "INCOMPLETE", "IS_ADVICE", "PLACEHOLDER_TEXT", "DUPLICATE", "OFF_SCOPE", "OTHER"],
                    key="reject_code"
                )
                reject_note = st.text_input("Reviewer Note (optional)", key="reject_note")
                if st.button("❌ REJECT ITEM", use_container_width=True):
                    selected_item["status"] = "rejected"
                    selected_item["review"] = {
                        "reviewer": reviewer_name,
                        "decision": "rejected",
                        "reason_code": reject_code,
                        "note": reject_note,
                        "ts": datetime.now().isoformat(),
                    }
                    save_all_items_data(items_data)
                    st.warning("Item rejected.")
                    st.rerun()

        with col_right:
            st.markdown("### 📄 Cited Document Page")
            p_num = cite.get("pdf_page", 1)
            d_name = selected_item.get("doc", "medication_guide")
            img_bytes = render_pdf_page(d_name, p_num)
            if img_bytes:
                st.image(img_bytes, caption=f"{cite.get('doc_title')} · Page {p_num}", use_container_width=True)
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
            with st.chat_message("user"):
                st.write(msg["text"])
        else:
            turn = msg["turn"]
            with st.chat_message("assistant"):
                # Style by kind
                kind = turn.get("kind", "")
                reply = turn.get("reply_text", "")

                if kind.startswith("red_"):
                    st.error(reply)
                elif kind == "advice":
                    st.warning(reply)
                else:
                    st.markdown(reply)

                # Show why line
                if show_why:
                    why = turn.get("why", {})
                    zone_label = f"zone: {why.get('zone')}"
                    details = []
                    if why.get("red_type"):
                        details.append(f"red_type: {why.get('red_type')}")
                    if why.get("intent"):
                        details.append(f"intent: {why.get('intent')}")
                    if why.get("matched_id"):
                        details.append(f"matched: {why.get('matched_id')}")
                    if why.get("score") is not None:
                        details.append(f"confidence: {why.get('score')}")
                    if why.get("scan_terms"):
                        details.append(f"safety words: {why.get('scan_terms')}")
                    extra = " · ".join(details)
                    why_line = f"{zone_label} · {extra}" if extra else zone_label
                    st.caption(f"🔍 `{why_line}` · latency: {turn.get('latency_ms')}ms")

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
        for idx, rep in enumerate(reversed(red_reports)):
            status = rep.get("report_status")
            status_badge = "🔴 OPEN" if status == "open" else "🟢 ACKNOWLEDGED"
            with st.container(border=True):
                rc1, rc2, rc3 = st.columns([3, 1, 1])
                rc1.write(f"**Query:** \"{rep.get('message')}\"")
                rc1.caption(f"**Type:** `{rep.get('red_type')}` | **Terms:** `{rep.get('scan_terms')}` | **Time:** {rep.get('ts')}")
                rc2.write(f"**Status:** {status_badge}")
                if rep.get("ack_by"):
                    rc2.caption(f"Ack by: {rep.get('ack_by')} at {rep.get('ack_ts')}")

                if status == "open":
                    if rc3.button("Acknowledge", key=f"ack_{idx}"):
                        rep["report_status"] = "acknowledged"
                        rep["ack_by"] = reviewer_name
                        rep["ack_ts"] = datetime.now().isoformat()
                        save_logs(logs)
                        st.success("Report acknowledged!")
                        st.rerun()

    st.markdown("---")

    # Section 2: Content Gaps
    st.subheader("💡 Content Gaps Analysis")
    st.caption("Internal analytics — AI-generated, for content planning only. Never shown to patients.")

    unanswered_msgs = [l.get("message") for l in logs if l.get("route") in ["no_answer", "related"]]
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

        with st.spinner("Analyzing queries with Gemini 2.5 Flash..."):
            client = pipeline.get_genai_client()
            resp = client.models.generate_content(
                model=config.MODEL_FLASH,
                contents=PROMPT_GAPS.replace("{MESSAGES}", "\n".join(f"- {m}" for m in msgs_to_cluster)),
                config=types.GenerateContentConfig(
                    temperature=0,
                    response_mime_type="application/json",
                ),
            )
            gaps_data = pipeline.clean_json_text(resp.text)
            parsed_gaps = json.loads(gaps_data)
            themes = parsed_gaps.get("themes", [])

            st.write(f"Found **{len(themes)}** content gap themes:")
            for th in themes:
                with st.expander(f"📌 {th.get('label')} (Count: {th.get('count', len(th.get('example_messages', [])))})", expanded=True):
                    st.write("**Examples:**")
                    for eg in th.get("example_messages", []):
                        st.markdown(f"- *{eg}*")
                    st.info(f"**Suggested Content Plan:** {th.get('suggested_content')}")
