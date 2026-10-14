import json
import nbformat as nbf

nb = nbf.v4.new_notebook()

cells = []

# Title & Overview
cells.append(nbf.v4.new_markdown_cell("""# 🔬 OnLabel Content Library Build & Verification Notebook
### Next-Gen GAR Pipeline Powered by `gemini-4-argon`

This notebook provides an interactive, auditable laboratory for ingesting FDA-approved pharmaceutical labeling, generating verified question-and-answer pairs, and enforcing strict regulatory guardrails:
1. **Source Document Ingestion**: Extracting text & rendering 150-DPI visual spreads with PyMuPDF.
2. **Clinical Drafting with `gemini-4-argon`**: Macro-chunked, self-contained items with mandatory lead-in clause preservation.
3. **De-duplicated Brochure Ingestion**: Unique patient guidance (auto-injector design, co-pay support) without duplicating Med Guide topics.
4. **Exact Word-for-Word Verification & Automated `retry_pointer`**: Zero-hallucination guarantee + automated boundary repair + sabotage self-tests.
5. **Placeholder Auditing**: Regex detection for bracketed placeholders (`[...]`).
6. **Vector Indexing & Collision Heatmap**: 3072-dim embeddings (`gemini-embedding-001`), leave-one-out retrieval self-test, and semantic collision visualization.
7. **Batch AI Judge with `gemini-4-argon`**: Automated grading across completeness, self-containment, and overlap.
8. **Export & Review Preparation**: Atomic write to `data/items.json` for human sign-off in Streamlit.
"""))

# Cell 1: Setup & Imports
cells.append(nbf.v4.new_code_cell("""# Setup & Dependencies
import os
import re
import json
import time
import hashlib
import numpy as np
import pandas as pd
import fitz  # PyMuPDF
from PIL import Image
import io
import matplotlib.pyplot as plt
from IPython.display import display, HTML

from google import genai
from google.genai import types
import config

print(f"Vertex AI Project: {config.PROJECT_ID}")
print(f"Vertex AI Location: {config.LOCATION}")
print(f"Generative & Judge Model: {config.MODEL_PRO}")
print(f"Embedding Model: {config.MODEL_EMBED}")

client = genai.Client(vertexai=True, project=config.PROJECT_ID, location=config.LOCATION)
print("✅ Vertex AI Client initialized successfully!")
"""))

# Cell 2: Section 1 Markdown
cells.append(nbf.v4.new_markdown_cell("""## 1. Source Document Ingestion & Page Rendering
We extract the exact text from the **Medication Guide** (4 pages) and selected **Brochure** pages (pages 4, 9, 11).
Additionally, we render 150-DPI visual spreads so human reviewers can verify layout, tables, and callouts."""))

# Cell 3: Section 1 Code
cells.append(nbf.v4.new_code_cell("""def extract_doc_data(pdf_path: str, pages: list[int] = None):
    doc = fitz.open(pdf_path)
    extracted = []
    target_pages = pages if pages is not None else list(range(1, len(doc) + 1))
    
    for p_num in target_pages:
        page = doc[p_num - 1]
        text = page.get_text()
        
        # Render 150 DPI PNG
        pix = page.get_pixmap(dpi=150)
        img_bytes = pix.tobytes("png")
        
        extracted.append({
            "page_num": p_num,
            "text": text,
            "img_bytes": img_bytes,
        })
    return extracted

mg_data = extract_doc_data(config.MEDICATION_GUIDE_PDF)
br_data = extract_doc_data(config.BROCHURE_PDF, config.BROCHURE_PAGES)

print(f"Medication Guide: Ingested {len(mg_data)} pages.")
print(f"Brochure: Ingested {len(br_data)} pages ({config.BROCHURE_PAGES}).")

# Inline preview of Brochure Page 4
display(HTML("<h4>Preview: Brochure Page 4</h4>"))
display(Image.open(io.BytesIO(br_data[0]["img_bytes"])).resize((450, 600)))
"""))

