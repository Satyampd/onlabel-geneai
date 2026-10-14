import hashlib
import json
import os
import re
import time
from datetime import datetime
import numpy as np
import pymupdf
from google import genai
from google.genai import types
import config


PROMPT_GENERATE = """You are helping build a patient Q&A library from an approved medicine document. The document text is given below between <document> tags. It is approved patient text, and its wording must not change.

Task: list the questions a patient or caregiver would realistically ask that this document answers, and for each one point to the exact passage(s) that answer it. Cover every section at least once, and give each bullet under "What is the most important information I should know about KESIMPTA?" its own item.

Strict rules for "answer_parts":
1. Each part must be copied character-for-character from the document: same words, same order, same numbers, phone numbers, hyphens and punctuation. Never rephrase, shorten, correct or add words.
2. Use 1 to 3 parts, all from the SAME section, in the order they appear in the document. Use more than one part only when needed — typically the lead-in line of a list followed by the relevant list item(s).
3. Never start or end a part in the middle of a sentence. The answer must make sense on its own.
4. Keep list formatting: each list item on its own line, as in the document.
5. Keep the total under about 120 words; split longer sections into separate questions.
6. Ignore page headers, footers, page numbers and the distributor address.

Rules for questions:
7. "question": plain, everyday patient language, not the document's wording.
8. "paraphrases": 3–5 other ways people might ask the SAME general question (casual wording, short forms, one with a typo). General information questions only — never describe a personal symptom, an event, or a problem with someone's pen or medicine.
9. Only include questions the document truly answers.

Return ONLY valid JSON:
{"items":[{"id":"short-kebab-case-id","question":"…","paraphrases":["…"],"answer_parts":["…"],"section":"exact section heading","printed_pages":null,"topic":"about|how_to_use|dosing_schedule|missed_dose|storage_travel|side_effects|serious_warnings|pregnancy_breastfeeding|vaccines|who_should_not_use|ingredients|support_cost|other"}]}

<document>
{DOCUMENT_TEXT}
</document>"""

BROCHURE_RULES = """Additional rules for this brochure page:
- The image shows the page layout; the text between <document> tags is the exact text to copy from. Copy only from that text.
- Each PDF page is a two-page spread. Set "printed_pages" to the printed page numbers visible on the spread, e.g. "6–7".
- Ignore the "Important Safety Information" strip that runs along the pages, the line "Please see full Important Safety Information…", testimonial quotes, and video/link prompts ("Click to…").
- Skip clinical study results and statistics (percentages from studies or surveys).
- Footnotes may be used if they answer a question (e.g. storage).
- Use the nearest visible heading as "section"."""

PROMPT_JUDGE = """You are a strict reviewer checking draft patient Q&A items against the approved document text below (between <document> tags), before a human approves them. You never rewrite answers; you only judge them. Exact copying is already verified by software.

Each item comes with evidence from automatic checks: placeholder and retrieval_self_test (whether its paraphrases find this item or a different one). Use this evidence in your verdict and mention it in your reason when relevant.

For each item check:
- answers_question: does the answer actually answer the question?
- self_contained: does it read as complete sentences that make sense on their own?
- complete: is important qualifying text in the same section left out (e.g. an instruction to contact a healthcare provider, a time limit, a condition)?
- placeholder: does it contain draft markers such as [square brackets]?
- advice_risk: could showing it be mistaken for personal medical advice?
- paraphrases_ok: do all paraphrases ask the same general question?
- overlap: does it substantially overlap another item (see retrieval_self_test misses)?

Verdict: "pass" (all fine), "concern" (usable, a human should look closely), "fail" (must not be served).

Return ONLY valid JSON:
{"reviews":[{"id":"…","verdict":"pass|concern|fail","checks":{"answers_question":true,"self_contained":true,"complete":true,"placeholder":false,"advice_risk":false,"paraphrases_ok":true,"overlap":false},"reason":"one short sentence","suggestion":"what a human should consider (do NOT write a new answer)"}]}

<document>
{DOCUMENT_TEXT}
</document>

Items with evidence:
{ITEMS_JSON}"""


