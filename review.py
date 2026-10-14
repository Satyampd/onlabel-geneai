"""Reviewer-side logic shared by the web console (api.py) and the Streamlit console (app.py):
the approval rules, saving decisions, safety-report acknowledgement and the content-gap report.

The approval rules live here once, so both consoles block exactly the same items.
"""
import json
import os
import re
import tempfile
import threading
from datetime import datetime

from google.genai import types

import config
import pipeline

PLACEHOLDER_RE = re.compile(r"\[[^\]]+\]")
REJECT_CODES = ["NOT_IN_SOURCE", "INCOMPLETE", "IS_ADVICE", "PLACEHOLDER_TEXT", "DUPLICATE", "OFF_SCOPE", "OTHER"]
_write_lock = threading.Lock()  # one writer at a time for items.json / log.jsonl in this process


def atomic_write(path: str, write_fn) -> None:
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


# ---------- Items ----------

def load_items_data() -> dict:
    if not os.path.exists(config.ITEMS_JSON):
        return {"items": [], "built_at": "", "build_seconds": 0}
    with open(config.ITEMS_JSON, encoding="utf-8") as f:
        return json.load(f)


def block_reason(item: dict, reviewer: str) -> str:
    """Why this item can't be approved ("" if it can). Checked again on every save."""
    checks = item.get("checks", {})
    if checks.get("found_in_source") is not True:
        return "Not found word for word in the source"
    if checks.get("placeholder"):
        return "Contains a draft placeholder: reject with PLACEHOLDER_TEXT"
    if str(item.get("judge", {}).get("verdict", "")).strip().lower() == "fail":
        return "The AI reviewer failed this item"
    if not reviewer:
        return "Enter your name first"
    return ""


def public_item(item: dict) -> dict:
    """An item as the console shows it: no embeddings (they are most of the 30 MB)."""
    out = {k: v for k, v in item.items() if k != "embeddings"}
    out["placeholders"] = PLACEHOLDER_RE.findall(item.get("answer", ""))
    out["approve_block"] = block_reason(item, reviewer="x")  # reviewer name is checked on save
    return out


def summary(items: list[dict]) -> dict:
    count = lambda pred: sum(1 for it in items if pred(it))
    return {
        "total": len(items),
        "pending": count(lambda it: it.get("status") == "pending"),
        "approved": count(lambda it: it.get("status") == "approved"),
        "rejected": count(lambda it: it.get("status") == "rejected"),
        "verified": count(lambda it: it.get("checks", {}).get("found_in_source") is True),
        "brochure": count(lambda it: it.get("doc") == "brochure"),
        "medication_guide": count(lambda it: it.get("doc") == "medication_guide"),
    }


def record_decision(item_id: str, decision: str, reviewer: str, reason_code: str = "", note: str = "") -> dict:
    """Approve or reject one item. Raises ValueError (shown to the reviewer) if not allowed."""
    reviewer = (reviewer or "").strip()
    if not reviewer:
        raise ValueError("Enter your name first")
    if decision not in ("approved", "rejected"):
        raise ValueError("Unknown decision")
    if decision == "rejected" and reason_code not in REJECT_CODES:
        raise ValueError("Choose a reason code")
    with _write_lock:
        data = load_items_data()  # re-read: never save over a newer file with a stale copy
        item = next((it for it in data.get("items", []) if it.get("id") == item_id), None)
        if item is None:
            raise KeyError(item_id)
        if decision == "approved":
            reason = block_reason(item, reviewer)
            if reason:
                raise ValueError(f"Can't approve: {reason}")
        item["status"] = decision
        item["review"] = {
            "reviewer": reviewer,
            "decision": decision,
            "reason_code": reason_code if decision == "rejected" else "",
            "note": note.strip(),
            "ts": datetime.now().isoformat(timespec="seconds"),
        }
        atomic_write(config.ITEMS_JSON, lambda f: json.dump(data, f))
    return item


# ---------- Log: safety reports, unanswered questions, audit trail ----------

def load_logs() -> list[dict]:
    if not os.path.exists(config.LOG_JSONL):
        return []
    logs = []
    with open(config.LOG_JSONL, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    logs.append(json.loads(line))
                except json.JSONDecodeError:
                    continue  # a half-written last line must not hide the rest
    return logs


def report_id(entry: dict) -> str:
    return f"{entry.get('ts')}|{entry.get('session_id')}"


def safety_reports(logs: list[dict]) -> list[dict]:
    """Red turns from real chats (not eval runs), newest first."""
    reports = [l for l in logs if l.get("report_status") is not None and not l.get("eval")]
    return [dict(r, id=report_id(r)) for r in reversed(reports)]


def acknowledge(rid: str, reviewer: str) -> dict:
    reviewer = (reviewer or "").strip()
    if not reviewer:
        raise ValueError("Enter your name first")
    with _write_lock:
        logs = load_logs()  # re-read right before rewriting so new chat turns are kept
        hit = None
        for entry in logs:
            if report_id(entry) == rid and entry.get("report_status") is not None:
                if entry.get("report_status") != "acknowledged":
                    entry.update(report_status="acknowledged", ack_by=reviewer,
                                 ack_ts=datetime.now().isoformat(timespec="seconds"))
                hit = entry
        if hit is None:
            raise KeyError(rid)

        def _write(f):
            for entry in logs:
                f.write(json.dumps(entry) + "\n")
        atomic_write(config.LOG_JSONL, _write)
    return dict(hit, id=rid)


def unanswered(logs: list[dict]) -> list[str]:
    return [l.get("message") for l in logs
            if l.get("route") in ("no_answer", "related") and not l.get("eval") and l.get("message")]


def activity(logs: list[dict], limit: int = 100) -> list[dict]:
    keep = ("ts", "message", "zone", "red_type", "intent", "route", "matched_id", "score",
            "scan_terms", "verbatim_ok", "latency_ms", "report_status")
    return [{k: l.get(k) for k in keep} for l in reversed(logs) if not l.get("eval")][:limit]


PROMPT_GAPS = """These are questions users asked a KESIMPTA patient information assistant that it could not answer from its approved content. Group them into themes for the content team. Do not answer the questions.
Return ONLY valid JSON: {"themes":[{"label":"short theme name","count":0,"example_messages":["…"],"suggested_content":"what kind of approved content or source document could cover this"}]}
Questions:
{MESSAGES}"""


def content_gaps(messages: list[str]) -> list[dict]:
    """Gemini groups unanswered questions into themes (internal analytics, never shown to patients)."""
    client = pipeline.get_genai_client()
    resp = client.models.generate_content(
        model=config.MODEL_FLASH,
        contents=PROMPT_GAPS.replace("{MESSAGES}", "\n".join(f"- {m}" for m in messages)),
        config=types.GenerateContentConfig(temperature=0, response_mime_type="application/json"),
    )
    themes = json.loads(pipeline.clean_json_text(resp.text)).get("themes", [])
    if not isinstance(themes, list):
        raise ValueError("themes is not a list")
    return [t for t in themes if isinstance(t, dict)]
