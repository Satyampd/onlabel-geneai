import io
import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import pymupdf

import config
import templates
import pipeline

app = FastAPI(title="OnLabel API", description="GAR-based Patient Information Assistant")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory page image cache: (doc_name, pdf_page) -> bytes
PAGE_CACHE: dict[tuple[str, int], bytes] = {}


def get_rendered_page(doc_name: str, pdf_page: int) -> bytes:
    key = (doc_name, pdf_page)
    if key in PAGE_CACHE:
        return PAGE_CACHE[key]

    pdf_path = config.MEDICATION_GUIDE_PDF if doc_name == "medication_guide" else config.BROCHURE_PDF
    if not os.path.exists(pdf_path):
        raise HTTPException(status_code=404, detail=f"Document {doc_name} not found")

    try:
        doc = pymupdf.open(pdf_path)
        p_idx = max(0, min(pdf_page - 1, len(doc) - 1))
        page = doc[p_idx]
        pix = page.get_pixmap(dpi=150)
        png_bytes = pix.tobytes("png")
        PAGE_CACHE[key] = png_bytes
        return png_bytes
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to render page: {e}")


class ChatRequest(BaseModel):
    message: str
    session_id: str


@app.post("/api/chat")
def chat(req: ChatRequest):
    turn_result = pipeline.answer_turn(req.message, session_id=req.session_id)

    src = turn_result.get("source_page")
    source_page_url = None
    if src:
        source_page_url = f"/api/page/{src['doc']}/{src['pdf_page']}.png"

    return {
        "reply_text": turn_result["reply_text"],
        "kind": turn_result["kind"],
        "answer": turn_result["answer"],
        "citation": turn_result["citation"],
        "source_page_url": source_page_url,
        "figure": turn_result.get("figure"),
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
    }


@app.get("/api/page/{doc}/{pdf_page}.png")
def get_page(doc: str, pdf_page: int):
    png_bytes = get_rendered_page(doc, pdf_page)
    return Response(content=png_bytes, media_type="image/png")


# Serve figures
figures_dir = os.path.join(os.path.dirname(__file__), "data", "figures")
if os.path.exists(figures_dir):
    app.mount("/api/figures", StaticFiles(directory=figures_dir), name="figures")

# Serve frontend
web_dir = os.path.join(os.path.dirname(__file__), "web")
if os.path.exists(web_dir):
    app.mount("/static", StaticFiles(directory=web_dir), name="static")

    @app.get("/")
    def index():
        return FileResponse(
            os.path.join(web_dir, "index.html"),
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0",
            }
        )