def clean_json_text(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def parse_json_safely(text: str):
    cleaned = clean_json_text(text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # Try finding outermost { ... } or [ ... ]
        match = re.search(r"(\[.*\]|\{.*\})", cleaned, re.DOTALL)
        if match:
            return json.loads(match.group(1))
        raise


def extract_list(data, key: str = "items") -> list:
    if isinstance(data, list):
        return data
    elif isinstance(data, dict):
        if key in data and isinstance(data[key], list):
            return data[key]
        for alt in ["items", "reviews", "data", "results"]:
            if alt in data and isinstance(data[alt], list):
                return data[alt]
    return []


def normalise(s: str) -> str:
    # curly quotes → straight quotes
    s = s.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    # hyphen at end of line joins lines WITHOUT removing hyphen
    s = re.sub(r"-\s*\n\s*", "-", s)
    # remove bullet markers at line starts ("•", "○", "▪", or "o" followed by a space)
    s = re.sub(r"(?m)^[ \t]*([•○▪]|o\s+)[ \t]*", "", s)
    # collapse all whitespace to single spaces; strip
    s = re.sub(r"\s+", " ", s).strip()
    return s


MIN_PART_CHARS = 20
PART_END_CHARS = (".", "!", "?", ":", ")")


def coerce_parts(raw):
    """answer_parts must be a list of strings; a bare string is wrapped. Anything else -> None."""
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, list) and all(isinstance(p, str) for p in raw):
        return list(raw)
    return None


FOOTNOTE_MARKS = "*†‡§¶#"
_BULLET_START = re.compile(r"^\s*([•○▪*†‡§¶#]|o\s)")


def ends_at_line_break(norm_part: str, source_raw: str | None) -> bool:
    """True if the part ends exactly where a source line ends AND the next
    non-empty line starts a new item or sentence (bullet, capital letter, digit).
    This accepts list items without punctuation ("…progressive disease") but
    rejects cuts inside a wrapped sentence ("…loss of" / "coordination in…")."""
    if not source_raw:
        return False
    lines = source_raw.splitlines()
    for i, line in enumerate(lines):
        line_norm = normalise(line)
        if not line_norm or line.rstrip().endswith("-"):
            continue
        if not (norm_part.endswith(line_norm) or line_norm.endswith(norm_part)):
            continue
        for nxt in lines[i + 1:]:
            if not nxt.strip():
                continue
            nxt_norm = normalise(nxt)
            if _BULLET_START.match(nxt) or not nxt_norm or nxt_norm[0].isupper() or nxt_norm[0].isdigit():
                return True
            break
    return False


def verify_parts(raw_parts, source_norm: str, source_raw: str | None = None):
    """Return (found_in_source, parts, not_found_parts, notes).

    A part is found only if it is a string, at least MIN_PART_CHARS long after
    normalising, occurs in source_norm, and ends at a natural boundary (ends with
    . ! ? : ), ends at a source line break before a new item/sentence, or the
    match runs to end-of-text)."""
    parts = coerce_parts(raw_parts)
    if parts is None:
        return False, [], [repr(raw_parts)[:200]], ["BAD_ANSWER_PARTS_TYPE"]
    not_found, notes = [], []
    for part in parts:
        norm_part = normalise(part)
        if len(norm_part) < MIN_PART_CHARS:
            not_found.append(part)
            notes.append("PART_TOO_SHORT")
            continue
        if norm_part not in source_norm:
            not_found.append(part)
            continue
        if not norm_part.rstrip(FOOTNOTE_MARKS).endswith(PART_END_CHARS) and not ends_at_line_break(norm_part, source_raw):
            # accept only if some occurrence runs to end-of-text
            ends_at_eot = False
            start = source_norm.find(norm_part)
            while start != -1:
                if start + len(norm_part) == len(source_norm):
                    ends_at_eot = True
                    break
                start = source_norm.find(norm_part, start + 1)
            if not ends_at_eot:
                not_found.append(part)
                notes.append("CUT_MID_SENTENCE")
    found = len(parts) > 0 and len(not_found) == 0
    return found, parts, not_found, notes


def normalise_printed_pages(pp):
    if pp is None or pp == "":
        return pp
    s = str(pp).strip()
    s = re.sub(r"\s*[-‐‑‒–—―−]\s*", "–", s)
    return s


def format_answer_part(part: str) -> str:
    lines = [line.strip() for line in part.split("\n")]
    raw_lines = [l for l in lines if l]
    if not raw_lines:
        return ""

    # 1. line that is only "•" joins next line as "• <text>"
    merged_bullets = []
    i = 0
    while i < len(raw_lines):
        line = raw_lines[i]
        if line in ("•", "○", "▪") and i + 1 < len(raw_lines):
            merged_bullets.append(f"{line} {raw_lines[i+1]}")
            i += 2
        else:
            merged_bullets.append(line)
            i += 1

    # 2. line starting with "o ", "○" or "▪" (sub-bullets) becomes "   ◦ <text>"
    transformed = []
    for line in merged_bullets:
        if line.startswith("o "):
            transformed.append("   ◦ " + line[2:].lstrip())
        elif line.startswith("○") or line.startswith("▪"):
            transformed.append("   ◦ " + line[1:].lstrip())
        else:
            transformed.append(line)

    # 3. wrapped line joins previous line with a space, unless starts a new bullet;
    #    if previous line ends with "-", join without space
    final_lines = []
    for line in transformed:
        is_bullet = line.startswith("• ") or line.startswith("   ◦ ")
        if not final_lines or is_bullet:
            final_lines.append(line)
        else:
            prev = final_lines[-1]
            if prev.endswith("-"):
                final_lines[-1] = prev + line
            else:
                final_lines[-1] = prev + " " + line

    return "\n".join(final_lines)


def get_embedding_batch(client, texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    # Send in batches of up to 50
    all_vecs = []
    batch_size = 50
    for i in range(0, len(texts), batch_size):
        chunk = texts[i:i + batch_size]
        resp = client.models.embed_content(
            model=config.MODEL_EMBED,
            contents=chunk,
            config=types.EmbedContentConfig(task_type="SEMANTIC_SIMILARITY"),
        )
        if hasattr(resp, "embeddings") and resp.embeddings:
            for emb in resp.embeddings:
                v = np.array(emb.values, dtype=np.float32)
                norm = np.linalg.norm(v)
                v_norm = (v / norm if norm > 0 else v).tolist()
                all_vecs.append(v_norm)
        else:
            raise ValueError("No embeddings returned by API")
    return all_vecs


PROMPT_REPOINTER = """You are re-pointing a candidate Q&A item whose answer could not be found character-for-character in the source text due to minor punctuation, whitespace, or boundary issues.

Target Question: {question}
Attempted Answer: {attempted_answer}

Source text:
{source_text}

Task:
Find the EXACT passage in the source text that answers the question.
Copy it 100% CHARACTER-FOR-CHARACTER from the source text with ZERO alterations.
If a bullet list is extracted, include the introductory lead-in clause.

Return ONLY valid JSON:
{{"repaired_parts": ["exact text snippet 1", "exact text snippet 2"]}}
"""


def retry_pointer(client, item: dict, source_raw: str, source_norm: str) -> bool:
    for attempt in range(2):
        try:
            prev_parts = coerce_parts(item.get("answer_parts")) or []
            prompt = PROMPT_REPOINTER.format(
                question=item.get("question", ""),
                attempted_answer="\n".join(prev_parts),
                source_text=source_raw,
            )
            resp = client.models.generate_content(
                model=config.MODEL_PRO,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0,
                    response_mime_type="application/json",
                ),
            )
            data = parse_json_safely(resp.text)
            new_parts = data.get("repaired_parts", []) if isinstance(data, dict) else []
            if new_parts:
                all_found, parts, _, _ = verify_parts(new_parts, source_norm, source_raw)
                if all_found:
                    item["answer_parts"] = parts
                    item["repaired"] = True
                    return True
        except Exception as e:
            if attempt == 1:
                print(f"  Retry pointer error for {item.get('id')}: {e}")
    return False


def cosine_sim(v1, v2) -> float:
    a = np.array(v1, dtype=np.float32)
    b = np.array(v2, dtype=np.float32)
    return float(np.dot(a, b))


def main():
    start_time = time.time()
    print(f"[{datetime.now().isoformat()}] Starting build_items.py...")
    client = genai.Client(vertexai=True, project=config.PROJECT_ID, location=config.LOCATION)

    # --- Part A: Extract text with pymupdf ---
    print("\n--- Part A: Extracting text from PDFs ---")
    mg_doc = pymupdf.open(config.MEDICATION_GUIDE_PDF)
    mg_pages = [page.get_text("text") for page in mg_doc]
    mg_full_text = "\n".join(mg_pages)
    norm_mg_full_text = normalise(mg_full_text)
    norm_mg_pages = [normalise(p) for p in mg_pages]
    print(f"Medication Guide: {len(mg_pages)} pages, {len(mg_full_text)} characters extracted.")

    br_doc = pymupdf.open(config.BROCHURE_PDF)
    br_page_data = {}
    for p_num in config.BROCHURE_PAGES:
        p_idx = p_num - 1  # 0-indexed
        page = br_doc[p_idx]
        text = page.get_text("text")
        pix = page.get_pixmap(dpi=150)
        png_bytes = pix.tobytes("png")
        br_page_data[p_num] = {
            "text": text,
            "norm_text": normalise(text),
            "png_bytes": png_bytes,
        }
        print(f"Brochure PDF page {p_num} (index {p_idx}): {len(text)} chars, rendered {len(png_bytes)} bytes PNG.")

    # --- Part B: Generate drafts with MODEL_PRO ---
    print(f"\n--- Part B: Generating drafts with {config.MODEL_PRO} ---")
    items = []
    seen_ids = set()

    # 1. Medication Guide
    print("Generating items for Medication Guide...")
    mg_cache_file = os.path.join(config.DATA_DIR, ".cache_mg_items.json")
    raw_mg_items = []
    if os.path.exists(mg_cache_file):
        try:
            with open(mg_cache_file, "r", encoding="utf-8") as f:
                raw_mg_items = json.load(f)
            print(f"Loaded {len(raw_mg_items)} Medication Guide items from cache.")
        except Exception:
            raw_mg_items = []

    if not raw_mg_items:
        mg_prompt = PROMPT_GENERATE.replace("{DOCUMENT_TEXT}", mg_full_text)
        mg_resp = None
        for attempt in range(2):
            try:
                resp = client.models.generate_content(
                    model=config.MODEL_PRO,
                    contents=mg_prompt,
                    config=types.GenerateContentConfig(
                        temperature=0,
                        response_mime_type="application/json",
                    ),
                )
                mg_resp = parse_json_safely(resp.text)
                break
            except Exception as e:
                print(f"Warning: Attempt {attempt + 1} failed for Medication Guide generation: {e}")
                if attempt == 1:
                    raise

        raw_mg_items = extract_list(mg_resp, "items")
        try:
            with open(mg_cache_file, "w", encoding="utf-8") as f:
                json.dump(raw_mg_items, f, indent=2)
        except Exception as e:
            print(f"Warning: Could not save cache: {e}")

    print(f"Medication Guide generated {len(raw_mg_items)} candidate items.")

    for item in raw_mg_items:
        raw_id = item.get("id", "item")
        if not raw_id.startswith("mg-"):
            raw_id = f"mg-{raw_id}"
        # Ensure unique id
        item_id = raw_id
        suffix = 2
        while item_id in seen_ids:
            item_id = f"{raw_id}-{suffix}"
            suffix += 1
        seen_ids.add(item_id)

        # pdf_page for the Medication Guide is located in Part C from the final
        # verified parts (after repair); keep the model's page, if any, until then.
        model_page = item.get("pdf_page")
        found_p = model_page if isinstance(model_page, int) and not isinstance(model_page, bool) else None

        item_entry = {
            "id": item_id,
            "doc": "medication_guide",
            "question": item.get("question", ""),
            "paraphrases": item.get("paraphrases", []),
            "answer_parts": item.get("answer_parts", []),
            "citation": {
                "doc_title": "Medication Guide (rev. 4/2026)",
                "section": item.get("section", "Medication Guide"),
                "pdf_page": found_p,
                "printed_pages": None,
            },
            "topic": item.get("topic", "other"),
        }
        items.append(item_entry)

    # 2. Brochure
    for p_num, p_info in br_page_data.items():
        print(f"Generating items for Brochure page {p_num}...")
        br_cache_file = os.path.join(config.DATA_DIR, f".cache_br_items_{p_num}.json")
        raw_br_items = []
        if os.path.exists(br_cache_file):
            try:
                with open(br_cache_file, "r", encoding="utf-8") as f:
                    raw_br_items = json.load(f)
                print(f"Loaded {len(raw_br_items)} Brochure page {p_num} items from cache.")
            except Exception:
                raw_br_items = []

        if not raw_br_items:
            prompt_text = PROMPT_GENERATE.replace("{DOCUMENT_TEXT}", p_info["text"]) + "\n\n" + BROCHURE_RULES
            img_part = types.Part.from_bytes(data=p_info["png_bytes"], mime_type="image/png")

            br_resp = None
            for attempt in range(2):
                try:
                    resp = client.models.generate_content(
                        model=config.MODEL_PRO,
                        contents=[img_part, prompt_text],
                        config=types.GenerateContentConfig(
                            temperature=0,
                            response_mime_type="application/json",
                        ),
                    )
                    br_resp = parse_json_safely(resp.text)
                    break
                except Exception as e:
                    print(f"Warning: Attempt {attempt + 1} failed for Brochure page {p_num}: {e}")
                    if attempt == 1:
                        raise

            raw_br_items = extract_list(br_resp, "items")
            try:
                with open(br_cache_file, "w", encoding="utf-8") as f:
                    json.dump(raw_br_items, f, indent=2)
            except Exception as e:
                print(f"Warning: Could not save cache: {e}")

        print(f"Brochure page {p_num} generated {len(raw_br_items)} candidate items.")

        for item in raw_br_items:
            raw_id = item.get("id", "item")
            if not raw_id.startswith("br-"):
                raw_id = f"br-{raw_id}"
            item_id = raw_id
            suffix = 2
            while item_id in seen_ids:
                item_id = f"{raw_id}-{suffix}"
                suffix += 1
            seen_ids.add(item_id)

            printed_pages = item.get("printed_pages")
            if not printed_pages:
                if p_num == 4:
                    printed_pages = "6–7"
                elif p_num == 9:
                    printed_pages = "16–17"
                elif p_num == 11:
                    printed_pages = "20–21"
            printed_pages = normalise_printed_pages(printed_pages)

            item_entry = {
                "id": item_id,
                "doc": "brochure",
                "question": item.get("question", ""),
                "paraphrases": item.get("paraphrases", []),
                "answer_parts": item.get("answer_parts", []),
                "citation": {
                    "doc_title": "KESIMPTA brochure",
                    "section": item.get("section", "Brochure"),
                    "pdf_page": p_num,
                    "printed_pages": printed_pages,
                },
                "topic": item.get("topic", "other"),
            }
            items.append(item_entry)

    print(f"Total candidate items generated: {len(items)}")

    # --- Part C: Find in source (pure code) ---
    print("\n--- Part C: Verifying exact answer passages in source text ---")
    found_parts_sample = None
    phone_part_sample = None

    for item in items:
        if item["doc"] == "medication_guide":
            source_norm = norm_mg_full_text
        else:
            p_num = item["citation"]["pdf_page"]
            source_norm = br_page_data[p_num]["norm_text"]

        raw_src = mg_full_text if item["doc"] == "medication_guide" else br_page_data[item["citation"]["pdf_page"]]["text"]
        found_in_source, answer_parts, not_found_parts, verify_notes = verify_parts(
            item.get("answer_parts"), source_norm, raw_src
        )
        item["answer_parts"] = answer_parts

        # Automated repair with retry_pointer if not found
        if not found_in_source:
            raw_src = mg_full_text if item["doc"] == "medication_guide" else br_page_data[item["citation"]["pdf_page"]]["text"]
            if retry_pointer(client, item, raw_src, source_norm):
                answer_parts = item["answer_parts"]
                not_found_parts = []
                verify_notes = []
                found_in_source = True

        if found_in_source:
            for part in answer_parts:
                norm_part = normalise(part)
                if found_parts_sample is None and len(norm_part.split()) >= 5:
                    found_parts_sample = (part, source_norm)
                if phone_part_sample is None and re.search(r"\d{3}[-\s]\d{3}[-\s]\d{4}", part):
                    phone_part_sample = (part, source_norm)

        notes = list(dict.fromkeys(verify_notes))

        # Medication Guide pdf_page: page containing the first final verified part
        if item["doc"] == "medication_guide":
            located_p = None
            if found_in_source and answer_parts:
                norm_first = normalise(answer_parts[0])
                for idx, np_text in enumerate(norm_mg_pages):
                    if norm_first in np_text:
                        located_p = idx + 1
                        break
            if located_p is not None:
                item["citation"]["pdf_page"] = located_p
            elif item["citation"].get("pdf_page") is not None:
                notes.append("PDF_PAGE_FROM_MODEL")
            else:
                item["citation"]["pdf_page"] = 1
                notes.append("PDF_PAGE_UNKNOWN_DEFAULTED_TO_1")

        # Section heading is shown to patients: it must come from the source text
        section = item["citation"].get("section") or ""
        norm_section = normalise(section) if isinstance(section, str) else ""
        section_verified = bool(norm_section) and norm_section in source_norm
        if not section_verified:
            item["citation"]["section"] = ""

        item["checks"] = {
            "found_in_source": found_in_source,
            "not_found_parts": not_found_parts,
            "repaired": item.get("repaired", False),
            "section_verified": section_verified,
            "notes": notes,
        }

        # Build display text for found items
        if found_in_source:
            formatted_parts = [format_answer_part(p) for p in answer_parts]
            item["answer"] = "\n".join(formatted_parts)
        else:
            # Fallback join without claiming verified formatting
            item["answer"] = "\n".join(answer_parts)

    found_count = sum(1 for item in items if item["checks"]["found_in_source"])
    print(f"Verification complete: {found_count}/{len(items)} items found word-for-word in source.")

    # Self-test: copy one found part, change one word, and one digit of a phone number; both must NOT be found.
    print("\n--- Running sabotage self-test ---")
    if found_parts_sample:
        orig_part, src = found_parts_sample
        # Sabotage one word
        words = orig_part.split()
        if words:
            sabotaged_words = list(words)
            sabotaged_words[len(words) // 2] = "SABOTAGEDWORD"
            sabotaged_part = " ".join(sabotaged_words)
            res_word = normalise(sabotaged_part) in src
            print(f"Sabotage check 1 (changed word): found={res_word} -> {'PASS (NOT FOUND)' if not res_word else 'FAIL'}")
    else:
        print("Warning: No found part sample for sabotage check 1")

    # If no phone part found yet in sample, find one in mg_full_text
    if not phone_part_sample:
        for item in items:
            for p in item.get("answer_parts", []):
                if re.search(r"\d{3}[-\s]\d{3}[-\s]\d{4}", p):
                    src = norm_mg_full_text if item["doc"] == "medication_guide" else br_page_data[item["citation"]["pdf_page"]]["norm_text"]
                    phone_part_sample = (p, src)
                    break
            if phone_part_sample:
                break

    if phone_part_sample:
        orig_phone_part, src = phone_part_sample
        # Sabotage one digit of a phone number
        match = re.search(r"\d{3}[-\s]\d{3}[-\s]\d{4}", orig_phone_part)
        if match:
            orig_match = match.group(0)
            # change first digit: if '1' make '9', else '1'
            new_digit = "9" if orig_match[0] != "9" else "8"
            sabotaged_phone = new_digit + orig_match[1:]
            sabotaged_phone_part = orig_phone_part[:match.start()] + sabotaged_phone + orig_phone_part[match.end():]
            res_phone = normalise(sabotaged_phone_part) in src
            print(f"Sabotage check 2 (changed phone digit {orig_match} -> {sabotaged_phone}): found={res_phone} -> {'PASS (NOT FOUND)' if not res_phone else 'FAIL'}")
        else:
            print("Warning: Could not isolate phone match for sabotage check 2")
    else:
        print("Note: No phone number in generated answer parts to sabotage.")

    # --- Part D: Code checks ---
    print("\n--- Part D: Code checks (placeholders, embeddings, retrieval self-test) ---")
    placeholder_count = 0
    for item in items:
        # placeholder: answer contains text in [square brackets] (regex \[[^\]]+\])
        has_placeholder = bool(re.search(r"\[[^\]]+\]", item["answer"]))
        item["checks"]["placeholder"] = has_placeholder
        if has_placeholder:
            placeholder_count += 1

    print(f"Placeholder check: {placeholder_count} items flagged with [square brackets].")

    # Embeddings: question + paraphrases
    print("Generating embeddings for all questions and paraphrases...")
    all_texts_to_embed = []
    item_text_indices = []  # list of (start_idx, end_idx)

    for item in items:
        texts = [item["question"]] + item.get("paraphrases", [])
        start = len(all_texts_to_embed)
        all_texts_to_embed.extend(texts)
        item_text_indices.append((start, len(all_texts_to_embed)))

    all_embeddings = get_embedding_batch(client, all_texts_to_embed)

    for i, item in enumerate(items):
        start, end = item_text_indices[i]
        item["embeddings"] = all_embeddings[start:end]

    # Retrieval self-test
    # for each paraphrase of an item, score all items using every stored vector EXCEPT that paraphrase's own vector;
    # passed if best item is this item and score >= ACCEPT_THRESHOLD.
    # Record passed/total and misses [{paraphrase, best_item, score}].
    print("Running retrieval self-test...")
    total_paraphrases = 0
    passed_paraphrases = 0

    for i, item in enumerate(items):
        paraphrases = item.get("paraphrases", [])
        p_passed = 0
        p_total = len(paraphrases)
        misses = []

        # Vector 0 is question, vectors 1..p_total are paraphrases
        for p_idx, p_text in enumerate(paraphrases):
            p_vec = item["embeddings"][1 + p_idx]

            best_item_id = None
            best_score = -1.0

            for j, candidate in enumerate(items):
                cand_vecs = candidate["embeddings"]
                for v_idx, c_vec in enumerate(cand_vecs):
                    # Exclude the paraphrase's own vector
                    if i == j and v_idx == (1 + p_idx):
                        continue
                    score = cosine_sim(p_vec, c_vec)
                    if score > best_score:
                        best_score = score
                        best_item_id = candidate["id"]

            if best_item_id == item["id"] and best_score >= config.ACCEPT_THRESHOLD:
                p_passed += 1
            else:
                misses.append({
                    "paraphrase": p_text,
                    "best_item": best_item_id,
                    "score": round(best_score, 4),
                })

        item["checks"]["retrieval_self_test"] = {
            "passed": p_passed,
            "total": p_total,
            "misses": misses,
        }
        total_paraphrases += p_total
        passed_paraphrases += p_passed

    pass_rate = (passed_paraphrases / total_paraphrases * 100) if total_paraphrases > 0 else 0
    print(f"Retrieval self-test: {passed_paraphrases}/{total_paraphrases} ({pass_rate:.1f}%) passed.")

    # --- Part E: Judge (MODEL_PRO) ---
    print(f"\n--- Part E: Judging items with {config.MODEL_PRO} ---")
    # Items not found in source get verdict "fail", reason "Not found in the source document." without a model call.
    found_items = [it for it in items if it["checks"]["found_in_source"]]
    not_found_items = [it for it in items if not it["checks"]["found_in_source"]]

    for it in not_found_items:
        it["judge"] = {
            "verdict": "fail",
            "checks": {
                "answers_question": False,
                "self_contained": False,
                "complete": False,
                "placeholder": it["checks"]["placeholder"],
                "advice_risk": False,
                "paraphrases_ok": False,
                "overlap": False,
            },
            "reason": "Not found in the source document.",
            "suggestion": "Verify citation passage against document text.",
        }

    # Judge found items in batches of ~10
    batch_size = 10
    judge_results_map = {}

    for b_idx in range(0, len(found_items), batch_size):
        batch = found_items[b_idx:b_idx + batch_size]
        print(f"Judging batch {b_idx // batch_size + 1} ({len(batch)} items)...")

        # Prepare evidence JSON
        evidence_list = []
        doc_texts_used = set()
        for it in batch:
            evidence_list.append({
                "id": it["id"],
                "question": it["question"],
                "paraphrases": it["paraphrases"],
                "answer": it["answer"],
                "section": it["citation"]["section"],
                "evidence": {
                    "found_in_source": it["checks"]["found_in_source"],
                    "placeholder": it["checks"]["placeholder"],
                    "retrieval_self_test": it["checks"]["retrieval_self_test"],
                },
            })
            if it["doc"] == "medication_guide":
                doc_texts_used.add(mg_full_text)
            else:
                p_num = it["citation"]["pdf_page"]
                doc_texts_used.add(br_page_data[p_num]["text"])

        combined_doc_text = "\n\n--- NEXT SECTION / PAGE ---\n\n".join(doc_texts_used)
        judge_prompt = (
            PROMPT_JUDGE
            .replace("{DOCUMENT_TEXT}", combined_doc_text)
            .replace("{ITEMS_JSON}", json.dumps(evidence_list, indent=2))
        )

        for attempt in range(2):
            try:
                resp = client.models.generate_content(
                    model=config.MODEL_PRO,
                    contents=judge_prompt,
                    config=types.GenerateContentConfig(
                        temperature=0,
                        response_mime_type="application/json",
                    ),
                )
                parsed = parse_json_safely(resp.text)
                for rev in extract_list(parsed, "reviews"):
                    if isinstance(rev, dict) and "id" in rev:
                        judge_results_map[rev["id"]] = rev
                break
            except Exception as e:
                print(f"Warning: Judge batch {b_idx // batch_size + 1} attempt {attempt + 1} failed: {e}")
                if attempt == 1:
                    # Provide fallback concern verdict so pipeline continues safely
                    for it in batch:
                        if it["id"] not in judge_results_map:
                            judge_results_map[it["id"]] = {
                                "id": it["id"],
                                "verdict": "concern",
                                "checks": {
                                    "answers_question": None,
                                    "self_contained": None,
                                    "complete": None,
                                    "placeholder": None,
                                    "advice_risk": None,
                                    "paraphrases_ok": None,
                                    "overlap": None,
                                },
                                "reason": "AI review unavailable",
                                "suggestion": "Inspect manually in Review screen.",
                            }

    for it in found_items:
        rev = judge_results_map.get(it["id"])
        if rev:
            it["judge"] = {
                "verdict": rev.get("verdict", "concern"),
                "checks": rev.get("checks", {}),
                "reason": rev.get("reason", ""),
                "suggestion": rev.get("suggestion", ""),
            }
        else:
            it["judge"] = {
                "verdict": "concern",
                "checks": {},
                "reason": "Pending judge evaluation",
                "suggestion": "Review item manually",
            }

    # Count judge verdicts
    judge_counts = {"pass": 0, "concern": 0, "fail": 0}
    for it in items:
        v = it.get("judge", {}).get("verdict", "concern")
        judge_counts[v] = judge_counts.get(v, 0) + 1

    # --- Part F: Persistence & State Merging ---
    print("\n--- Part F: Saving items to data/items.json ---")
    existing_items_map = {}
    if os.path.exists(config.ITEMS_JSON):
        try:
            with open(config.ITEMS_JSON, "r", encoding="utf-8") as f:
                old_data = json.load(f)
                for old_it in old_data.get("items", []):
                    existing_items_map[old_it["id"]] = old_it
            print(f"Loaded {len(existing_items_map)} existing items from {config.ITEMS_JSON}.")
        except Exception as e:
            print(f"Warning: Could not load existing items.json: {e}")

    def review_fingerprint(x: dict) -> str:
        cite = x.get("citation") or {}
        paras = x.get("paraphrases") or []
        if not isinstance(paras, list):
            paras = [paras]
        payload = {
            "question": x.get("question", ""),
            "paraphrases": sorted(str(p) for p in paras),
            "answer": x.get("answer", ""),
            "doc": x.get("doc", ""),
            "section": cite.get("section", ""),
            "pdf_page": cite.get("pdf_page"),
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()

    for it in items:
        old_it = existing_items_map.get(it["id"])
        if old_it and old_it.get("status") in ["approved", "rejected"]:
            # Keep the human decision only if the item is still verified and the
            # reviewed fields (question, paraphrases, answer, citation) are unchanged
            if not it["checks"]["found_in_source"] or review_fingerprint(it) != review_fingerprint(old_it):
                it["status"] = "pending"
                it["review"] = {
                    "reviewer": "",
                    "decision": "",
                    "reason_code": "",
                    "note": "SOURCE_CHANGED: needs re-approval",
                    "ts": datetime.now().isoformat(),
                }
            else:
                it["status"] = old_it.get("status", "pending")
                it["review"] = old_it.get("review", {
                    "reviewer": "",
                    "decision": "",
                    "reason_code": "",
                    "note": "",
                    "ts": "",
                })
        else:
            it["status"] = "pending"
            it["review"] = {
                "reviewer": "",
                "decision": "",
                "reason_code": "",
                "note": "",
                "ts": "",
            }

    build_seconds = round(time.time() - start_time, 2)
    output_data = {
        "built_at": datetime.now().isoformat(),
        "build_seconds": build_seconds,
        "items": items,
    }

    with open(config.ITEMS_JSON, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2)

    # Print summary
    mg_count = sum(1 for it in items if it["doc"] == "medication_guide")
    br_count = sum(1 for it in items if it["doc"] == "brochure")
    not_found_count = len(items) - found_count

    print("\n" + "=" * 50)
    print("BUILD_ITEMS SUMMARY:")
    print(f"Items per doc: Medication Guide = {mg_count}, Brochure = {br_count}")
    print(f"Found in source: {found_count} / {len(items)} (Not found: {not_found_count})")
    print(f"Placeholder count: {placeholder_count}")
    print(f"Retrieval self-test pass rate: {pass_rate:.1f}% ({passed_paraphrases}/{total_paraphrases})")
    print(f"Judge verdicts: Pass = {judge_counts.get('pass', 0)}, Concern = {judge_counts.get('concern', 0)}, Fail = {judge_counts.get('fail', 0)}")
    print(f"Total build time: {build_seconds} seconds")
    print(f"Saved to: {config.ITEMS_JSON}")
    print("=" * 50)


if __name__ == "__main__":
    main()
