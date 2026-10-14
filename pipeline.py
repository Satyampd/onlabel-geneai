import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
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

# Safety word lists. All terms match at word boundaries (so "itch" never matches
# "switch"). A trailing "*" means "word starting with" (e.g. "vomit*" = vomit, vomiting).

# Always urgent, even without a personal marker: these phrases describe a situation.
URGENT_PHRASES = [
    "can't breathe", "cant breathe", "cannot breathe", "trouble breathing", "hard to breathe",
    "chest tightness", "chest feels tight", "chest pain", "lips are swelling", "face is swelling",
    "tongue is swelling", "throat is swelling", "throat is closing", "call 911",
    "fainted", "passed out", "overdose*", "injected twice", "double dose", "wrong dose",
    "suicid*", "self-harm", "kill myself",
]

# Urgent only together with a personal marker ("Is it given in a hospital?" stays green).
URGENT_CONTEXT_WORDS = ["emergency", "911", "ambulance", "hospital*", "er"]

PREGNANCY_PHRASES = [
    "i'm pregnant", "im pregnant", "i am pregnant", "got pregnant", "became pregnant",
    "i think i'm pregnant", "i think im pregnant", "my wife is pregnant",
    "my partner is pregnant",
]
NEGATIONS = ["not pregnant", "never pregnant"]

# Personal-experience markers: someone describes what happened, not asks in general.
EXPERIENCE_MARKERS = [
    "i have", "i've had", "i've been", "i've got", "i've noticed", "i've developed",
    "ive had", "ive been", "ive got", "i had", "i got", "i'm having", "im having",
    "i am having", "i feel", "i felt", "i noticed", "i'm getting", "im getting", "i keep",
    "since my", "after my", "my skin", "my eyes", "my lips", "my face", "my throat",
    "my tongue", "my arm", "my leg", "my head", "my urine", "my pen", "my injection",
    "my son", "my daughter", "my wife", "my husband", "my mother", "my father", "my child",
    "my mom", "my mum", "my dad", "my baby",
]

SYMPTOM_WORDS = [
    "rash*", "hives", "itch*", "fever*", "chills", "headache*", "swelling", "swollen",
    "yellow*", "jaundice", "dark urine", "vomit*", "nausea*", "weak*", "vision", "blurry",
    "confus*", "infection*", "dizz*", "faint*",
]

COMPLAINT_WORDS = [
    "didn't click", "didnt click", "won't click", "wont click", "broken", "leak*",
    "cloudy", "particles", "expired", "damaged", "froze", "frozen", "cracked",
]


def _pattern(term: str) -> re.Pattern:
    stem = term[:-1] if term.endswith("*") else term
    tail = r"\w*" if term.endswith("*") else r"\b"
    return re.compile(r"(?<![\w'])" + re.escape(stem) + tail)


_COMPILED: dict[str, list[tuple[str, re.Pattern]]] = {
    name: [(t, _pattern(t)) for t in terms]
    for name, terms in {
        "urgent": URGENT_PHRASES, "urgent_ctx": URGENT_CONTEXT_WORDS,
        "pregnancy": PREGNANCY_PHRASES, "exp": EXPERIENCE_MARKERS,
        "symptom": SYMPTOM_WORDS, "complaint": COMPLAINT_WORDS,
    }.items()
}


MODAL_PREFIXES = {"can", "could", "do", "does", "did", "if", "will", "might", "should", "would", "is", "are"}
AMBIGUOUS_EXP_TERMS = {"i have", "i had", "i feel", "i get"}


def _clean_exp_hits(hits: list[str], text: str) -> list[str]:
    """Filter out experience markers when used in interrogative/conditional queries (e.g. 'Can I have a fever?')"""
    if not any(h in AMBIGUOUS_EXP_TERMS for h in hits):
        return hits
    cleaned = []
    for h in hits:
        if h in AMBIGUOUS_EXP_TERMS:
            genuine = False
            for m in re.finditer(r"\b" + re.escape(h) + r"\b", text):
                pre_words = text[:m.start()].rstrip().split()
                if not pre_words or pre_words[-1].lower() not in MODAL_PREFIXES:
                    genuine = True
                    break
            if genuine:
                cleaned.append(h)
        else:
            cleaned.append(h)
    return cleaned


def _hits(name: str, text: str) -> list[str]:
    return [t for t, p in _COMPILED[name] if p.search(text)]


