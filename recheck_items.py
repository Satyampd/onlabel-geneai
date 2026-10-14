"""Re-run the CODE checks on an existing data/items.json, with no Gemini calls.

Use this after updating build_items.py, instead of a full rebuild:
  python recheck_items.py                    # re-verify; changed or unverifiable items lose approval
  python recheck_items.py --reset-approvals  # also set every item back to pending (fresh human review)

What it checks again, against the PDFs:
- every answer part is found word for word in the source (type, length and sentence-cut rules included)
- the display answer is rebuilt from the verified parts
- the citation section really appears in the source (otherwise it is blanked)
- draft placeholders like [$0]
- printed page numbers use one dash style

An approved item keeps its approval only if it is still verified AND its answer text is unchanged.
"""
import json
import os
import re
import sys
import tempfile
from datetime import datetime

import pymupdf

import config
from build_items import format_answer_part, normalise, normalise_printed_pages, verify_parts

PLACEHOLDER_RE = re.compile(r"\[[^\]]+\]")


def load_sources():
    mg_raw = "\n".join(p.get_text("text") for p in pymupdf.open(config.MEDICATION_GUIDE_PDF))
    br_doc = pymupdf.open(config.BROCHURE_PDF)
    return mg_raw, {n: br_doc[n - 1].get_text("text") for n in range(1, len(br_doc) + 1)}


def recheck(reset_approvals: bool = False) -> None:
    with open(config.ITEMS_JSON, encoding="utf-8") as f:
        data = json.load(f)
    mg_raw, br_pages = load_sources()
    mg_norm = normalise(mg_raw)
    now = datetime.now().isoformat()
    counts = {"items": 0, "verified": 0, "unverified": 0, "answer_changed": 0,
              "section_blanked": 0, "placeholder": 0, "approval_removed": 0}

    for item in data.get("items", []):
        counts["items"] += 1
        cite = item.setdefault("citation", {})
        checks = item.setdefault("checks", {})
        if item.get("doc") == "medication_guide":
            raw = mg_raw
        else:
            raw = br_pages.get(cite.get("pdf_page"), "")
        norm = mg_norm if raw is mg_raw else normalise(raw)

        found, parts, not_found, notes = verify_parts(item.get("answer_parts"), norm, raw)
        item["answer_parts"] = parts
        old_answer = item.get("answer", "")
        new_answer = "\n".join(format_answer_part(p) for p in parts) if found else "\n".join(parts)
        item["answer"] = new_answer

        section = cite.get("section") or ""
        section_ok = bool(normalise(section)) and normalise(section) in norm
        if not section_ok and section:
            cite["section"] = ""
            counts["section_blanked"] += 1
        if cite.get("printed_pages"):
            cite["printed_pages"] = normalise_printed_pages(cite["printed_pages"])

        has_placeholder = bool(PLACEHOLDER_RE.search(new_answer))
        checks.update(found_in_source=found, not_found_parts=not_found, placeholder=has_placeholder,
                      section_verified=section_ok,
                      notes=sorted(set((checks.get("notes") or []) + notes)))
        counts["verified" if found else "unverified"] += 1
        counts["placeholder"] += has_placeholder
        changed = new_answer != old_answer
        counts["answer_changed"] += changed

        approved = item.get("status") == "approved"
        if reset_approvals or (approved and (not found or changed or has_placeholder)):
            if approved:
                counts["approval_removed"] += 1
            reason = "RESET_FOR_HUMAN_REVIEW" if reset_approvals else "SOURCE_CHANGED: needs re-approval"
            item["status"] = "pending"
            item["review"] = {"reviewer": "", "decision": "", "reason_code": "", "note": reason, "ts": now}

    # Atomic write: the chat reads this file while it runs.
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(config.ITEMS_JSON)), suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp, config.ITEMS_JSON)
    print(json.dumps(counts, indent=2))


if __name__ == "__main__":
    recheck(reset_approvals="--reset-approvals" in sys.argv)
