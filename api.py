import os
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from urllib.parse import quote

import config
import templates
import pipeline
import review
import source_view

app = FastAPI(title="OnLabel API", description="GAR-based Patient Information Assistant")

# No CORS middleware: the chat UI is served from this same origin.

# Source images are rendered by source_view: the approved PDF page itself, with the
# answer passage highlighted by code. Only the two known documents can be rendered.
IMAGE_CACHE: dict[tuple, bytes] = {}


def _approved_item(item_id: str) -> dict:
    for it in pipeline.load_approved_items():  # approved AND verified items only
        if it.get("id") == item_id:
            return it
    raise HTTPException(status_code=404, detail="Not found")


def _png(key: tuple, doc: str, pdf_page: int, parts=None, snippet=False) -> Response:
    if doc not in source_view.DOC_PATHS or not os.path.exists(source_view.DOC_PATHS[doc]):
        raise HTTPException(status_code=404, detail="Not found")
    if key not in IMAGE_CACHE:
        try:
            if len(IMAGE_CACHE) > 128:
                IMAGE_CACHE.clear()
            IMAGE_CACHE[key] = source_view.render(doc, pdf_page, parts, snippet=snippet)
        except (IndexError, KeyError):
            raise HTTPException(status_code=404, detail="Not found")
        except Exception:
            raise HTTPException(status_code=500, detail="Failed to render page")
    return Response(content=IMAGE_CACHE[key], media_type="image/png",
                    headers={"Cache-Control": "public, max-age=3600"})


class ChatRequest(BaseModel):
    message: str = Field(..., max_length=1000)
    session_id: str = Field(..., max_length=100)

    @field_validator("message")
    @classmethod
    def _strip_message(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("message must not be empty")
        return v


@app.post("/api/chat")
def chat(req: ChatRequest):
    turn_result = pipeline.answer_turn(req.message, session_id=req.session_id)

    # Relative URLs, so the UI also works behind a path-prefix proxy (Workbench, Code Editor).
    src = turn_result.get("source_page")
    source_page_url = snippet_url = None
    if src:
        item_id = quote(src["item_id"], safe="")
        source_page_url = f"api/page/{src['doc']}/{src['pdf_page']}.png?highlight={item_id}"
        snippet_url = f"api/snippet/{item_id}.png"

    return {
        "reply_text": turn_result["reply_text"],
        "kind": turn_result["kind"],
        "answer": turn_result["answer"],
        "citation": turn_result["citation"],
        "source_label": turn_result.get("source_label"),
        "snippet_url": snippet_url,
        "source_page_url": source_page_url,
        "approval": turn_result.get("approval"),
        "why": turn_result["why"],
        "latency_ms": turn_result["latency_ms"],
    }


@app.get("/api/meta")
def meta():
    safety_text = ""
    if os.path.exists(config.SAFETY_PANEL_TXT):
        with open(config.SAFETY_PANEL_TXT, "r", encoding="utf-8") as f:
            safety_text = f.read()

    return {
        "banner": templates.BANNER,
        "safety_panel": safety_text,
        "starters": templates.STARTERS,
        "error_text": templates.TEMPLATE_ERROR,
        "thresholds": {"accept": config.ACCEPT_THRESHOLD, "related": config.RELATED_THRESHOLD},
    }


@app.get("/api/page/{doc}/{pdf_page}.png")
def get_page(doc: str, pdf_page: int, highlight: str | None = None):
    """Full source page; with ?highlight=<approved item id>, its passage is highlighted."""
    if highlight:
        item = _approved_item(highlight)
        if item.get("doc") != doc or item.get("citation", {}).get("pdf_page") != pdf_page:
            raise HTTPException(status_code=404, detail="Not found")
        return _png(("page", doc, pdf_page, highlight), doc, pdf_page, item.get("answer_parts"))
    return _png(("page", doc, pdf_page), doc, pdf_page)


@app.get("/api/snippet/{item_id}.png")
def get_snippet(item_id: str):
    """Crop of the source page around an approved answer, with the passage highlighted."""
    item = _approved_item(item_id)
    cite = item.get("citation", {})
    return _png(("snippet", item_id), item["doc"], cite.get("pdf_page", 1),
                item.get("answer_parts"), snippet=True)


# ---------------------------------------------------------------------------
# Reviewer console API (web/console.html). Prototype: no login, as for the Streamlit
# console. The approval rules are in review.py and are checked again on every save.
# ---------------------------------------------------------------------------
class DecisionRequest(BaseModel):
    decision: str = Field(..., pattern="^(approved|rejected)$")
    reviewer: str = Field(..., min_length=1, max_length=80)
    reason_code: str = Field("", max_length=40)
    note: str = Field("", max_length=500)


class AckRequest(BaseModel):
    id: str = Field(..., max_length=200)
    reviewer: str = Field(..., min_length=1, max_length=80)


def _any_item(item_id: str) -> dict:
    for it in review.load_items_data().get("items", []):
        if it.get("id") == item_id:
            return it
    raise HTTPException(status_code=404, detail="Not found")


@app.get("/api/console/items")
def console_items():
    data = review.load_items_data()
    items = data.get("items", [])
    return {
        "summary": review.summary(items),
        "built_at": data.get("built_at", ""),
        "build_seconds": data.get("build_seconds", 0),
        "reject_codes": review.REJECT_CODES,
        "items": [review.public_item(it) for it in items],
    }


@app.post("/api/console/items/{item_id}/decision")
def console_decide(item_id: str, req: DecisionRequest):
    try:
        item = review.record_decision(item_id, req.decision, req.reviewer, req.reason_code, req.note)
    except KeyError:
        raise HTTPException(status_code=404, detail="Not found")
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"item": review.public_item(item), "summary": review.summary(review.load_items_data().get("items", []))}