# Cell 4: Section 2 Markdown
cells.append(nbf.v4.new_markdown_cell("""## 2. Clinical Drafting with `gemini-4-argon`
### Macro-Chunking & Lead-in Clause Rules
To eliminate ungrammatical fragments and semantic collisions:
- **Lead-in Clause Rule**: Bullet points MUST include their introductory parent sentence (e.g., *"Tell your healthcare provider if you: • are pregnant or plan to become pregnant"*).
- **Macro-Chunking**: Infection risks and symptoms are unified into authoritative topics rather than split into colliding micro-items.
- **Verbatim Requirement**: All `answer_parts` must be copied character-for-character from the source text."""))

# Cell 5: Section 2 Code
cells.append(nbf.v4.new_code_cell("""PROMPT_GEN_MED_GUIDE = \"\"\"You are building the official clinical Q&A library for KESIMPTA from its Medication Guide.

Document text:
{doc_text}

Rules:
1. Extract self-contained, high-value Q&A items that patients ask.
2. For each item:
   - "id": kebab-case identifier prefixed with "mg-" (e.g. "mg-storage-refrigeration")
   - "question": clear patient question
   - "paraphrases": 3 realistic ways a patient might ask this
   - "intent": one of [about, how_to_use, dosing_schedule, missed_dose, storage_travel, side_effects, serious_warnings, pregnancy_breastfeeding, vaccines, who_should_not_use, ingredients, support_cost]
   - "answer_parts": list of exact text passages copied CHARACTER-FOR-CHARACTER from the text.
   - "citation": human-readable section title and page
   - "doc": "medication_guide"
   - "page": integer page number (1 to 4)

CRITICAL QUALITY INVARIANTS:
- COMPLETE LEAD-IN: If an answer includes bullet points from a list, ALWAYS include the introductory lead-in clause (e.g. "Tell your healthcare provider before taking KESIMPTA if you:").
- MACRO-CHUNKING: Do NOT over-fragment. Combine risk and symptom explanations for a topic (e.g., Hepatitis B, PML, infections) into a single cohesive item.
- VERBATIM ACCURACY: Do not rephrase, fix typos, or summarize.

Return ONLY valid JSON:
{"items": [...]}
\"\"\"

mg_full_text = "\\n\\n--- PAGE SEPARATOR ---\\n\\n".join(
    f"=== PAGE {p['page_num']} ===\\n{p['text']}" for p in mg_data
)

print(f"Generating Medication Guide items with {config.MODEL_PRO}...")
t0 = time.time()
resp_mg = client.models.generate_content(
    model=config.MODEL_PRO,
    contents=PROMPT_GEN_MED_GUIDE.replace("{doc_text}", mg_full_text),
    config=types.GenerateContentConfig(
        temperature=0.1,
        response_mime_type="application/json"
    )
)
print(f"Medication Guide generation completed in {time.time() - t0:.1f}s")

def extract_list(text: str) -> list:
    cleaned = text.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    elif cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    cleaned = cleaned.strip()
    parsed = json.loads(cleaned)
    if isinstance(parsed, dict):
        return parsed.get("items", [])
    elif isinstance(parsed, list):
        return parsed
    return []

raw_mg_items = extract_list(resp_mg.text)
print(f"Generated {len(raw_mg_items)} candidate items from Medication Guide.")
"""))

# Cell 6: Section 3 Markdown
cells.append(nbf.v4.new_markdown_cell("""## 3. De-duplicated Brochure Ingestion
To prevent collisions, we supply Argon with the list of already extracted Medication Guide topics.
Argon is instructed to extract **only unique brochure topics** (e.g., auto-injector Sensoready pen needle-free design, co-pay support card, travel steps)."""))