def safety_word_scan(message: str) -> tuple[str | None, list[str]]:
    """
    Scans the message for safety keywords.
    Returns (red_type, matched_terms).
    Can only raise severity to red.
    """
    text = message.lower().replace("’", "'")

    urgent = _hits("urgent", text)
    if urgent:
        return "urgent", urgent

    exp = _clean_exp_hits(_hits("exp", text), text)
    urgent_ctx = _hits("urgent_ctx", text)
    if exp and urgent_ctx:
        return "urgent", exp + urgent_ctx

    if not any(n in text for n in NEGATIONS):
        pregnancy = _hits("pregnancy", text)
        if pregnancy:
            return "pregnancy", pregnancy

    if exp:
        symptoms = _hits("symptom", text)
        if symptoms:
            return "side_effect", exp + symptoms
        complaints = _hits("complaint", text)
        if complaints:
            return "complaint", exp + complaints

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


_items_cache = {"mtime": None, "items": [], "matrix": None, "owners": []}


def load_approved_items() -> list[dict]:
    """Approved AND verified items. Re-reads items.json only when the file changes
    (it is ~30 MB because of the embeddings, so parsing it every turn adds latency)."""
    if not os.path.exists(config.ITEMS_JSON):
        return []
    try:
        mtime = os.path.getmtime(config.ITEMS_JSON)
        if _items_cache["mtime"] != mtime:
            with open(config.ITEMS_JSON, "r", encoding="utf-8") as f:
                data = json.load(f)
            items = [
                it for it in data.get("items", [])
                if it.get("status") == "approved"
                and it.get("checks", {}).get("found_in_source") is True
            ]
            vecs, owners = [], []
            for idx, it in enumerate(items):
                for v in it.get("embeddings", []):
                    vecs.append(v)
                    owners.append(idx)
            _items_cache.update(
                mtime=mtime,
                items=items,
                matrix=np.array(vecs, dtype=np.float32) if vecs else None,
                owners=owners,
            )
        return _items_cache["items"]
    except Exception as e:
        print(f"Error loading items.json: {e}")
        return []


def best_match(msg_vec: list[float]) -> tuple[dict | None, float]:
    """Best approved item for a normalised query vector: max cosine over all its vectors.
    The brochure is the primary approved material: if a brochure answer scores within
    BROCHURE_PREFERENCE_MARGIN of the best answer, the brochure answer is served."""
    items = load_approved_items()
    matrix = _items_cache["matrix"]
    if not items or matrix is None:
        return None, 0.0
    sims = matrix @ np.array(msg_vec, dtype=np.float32)
    owners = np.array(_items_cache["owners"])
    i = int(np.argmax(sims))
    best_item, best_score = items[owners[i]], float(sims[i])
    if best_item.get("doc") != "brochure":
        is_brochure = np.array([items[o].get("doc") == "brochure" for o in owners])
        if is_brochure.any():
            j = int(np.argmax(np.where(is_brochure, sims, -1.0)))
            brochure_score = float(sims[j])
            if brochure_score >= best_score - config.BROCHURE_PREFERENCE_MARGIN:
                if best_score < config.ACCEPT_THRESHOLD or brochure_score >= config.ACCEPT_THRESHOLD:
                    return items[owners[j]], brochure_score
    return best_item, best_score


