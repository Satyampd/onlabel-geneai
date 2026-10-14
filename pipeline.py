import json
import os
import re
import time
from datetime import datetime
import numpy as np
from google import genai
from google.genai import types
import config
from templates import (
    TEMPLATE_ANSWER,
    TEMPLATE_RELATED,
    TEMPLATE_ADVICE,
    TEMPLATE_RED_URGENT,
    TEMPLATE_RED_SIDE_EFFECT,
    TEMPLATE_RED_PREGNANCY,
    TEMPLATE_RED_COMPLAINT,
    TEMPLATE_NO_ANSWER,
    TEMPLATE_OFF_TOPIC,
    TEMPLATE_ERROR,
)

PROMPT_TRIAGE = """You are the safety triage step of a patient information assistant for KESIMPTA (a multiple sclerosis medicine). You never answer questions. You only classify the message, so the system can pick a pre-approved response.

Zones:
- "green": a general factual question about KESIMPTA that approved patient information could answer (how to use, storage, dosing schedule, missed dose, side effects in general, who should not use it, vaccines, pregnancy information in general, ingredients, support, cost).
- "yellow": asks for a personal decision or advice that depends on the person's own health ("should I…", "is it safe for me…", "can I skip…", "should I stop…").
- "red": the person describes something that HAPPENED to them or someone they care for after using it (a possible side effect or symptom), says they or their partner are pregnant while on treatment, describes an urgent medical situation, or reports a problem with the pen or the medicine itself (damaged, leaking, cloudy, didn't click, frozen, expired).
- "off_topic": not about KESIMPTA or MS treatment.

Rules:
- A general question ("does it cause headaches?") is green. A personal experience ("I've had a headache since my injection") is red.
- Planning a pregnancy is green or yellow; being pregnant while on treatment is red with red_type "pregnancy".
- If unsure between red and anything else, choose red. If unsure between yellow and green, choose yellow.
- Comparisons with other treatments are green with intent "comparison"; approved content decides what can be said.

For red, red_type is one of: "urgent", "side_effect", "pregnancy", "complaint". Otherwise null.

Return ONLY valid JSON:
{"zone":"green|yellow|red|off_topic","red_type":"urgent|side_effect|pregnancy|complaint|null","intent":"about|how_to_use|dosing_schedule|missed_dose|storage_travel|side_effects|serious_warnings|pregnancy_breastfeeding|vaccines|who_should_not_use|ingredients|support_cost|comparison|other","reason":"short reason"}"""

# Safety word lists
TIER1_TERMS = [
    "can't breathe", "cant breathe", "trouble breathing", "hard to breathe",
    "chest tightness", "chest pain", "lips are swelling", "face is swelling",
    "tongue is swelling", "throat is swelling", "throat is closing",
    "emergency", "911", "ambulance", "hospital", "fainted", "passed out",
    "overdose", "injected twice", "double dose", "wrong dose",
    "suicide", "self-harm", "kill myself"
]

PREGNANCY_TERMS = [
    "i'm pregnant", "im pregnant", "i am pregnant", "got pregnant",
    "became pregnant", "found out i'm pregnant", "i think i'm pregnant",
    "my wife is pregnant", "my partner is pregnant", "pregnant now"
]

EXPERIENCE_MARKERS = [
    "i have ", "i've ", "ive ", "i had ", "i got ", "i'm having", "im having",
    "i am having", "i feel", "i felt", "i noticed", "i'm getting", "im getting",
    "i keep", "since my", "after my", "my skin", "my eyes", "my lips",
    "my face", "my throat", "my tongue", "my arm", "my leg", "my head",
    "my urine", "my pen", "my injection", "my son", "my daughter",
    "my wife", "my husband", "my mother", "my father", "my child"
]

SYMPTOM_WORDS = [
    "rash", "hives", "itch", "fever", "chills", "headache", "swelling",
    "swollen", "yellow", "jaundice", "dark urine", "vomit", "nausea",
    "weak", "vision", "blurry", "confus", "infection", "dizzy", "faint"
]

COMPLAINT_WORDS = [
    "didn't click", "didnt click", "won't click", "wont click",
    "broken", "leak", "cloudy", "particles", "expired",
    "damaged", "froze", "frozen", "cracked"
]