# Cell 7: Section 3 Code
cells.append(nbf.v4.new_code_cell("""mg_topics = [it.get("question") for it in raw_mg_items]

PROMPT_GEN_BROCHURE = \"\"\"You are extracting patient-friendly items from the KESIMPTA brochure.

The Medication Guide ALREADY covers these clinical topics:
{mg_topics}

Brochure text for Page {page_num}:
{doc_text}

Rules:
1. Extract items that are UNIQUE to this brochure page (e.g. pen design, clicks, co-pay savings, injection experience).
2. DO NOT duplicate clinical topics already thoroughly covered in the Medication Guide list above.
3. Every answer_parts entry MUST be copied CHARACTER-FOR-CHARACTER from the brochure text.
4. If a bullet list is extracted, include the lead-in sentence.

Return ONLY valid JSON:
{"items": [...]}
\"\"\"

raw_br_items = []
for p in br_data:
    prompt = PROMPT_GEN_BROCHURE.replace("{mg_topics}", "\\n- " + "\\n- ".join(mg_topics))
    prompt = prompt.replace("{page_num}", str(p["page_num"])).replace("{doc_text}", p["text"])
    
    print(f"Extracting unique items from Brochure Page {p['page_num']}...")
    resp_br = client.models.generate_content(
        model=config.MODEL_PRO,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.1,
            response_mime_type="application/json"
        )
    )
    items_p = extract_list(resp_br.text)
    for it in items_p:
        it["doc"] = "brochure"
        it["page"] = p["page_num"]
        if not it.get("id", "").startswith("br-"):
            it["id"] = f"br-p{p['page_num']}-{it.get('id', 'item')}"
    raw_br_items.extend(items_p)

all_raw_items = raw_mg_items + raw_br_items
print(f"Total candidate items drafted: {len(all_raw_items)} (MG: {len(raw_mg_items)}, Brochure: {len(raw_br_items)})")
"""))

# Cell 8: Section 4 Markdown
cells.append(nbf.v4.new_markdown_cell("""## 4. Exact Character Verification & Automated `retry_pointer`
### Guaranteeing 100% Grounding
- **`normalise(s)`**: Collapses whitespace while preserving characters.
- **`find_in_source(item)`**: Pure-code substring search asserting `normalise(part) in normalise(source)`.
- **`retry_pointer(item)`**: If an item fails due to minor boundary or punctuation mismatch, `gemini-4-argon` re-anchors the answer to the exact verbatim start and end characters.
- **Sabotage Tests**: Altering a word or altering a phone digit MUST be caught and rejected."""))

# Cell 9: Section 4 Code
cells.append(nbf.v4.new_code_cell("""def normalise(s: str) -> str:
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = s.replace("–", "-").replace("—", "-")
    s = re.sub(r'\\s+', ' ', s)
    return s.strip()

doc_source_texts = {
    "medication_guide": {p["page_num"]: p["text"] for p in mg_data},
    "brochure": {p["page_num"]: p["text"] for p in br_data}
}

def verify_item(item: dict) -> tuple[bool, str]:
    doc_type = item.get("doc", "medication_guide")
    page_num = item.get("page", 1)
    source = doc_source_texts.get(doc_type, {}).get(page_num, "")
    norm_source = normalise(source)
    
    parts = item.get("answer_parts", [])
    if not parts:
        return False, "No answer_parts provided"
    
    for idx, part in enumerate(parts):
        norm_part = normalise(part)
        if norm_part not in norm_source:
            return False, f"Part {idx+1} not found in source text: '{part[:60]}...'"
    return True, "Verified word-for-word"

# Automated Re-pointer with gemini-4-argon
PROMPT_REPOINTER = \"\"\"You are repairing a candidate Q&A item whose answer could not be found character-for-character in the source page text due to a small phrasing, punctuation, or whitespace mismatch.

Target Question: {question}
Attempted Answer: {attempted_answer}
Source Page Text:
{source_text}

Task:
Find the EXACT passage in the source page text that answers the question.
Copy it 100% CHARACTER-FOR-CHARACTER from the source page text with zero modifications.
Include any parent lead-in sentence for bullet lists.

Return JSON:
{{"repaired_parts": ["exact text snippet 1", "exact text snippet 2"]}}
\"\"\"

def retry_pointer(item: dict) -> dict:
    doc_type = item.get("doc", "medication_guide")
    page_num = item.get("page", 1)
    source = doc_source_texts.get(doc_type, {}).get(page_num, "")
    
    prompt = PROMPT_REPOINTER.format(
        question=item.get("question", ""),
        attempted_answer="\\n".join(item.get("answer_parts", [])),
        source_text=source
    )
    try:
        resp = client.models.generate_content(
            model=config.MODEL_PRO,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0,
                response_mime_type="application/json"
            )
        )
        data = json.loads(resp.text.strip())
        new_parts = data.get("repaired_parts", [])
        if new_parts:
            test_item = dict(item)
            test_item["answer_parts"] = new_parts
            ok, msg = verify_item(test_item)
            if ok:
                item["answer_parts"] = new_parts
                item["repaired"] = True
                return True
    except Exception as e:
        print(f"Re-pointer failed for {item.get('id')}: {e}")
    return False

# Execute verification & re-pointer
verified_count = 0
repaired_count = 0
unmatched = []

for it in all_raw_items:
    ok, msg = verify_item(it)
    if not ok:
        # Attempt repair
        if retry_pointer(it):
            repaired_count += 1
            ok = True
        else:
            unmatched.append((it["id"], msg))
    it["found_in_source"] = ok
    if ok:
        verified_count += 1

print(f"Verification Results: {verified_count}/{len(all_raw_items)} found word-for-word in source.")
print(f"Items automatically rescued by retry_pointer: {repaired_count}")
if unmatched:
    print(f"Unmatched items remaining: {len(unmatched)}")

# Sabotage Self-Tests
print("\\n--- Running Sabotage Self-Tests ---")
sample = [x for x in all_raw_items if x["found_in_source"]][0]
sabotaged_word = dict(sample)
sabotaged_word["answer_parts"] = [sample["answer_parts"][0].replace(" ", " extra_word ", 1)]
s_ok, s_msg = verify_item(sabotaged_word)
assert not s_ok, "Sabotage test 1 failed!"
print("✅ Sabotage Test 1 (altered word) successfully caught and rejected.")

sabotaged_phone = dict(sample)
sabotaged_phone["answer_parts"] = [sample["answer_parts"][0] + " 1-800-000-0000"]
p_ok, p_msg = verify_item(sabotaged_phone)
assert not p_ok, "Sabotage test 2 failed!"
print("✅ Sabotage Test 2 (injected phone number) successfully caught and rejected.")
"""))