def clean_json_text(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


VALID_ZONES = {"green", "yellow", "red", "off_topic"}
VALID_RED_TYPES = {"urgent", "side_effect", "pregnancy", "complaint"}

RED_REPLIES = {
    "urgent": ("red_urgent", TEMPLATE_RED_URGENT),
    "pregnancy": ("red_pregnancy", TEMPLATE_RED_PREGNANCY),
    "complaint": ("red_complaint", TEMPLATE_RED_COMPLAINT),
    "side_effect": ("red_side_effect", TEMPLATE_RED_SIDE_EFFECT),
}

_executor = ThreadPoolExecutor(max_workers=16)


def triage(client, message: str) -> dict:
    """One Gemini call that only classifies. Retries once on invalid output."""
    last_error = None
    for _ in range(2):
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
            out = json.loads(clean_json_text(resp.text))
            if isinstance(out, dict):
                return out
            last_error = ValueError(f"Invalid triage output: {out}")
        except Exception as e:
            last_error = e
    raise last_error


def _citation(item: dict) -> str:
    cite = item.get("citation", {})
    if item.get("doc") == "brochure":
        title, detail = "KESIMPTA brochure", cite.get("printed_pages") and f"pp. {cite['printed_pages']}"
    else:
        title, detail = cite.get("doc_title") or "Medication Guide", cite.get("section")
    # The section is only kept when it was verified against the source (build_items.py).
    return f"Source: {title} · {detail}" if detail else f"Source: {title}"


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
        "why": {"zone", "red_type", "intent", "matched_id", "score", "scan_terms"},
        "latency_ms": float,
    }
    """
    start_t = time.time()

    # Step 1: Safety word scan (code). Runs first and never depends on a model.
    scan_red_type, scan_terms = safety_word_scan(message)

    zone, red_type, intent, model_reason = "error", None, "error", ""
    kind, reply_text = "error", TEMPLATE_ERROR
    answer = citation = source_page = matched_id = score = None
    source_label = approval = figure = None
    verbatim_ok = True

    try:
        client = get_genai_client()

        # Step 2: triage and query embedding in parallel (embedding is cheap; it is
        # only used for green, but running both at once halves the wait).
        triage_future = _executor.submit(triage, client, message)
        embed_future = _executor.submit(get_embedding, client, message)

        try:
            triage_resp = triage_future.result(timeout=30)
        except Exception as e:
            if scan_red_type is None:
                raise
            # Fail safe: the model failed, but the safety net fired -> still escalate.
            triage_resp = {"zone": "red", "red_type": scan_red_type, "intent": "other",
                           "reason": f"triage unavailable ({type(e).__name__}); safety word scan fired"}

        zone = str(triage_resp.get("zone", "")).strip().lower()
        red_type = str(triage_resp.get("red_type") or "").strip().lower() or None
        intent = triage_resp.get("intent", "other")
        model_reason = triage_resp.get("reason", "")

        # The safety scan can only raise severity: red beats everything.
        if scan_red_type is not None:
            zone = "red"
            if red_type not in VALID_RED_TYPES:
                red_type = scan_red_type
        if zone not in VALID_ZONES:
            raise ValueError(f"Unknown zone from triage: {zone!r}")
        if zone != "red":
            red_type = None

        # Step 3: Route
        if zone == "red":
            kind, reply_text = RED_REPLIES.get(red_type, RED_REPLIES["side_effect"])
        elif zone == "yellow":
            kind, reply_text = "advice", TEMPLATE_ADVICE
        elif zone == "off_topic":
            kind, reply_text = "off_topic", TEMPLATE_OFF_TOPIC
        else:  # green
            best_item, best_score = best_match(embed_future.result(timeout=30))
            score = best_score
            if best_item and best_score >= config.RELATED_THRESHOLD:
                answer = best_item["answer"]
                matched_id = best_item["id"]
                citation = _citation(best_item)
                template = TEMPLATE_ANSWER if best_score >= config.ACCEPT_THRESHOLD else TEMPLATE_RELATED
                kind = "answer" if template is TEMPLATE_ANSWER else "related"
                reply_text = template.format(answer=answer, citation=citation)
                source_page = {
                    "doc": best_item.get("doc"),
                    "pdf_page": best_item.get("citation", {}).get("pdf_page", 1),
                    "item_id": best_item["id"],
                }
                source_label = citation.removeprefix("Source: ")
                figure = best_item.get("figure")
                review = best_item.get("review") or {}
                if review.get("reviewer"):
                    approval = {"reviewer": review["reviewer"], "ts": review.get("ts", "")}
                # Step 4: the served text must contain the approved answer exactly,
                # and that answer must be the verified one stored for the item.
                verbatim_ok = (
                    answer in reply_text
                    and best_item.get("checks", {}).get("found_in_source") is True
                )
                if not verbatim_ok:
                    raise AssertionError("Verbatim check failed: not serving this answer")
            else:
                kind, reply_text = "no_answer", TEMPLATE_NO_ANSWER

    except Exception as e:
        print(f"Exception in answer_turn: {e}")
        kind, reply_text = "error", TEMPLATE_ERROR
        zone, red_type, intent = "error", None, "error"
        model_reason = str(e)
        answer = citation = source_page = matched_id = None
        source_label = approval = None
        verbatim_ok = True  # nothing from the item set was served

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
        import review
        with review._write_lock:
            with open(config.LOG_JSONL, "a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry) + "\n")
    except Exception as e:
        print(f"Warning: Failed to write to log.jsonl: {e}")

    report_id = f"{log_entry['ts']}|{session_id}" if log_entry["report_status"] else None

    return {
        "reply_text": reply_text,
        "kind": kind,
        "answer": answer,
        "citation": citation,
        "source_page": source_page,
        "source_label": source_label,
        "figure": figure,
        "approval": approval,
        "why": why,
        "latency_ms": round(latency_ms, 2),
        "report_id": report_id,
    }