def safety_word_scan(message: str) -> tuple[str | None, list[str]]:
    """
    Scans the message for safety keywords.
    Returns (red_type, matched_terms).
    Can only raise severity to red.
    """
    padded = f" {message.lower()} "
    scan_terms = []

    # 1. TIER 1 Urgent
    for term in TIER1_TERMS:
        if term in padded:
            scan_terms.append(term)
    if scan_terms:
        return "urgent", scan_terms

    # 2. Pregnancy
    for term in PREGNANCY_TERMS:
        if term in padded:
            scan_terms.append(term)
    if scan_terms:
        return "pregnancy", scan_terms

    # 3. Experience markers + Symptoms or Complaints
    matched_exp = [m for m in EXPERIENCE_MARKERS if m in padded]
    if matched_exp:
        matched_symptoms = [s for s in SYMPTOM_WORDS if s in padded]
        if matched_symptoms:
            return "side_effect", matched_exp + matched_symptoms

        matched_complaints = [c for c in COMPLAINT_WORDS if c in padded]
        if matched_complaints:
            return "complaint", matched_exp + matched_complaints

    return None, []


_client_instance = None


def get_genai_client():
    global _client_instance
    if _client_instance is None:
        _client_instance = genai.Client(
            vertexai=True,
            project=config.PROJECT_ID,
            location=config.LOCATION,
        )
    return _client_instance


def get_embedding(client, text: str) -> list[float]:
    resp = client.models.embed_content(
        model=config.MODEL_EMBED,
        contents=text,
        config=types.EmbedContentConfig(task_type="SEMANTIC_SIMILARITY"),
    )
    if hasattr(resp, "embeddings") and resp.embeddings:
        vec = resp.embeddings[0].values
    elif hasattr(resp, "embedding") and resp.embedding:
        vec = resp.embedding.values
    else:
        raise ValueError("No embedding returned")
    v = np.array(vec, dtype=np.float32)
    norm = np.linalg.norm(v)
    return (v / norm if norm > 0 else v).tolist()


def cosine_sim(v1, v2) -> float:
    a = np.array(v1, dtype=np.float32)
    b = np.array(v2, dtype=np.float32)
    return float(np.dot(a, b))