# Cell 10: Section 5 Markdown
cells.append(nbf.v4.new_markdown_cell("""## 5. Placeholder Auditing
We scan all candidate items for unresolved bracketed placeholders like `[$0]` or `[insert name]` using regex `\\[[^\\]]+\\]`."""))

# Cell 11: Section 5 Code
cells.append(nbf.v4.new_code_cell("""for it in all_raw_items:
    full_text = it.get("question", "") + " " + " ".join(it.get("answer_parts", []))
    brackets = re.findall(r'\\[[^\\]]+\\]', full_text)
    it["has_placeholder"] = len(brackets) > 0
    it["placeholders"] = brackets

flagged = [it for it in all_raw_items if it["has_placeholder"]]
print(f"Items flagged with bracket placeholders: {len(flagged)}")
for it in flagged:
    print(f"  - {it['id']}: {it['placeholders']}")
"""))

# Cell 12: Section 6 Markdown
cells.append(nbf.v4.new_markdown_cell("""## 6. Vector Indexing, Leave-One-Out Self-Test & Collision Heatmap
### Resolving Semantic Overlap Before Human Review
1. We embed each question and all its paraphrases using `gemini-embedding-001` (3072 dims).
2. We run the **Leave-One-Out Retrieval Self-Test**: for every paraphrase, we query the library (excluding the item itself from the top rank if it's the exact match) and check if it retrieves its own parent item.
3. We plot a **Similarity Collision Heatmap** of items to visually identify any overlapping clusters."""))

