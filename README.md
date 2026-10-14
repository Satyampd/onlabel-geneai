# OnLabel: the AI assistant that never goes off-label

A Novartis AI Hackathon 2026 prototype built on Google Cloud (Vertex AI, Gemini).

OnLabel answers patient questions about a medicine **only with text a human has approved, shown word for word, with its source page**. No model writes the words a patient reads.

> Prototype for a hackathon demo, not for patient use. It uses public KESIMPTA information only (Medication Guide rev. 4/2026, patient brochure). Reports entered in the prototype are not sent to Novartis.

## The method: GAR (Generate → Approve → Retrieve), RAG reversed
| | RAG | GAR (OnLabel) |
|---|---|---|
| Where AI writes text | Live, in front of the user | Offline, before human review |
| What the user sees | Newly generated text | Only approved text, word for word |

1. **Generate** (`build_items.py`): Gemini reads the documents, including page images for the brochure, and drafts patient questions. It *points* to the exact answer passages. Code then proves every passage exists word for word in the source text, and drops anything it can't find.
2. **Approve** (reviewer console at `/console`; `app.py` Review tab as a backup): Gemini reviews each draft with evidence (completeness, draft placeholders, a retrieval self-test). A **named human** approves or rejects each item. Items that are unverified, contain placeholders, or failed the AI review can't be approved.
3. **Retrieve** (`pipeline.py`, `api.py`, `web/`): for every question, two steps run first:
   - a **safety word scan in code** (it can only raise severity)
   - a **Gemini triage** call, which only classifies

   Then:
   - **Normal questions** get the best-matching approved answer (Gemini embeddings), word for word, with a crop of the real source page where code has highlighted that exact passage. The brochure is the primary source: on a near-tie its answer is preferred over the Medication Guide.
   - **Personal-advice questions** are declined.
   - **Side effects, pregnancy during treatment, product complaints and emergencies** get fixed safety messages and are logged for a person to acknowledge.
   - **Errors fail safe:** the fixed error message is shown, and if the safety scan fired, the safety message is still shown.
4. **Insights** (reviewer console: Safety reports, Content gaps, Activity log): safety reports wait for a named person to acknowledge them. Gemini groups unanswered questions into content gaps (internal analytics only).

## Run it
```bash
pip install -r requirements.txt
# .env: PROJECT_ID, LOCATION, MODEL_PRO, MODEL_FLASH, MODEL_EMBED (see config.py for defaults)
python smoke_test.py                      # Gemini + embeddings + PDF access
python build_items.py                     # Generate + automatic checks -> data/items.json
uvicorn api:app --port 8080               # patient chat at /, reviewer console at /console
streamlit run app.py                      # backup reviewer console (Review / Chat / Insights)
python run_eval.py eval_v2.csv            # test set -> summary + threshold sweep
```

## Files
| File | Role |
|---|---|
| `build_items.py` | Generate: extraction, Gemini drafting, find-in-source check, judge, embeddings, retrieval self-test |
| `pipeline.py` | Retrieve: safety scan, triage, matching, fixed replies, audit log |
| `source_view.py` | Renders the approved source page with the answer passage highlighted (located by code, not by a model) |
| `recheck_items.py` | Re-runs the code checks on an existing `items.json` without calling Gemini |
| `templates.py` | Every fixed reply text the patient can see |
| `review.py` | Approval rules, saving decisions, safety-report acknowledgement, content gaps (shared by both consoles) |
| `api.py` | API for the patient chat and the reviewer console, including highlighted source snippets |
| `web/index.html`, `app.css`, `app.js` | Patient chat, with the "How OnLabel decided" panel |
| `web/console.html`, `console.css`, `console.js` | Reviewer console: review queue, safety reports, content gaps, activity log |
| `web/theme.css` | Shared look of both pages |
| `app.py` | Backup reviewer console in Streamlit |
| `run_eval.py`, `eval_v2.csv` | Test set and evaluation |
| `data/` | Source PDFs, `items.json` (Q&A + checks + reviews), `log.jsonl` (audit trail) |

## Safety rules
| Zone | Meaning | Response |
|---|---|---|
| Green | General factual question | Approved answer, word for word, with its source (or "no approved answer") |
| Yellow | Personal decision or advice | Polite decline, referral to the healthcare provider |
| Red | Urgent, side effect, pregnancy during treatment, product complaint | Fixed safety message + report for human acknowledgement |
| Off-topic | Not about the medicine | Redirect |

The general rules:
- Red beats everything.
- The safety word scan can only raise severity.
- When unsure: red rather than anything else, and yellow rather than green.

## Limitations (prototype)
- **No auth:** no login or access control on the reviewer console or the API. The reviewer name is typed in, not verified.
- **Personal data:** chat messages are logged without personal-data handling.
- **Small test set:** written by the team. Thresholds are tuned on it.
- **Public documents only.** It isn't connected to real review or safety-reporting systems.
- **Single process:** local JSON files, not built for concurrent multi-user writes.