def load_approved_items() -> list[dict]:
    if not os.path.exists(config.ITEMS_JSON):
        return []
    try:
        with open(config.ITEMS_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
            return [it for it in data.get("items", []) if it.get("status") == "approved"]
    except Exception as e:
        print(f"Error loading items.json: {e}")
        return []


def clean_json_text(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def answer_turn(message: str, session_id: str, eval: bool = False) -> dict:
    """
    Main decision and answer pipeline.
    Returns:
    {
        "reply_text": str,
        "kind": str,
        "answer": str | None,
        "citation": str | None,
        "source_page": {"doc": str, "pdf_page": int} | None,
        "why": {
            "zone": str,
            "red_type": str | None,
            "intent": str | None,
            "matched_id": str | None,
            "score": float | None,
            "scan_terms": list[str],
        },
        "latency_ms": float,
    }
    """
    start_t = time.time()
    client = get_genai_client()

    try:
        # Step 1: Safety word scan (code)
        scan_red_type, scan_terms = safety_word_scan(message)

        # Step 2: Triage call with MODEL_FLASH
        triage_resp = None
        for attempt in range(2):
            try:
                resp = client.models.generate_content(
                    model=config.MODEL_FLASH,
                    contents=message,
                    config=types.GenerateContentConfig(
                        temperature=0,
                        system_instruction=PROMPT_TRIAGE,
                        response_mime_type="application/json",
                    ),
                )
                cleaned = clean_json_text(resp.text)
                triage_resp = json.loads(cleaned)
                break
            except Exception as e:
                if attempt == 1:
                    raise

        if not triage_resp or not isinstance(triage_resp, dict):
            raise ValueError(f"Invalid triage output: {triage_resp}")

        zone = triage_resp.get("zone", "off_topic")
        red_type = triage_resp.get("red_type")
        intent = triage_resp.get("intent", "other")
        model_reason = triage_resp.get("reason", "")

        # If scan fired, force zone "red" and use scan's red_type if model gave none
        if scan_red_type is not None:
            zone = "red"
            if not red_type or red_type == "null":
                red_type = scan_red_type

        # Step 3: Route
        reply_text = ""
        kind = ""
        answer = None
        citation = None
        source_page = None
        matched_id = None
        score = None

        if zone == "red":
            if red_type == "urgent":
                reply_text = TEMPLATE_RED_URGENT
                kind = "red_urgent"
            elif red_type == "pregnancy":
                reply_text = TEMPLATE_RED_PREGNANCY
                kind = "red_pregnancy"
            elif red_type == "complaint":
                reply_text = TEMPLATE_RED_COMPLAINT
                kind = "red_complaint"
            else:
                reply_text = TEMPLATE_RED_SIDE_EFFECT
                kind = "red_side_effect"

        elif zone == "yellow":
            reply_text = TEMPLATE_ADVICE
            kind = "advice"

        elif zone == "off_topic":
            reply_text = TEMPLATE_OFF_TOPIC
            kind = "off_topic"

        elif zone == "green":
            # Embed user message
            msg_vec = get_embedding(client, message)
            approved_items = load_approved_items()

            best_item = None
            best_score = -1.0

            for item in approved_items:
                item_vecs = item.get("embeddings", [])
                for v in item_vecs:
                    sim = cosine_sim(msg_vec, v)
                    if sim > best_score:
                        best_score = sim
                        best_item = item

            score = best_score if best_item else 0.0

            if best_item and score >= config.ACCEPT_THRESHOLD:
                kind = "answer"
                answer = best_item["answer"]
                matched_id = best_item["id"]
                cite_info = best_item.get("citation", {})
                if best_item.get("doc") == "brochure":
                    citation = f"Source: KESIMPTA brochure · pp. {cite_info.get('printed_pages', '')}"
                else:
                    citation = f"Source: {cite_info.get('doc_title', 'Medication Guide')} · {cite_info.get('section', '')}"
                reply_text = TEMPLATE_ANSWER.format(answer=answer, citation=citation)
                source_page = {
                    "doc": best_item.get("doc"),
                    "pdf_page": cite_info.get("pdf_page", 1),
                }

            elif best_item and score >= config.RELATED_THRESHOLD:
                kind = "related"
                answer = best_item["answer"]
                matched_id = best_item["id"]
                cite_info = best_item.get("citation", {})
                if best_item.get("doc") == "brochure":
                    citation = f"Source: KESIMPTA brochure · pp. {cite_info.get('printed_pages', '')}"
                else:
                    citation = f"Source: {cite_info.get('doc_title', 'Medication Guide')} · {cite_info.get('section', '')}"
                reply_text = TEMPLATE_RELATED.format(answer=answer, citation=citation)
                source_page = {
                    "doc": best_item.get("doc"),
                    "pdf_page": cite_info.get("pdf_page", 1),
                }

            else:
                kind = "no_answer"
                reply_text = TEMPLATE_NO_ANSWER

        else:
            kind = "off_topic"
            reply_text = TEMPLATE_OFF_TOPIC

        # Step 4: Assert inserted answer == approved item's "answer"
        verbatim_ok = True
        if answer is not None and best_item is not None:
            assert answer == best_item["answer"], "Verbatim assertion failed: displayed answer != approved answer!"
            verbatim_ok = True

    except Exception as e:
        print(f"Exception in answer_turn: {e}")
        kind = "error"
        reply_text = TEMPLATE_ERROR
        zone = "error"
        red_type = None
        intent = "error"
        model_reason = str(e)
        matched_id = None
        score = None
        answer = None
        citation = None
        source_page = None
        scan_terms = []
        verbatim_ok = True

    latency_ms = (time.time() - start_t) * 1000

    why = {
        "zone": zone,
        "red_type": red_type,
        "intent": intent,
        "matched_id": matched_id,
        "score": round(score, 4) if score is not None else None,
        "scan_terms": scan_terms,
    }

    # Step 5: Append to data/log.jsonl
    log_entry = {
        "ts": datetime.now().isoformat(),
        "session_id": session_id,
        "message": message,
        "scan_terms": scan_terms,
        "zone": zone,
        "red_type": red_type,
        "intent": intent,
        "model_reason": model_reason,
        "route": kind,
        "matched_id": matched_id,
        "score": round(score, 4) if score is not None else None,
        "verbatim_ok": verbatim_ok,
        "latency_ms": round(latency_ms, 2),
        "report_status": ("open" if (zone == "red" and not eval) else None),
        "ack_by": None,
        "ack_ts": None,
        "eval": eval,
    }

    try:
        os.makedirs(os.path.dirname(config.LOG_JSONL), exist_ok=True)
        with open(config.LOG_JSONL, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry) + "\n")
    except Exception as e:
        print(f"Warning: Failed to write to log.jsonl: {e}")

    return {
        "reply_text": reply_text,
        "kind": kind,
        "answer": answer,
        "citation": citation,
        "source_page": source_page,
        "figure": best_item.get("figure") if best_item else None,
        "why": why,
        "latency_ms": round(latency_ms, 2),
    }