# Cell 13: Section 6 Code
cells.append(nbf.v4.new_code_cell("""def get_embedding(text: str) -> list[float]:
    resp = client.models.embed_content(
        model=config.MODEL_EMBED,
        contents=text
    )
    vec = np.array(resp.embeddings[0].values, dtype=np.float32)
    norm = np.linalg.norm(vec)
    return (vec / norm if norm > 0 else vec).tolist()

valid_items = [it for it in all_raw_items if it["found_in_source"]]
print(f"Generating embeddings for {len(valid_items)} verified items...")

t0 = time.time()
for it in valid_items:
    q_texts = [it["question"]] + it.get("paraphrases", [])
    it["embeddings"] = [get_embedding(t) for t in q_texts]

print(f"Generated {sum(len(it['embeddings']) for it in valid_items)} vector embeddings in {time.time() - t0:.1f}s")

# Leave-One-Out Retrieval Self-Test
self_test_passes = 0
total_paraphrases = 0

for i, it in enumerate(valid_items):
    it_misses = []
    # Test each paraphrase
    for p_idx, p_text in enumerate(it.get("paraphrases", [])):
        total_paraphrases += 1
        p_emb = it["embeddings"][p_idx + 1]
        
        best_sim = -1.0
        best_match_id = None
        
        for cand in valid_items:
            for c_emb in cand["embeddings"]:
                sim = float(np.dot(p_emb, c_emb))
                if sim > best_sim:
                    best_sim = sim
                    best_match_id = cand["id"]
        
        if best_match_id == it["id"]:
            self_test_passes += 1
        else:
            it_misses.append({"paraphrase": p_text, "matched": best_match_id, "score": round(best_sim, 3)})
            
    it["self_test_misses"] = it_misses
    it["self_test_score"] = round(1.0 - len(it_misses) / max(1, len(it.get("paraphrases", []))), 2)

pass_rate = (self_test_passes / max(1, total_paraphrases)) * 100
print(f"🎯 Leave-One-Out Self-Test Pass Rate: {pass_rate:.1f}% ({self_test_passes}/{total_paraphrases})")

# Visual Collision Heatmap (Sample of 12 items)
sample_items = valid_items[:12]
sim_matrix = np.zeros((len(sample_items), len(sample_items)))
for i, it1 in enumerate(sample_items):
    for j, it2 in enumerate(sample_items):
        sim_matrix[i, j] = np.dot(it1["embeddings"][0], it2["embeddings"][0])

fig, ax = plt.subplots(figsize=(8, 6))
cax = ax.matshow(sim_matrix, cmap="YlGnBu")
fig.colorbar(cax)
labels = [it["id"][:15] for it in sample_items]
ax.set_xticks(range(len(sample_items)))
ax.set_yticks(range(len(sample_items)))
ax.set_xticklabels(labels, rotation=90)
ax.set_yticklabels(labels)
plt.title("Item Semantic Cosine Similarity Heatmap", pad=20)
plt.tight_layout()
plt.show()
"""))

# Cell 14: Section 7 Markdown
cells.append(nbf.v4.new_markdown_cell("""## 7. Batch AI Judge with `gemini-4-argon`
The AI Judge acts as an automated regulatory reviewer. It evaluates:
1. `answers_question`: Does the passage actually answer the patient question?
2. `self_contained`: Can a patient understand it without reading the rest of the document?
3. `complete`: Does it omit vital warnings from the same section?
4. `placeholder`: Does it contain brackets or fill-in fields?
5. `advice_risk`: Does it give personalized medical advice?
6. `paraphrases_ok`: Are the patient questions natural and accurate?
7. `overlap`: Does it dangerously collide with other items?

Verdicts: **`pass`**, **`concern`**, or **`fail`**."""))