def _item_png(item: dict, snippet: bool) -> Response:
    # Any item, for review. The passage is highlighted only if it was verified in the source.
    cite = item.get("citation", {})
    parts = item.get("answer_parts") if item.get("checks", {}).get("found_in_source") is True else None
    key = ("review", item["id"], snippet, tuple(parts or ()))
    return _png(key, item.get("doc"), cite.get("pdf_page", 1), parts, snippet=snippet and bool(parts))


@app.get("/api/console/snippet/{item_id}.png")
def console_snippet(item_id: str):
    return _item_png(_any_item(item_id), snippet=True)


@app.get("/api/console/page/{item_id}.png")
def console_page(item_id: str):
    return _item_png(_any_item(item_id), snippet=False)


@app.get("/api/console/reports")
def console_reports():
    reports = review.safety_reports(review.load_logs())
    return {"open": sum(1 for r in reports if r.get("report_status") == "open"), "reports": reports}


@app.post("/api/console/reports/ack")
def console_ack(req: AckRequest):
    try:
        return review.acknowledge(req.id, req.reviewer)
    except KeyError:
        raise HTTPException(status_code=404, detail="Not found")
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@app.get("/api/console/activity")
def console_activity():
    logs = review.load_logs()
    return {"unanswered": len(review.unanswered(logs)), "turns": review.activity(logs)}


@app.post("/api/console/gaps")
def console_gaps():
    messages = review.unanswered(review.load_logs())
    if not messages:
        return {"sample": True, "count": 0, "themes": []}
    try:
        themes = review.content_gaps(messages[-200:])
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Could not group the questions right now ({type(e).__name__})")
    return {"sample": False, "count": len(messages), "themes": themes}


# Serve frontend
web_dir = os.path.join(os.path.dirname(__file__), "web")
if os.path.exists(web_dir):
    app.mount("/static", StaticFiles(directory=web_dir), name="static")

    def _page(name: str) -> FileResponse:
        return FileResponse(
            os.path.join(web_dir, name),
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0",
            }
        )

    @app.get("/")
    def index():
        return _page("index.html")

    @app.get("/console")
    def console_page_html():
        return _page("console.html")