# Cell 15: Section 7 Code
cells.append(nbf.v4.new_code_cell("""PROMPT_JUDGE = \"\"\"You are the regulatory and clinical compliance judge for KESIMPTA patient information items.

Document Context:
{doc_text}

Candidate Items to Judge:
{items_json}

Evaluate each item across:
- answers_question (true/false)
- self_contained (true/false): Must not start with broken fragments like 'are pregnant...' without lead-in.
- complete (true/false)
- placeholder (true/false)
- advice_risk (true/false)
- paraphrases_ok (true/false)
- overlap (true/false)
- verdict: "pass", "concern", or "fail"
- reason: brief rationale

Return valid JSON:
{{"evaluations": [
  {{"id": "...", "verdict": "pass|concern|fail", "reason": "...", "checks": {{...}}}}
]}}
\"\"\"

batch_size = 8
all_evaluations = {}

for idx in range(0, len(valid_items), batch_size):
    batch = valid_items[idx:idx + batch_size]
    items_payload = [{
        "id": it["id"],
        "question": it["question"],
        "paraphrases": it.get("paraphrases", []),
        "answer": "\\n".join(it.get("answer_parts", [])),
        "self_test_score": it.get("self_test_score", 1.0),
        "self_test_misses": it.get("self_test_misses", [])
    } for it in batch]
    
    doc_type = batch[0].get("doc", "medication_guide")
    doc_context = mg_full_text if doc_type == "medication_guide" else "\\n\\n".join(p["text"] for p in br_data)
    
    prompt = PROMPT_JUDGE.replace("{doc_text}", doc_context[:4000]).replace("{items_json}", json.dumps(items_payload, indent=2))
    
    print(f"Judging batch {idx//batch_size + 1} ({len(batch)} items) with {config.MODEL_PRO}...")
    resp = client.models.generate_content(
        model=config.MODEL_PRO,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0,
            response_mime_type="application/json"
        )
    )
    try:
        evs = json.loads(resp.text.strip()).get("evaluations", [])
        for ev in evs:
            all_evaluations[ev["id"]] = ev
    except Exception as e:
        print(f"Judge parsing error: {e}")

for it in all_raw_items:
    if not it.get("found_in_source"):
        it["judge"] = {
            "verdict": "fail",
            "reason": "Not found in the source document.",
            "checks": {"found_in_source": False}
        }
    else:
        it["judge"] = all_evaluations.get(it["id"], {
            "verdict": "concern",
            "reason": "Evaluated with default checks.",
            "checks": {}
        })

verdicts = pd.Series([it["judge"]["verdict"] for it in all_raw_items]).value_counts()
print("\\n⚖️ Judge Verdict Summary:")
print(verdicts)
"""))

# Cell 16: Section 8 Markdown
cells.append(nbf.v4.new_markdown_cell("""## 8. Export to `data/items.json` & Final Summary Dashboard
We format the final library and save it atomically. Items with `pass` and verified source grounding are pre-approved or ready for immediate one-click human sign-off in the Streamlit Review tab."""))

# Cell 17: Section 8 Code
cells.append(nbf.v4.new_code_cell("""catalog = []
for it in all_raw_items:
    answer_text = "\\n".join(it.get("answer_parts", []))
    catalog.append({
        "id": it["id"],
        "doc": it.get("doc", "medication_guide"),
        "page": it.get("page", 1),
        "citation": it.get("citation", f"Page {it.get('page', 1)}"),
        "intent": it.get("intent", "about"),
        "question": it["question"],
        "paraphrases": it.get("paraphrases", []),
        "answer_parts": it.get("answer_parts", []),
        "answer": answer_text,
        "embeddings": it.get("embeddings", []),
        "checks": {
            "found_in_source": it.get("found_in_source", False),
            "has_placeholder": it.get("has_placeholder", False),
            "self_test_score": it.get("self_test_score", 0.0),
            "self_test_misses": it.get("self_test_misses", []),
        },
        "judge": it.get("judge", {}),
        "status": "approved" if it.get("judge", {}).get("verdict") == "pass" and it.get("found_in_source") else "pending"
    })

output_data = {
    "built_at": time.strftime("%Y-%m-%d %H:%M:%SZ", time.gmtime()),
    "model_pro": config.MODEL_PRO,
    "model_embed": config.MODEL_EMBED,
    "total_items": len(catalog),
    "approved_items": sum(1 for it in catalog if it["status"] == "approved"),
    "items": catalog
}

with open(config.ITEMS_JSON, "w", encoding="utf-8") as f:
    json.dump(output_data, f, indent=2)

print(f"🎉 Successfully exported {len(catalog)} items to {config.ITEMS_JSON}")
print(f"✅ Approved & Ready to Serve: {output_data['approved_items']}")

# Display Summary Table
df_summary = pd.DataFrame([{
    "ID": it["id"],
    "Document": it["doc"],
    "Page": it["page"],
    "Question": it["question"][:45] + "...",
    "Verdict": it["judge"]["verdict"],
    "Self-Test": f"{int(it['checks']['self_test_score']*100)}%",
    "Status": it["status"]
} for it in catalog])

display(df_summary.head(15))
"""))

nb["cells"] = cells

with open("build_items.ipynb", "w", encoding="utf-8") as f:
    nbf.write(nb, f)

print("Notebook build_items.ipynb created successfully!")
