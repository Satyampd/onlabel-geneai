import os
import json
import time
import pymupdf as fitz
from google import genai
from google.genai import types
import config

PROMPT_EXTRACT_FIGURES = """
Analyze this page from a pharmaceutical document.
Identify any major instructional diagrams, comparison charts, or important graphical feature callouts that would be highly useful as standalone visual aids for patients.
Do NOT include logos, plain text paragraphs, continuous backgrounds, or purely decorative elements.

For each figure, provide:
- "id": a unique kebab-case ID (e.g. "fig-pen-diagram")
- "caption": a brief description of what the figure shows
- "bbox": its bounding box as [ymin, xmin, ymax, xmax] using normalized coordinates from 0 to 1000 representing the page dimensions. (e.g. if it covers the top left quarter, [0, 0, 500, 500]). Ensure the box tightly wraps the text and graphic of the figure.

Return ONLY valid JSON:
{"figures": [
  {"id": "...", "caption": "...", "bbox": [ymin, xmin, ymax, xmax]}
]}
"""

def extract_figures_from_pdf(client, pdf_path: str, doc_name: str, pages: list[int] = None):
    doc = fitz.open(pdf_path)
    target_pages = pages if pages is not None else list(range(1, len(doc) + 1))
    all_figures = []
    
    for p_num in target_pages:
        page = doc[p_num - 1]
        w, h = page.rect.width, page.rect.height
        
        pix = page.get_pixmap(dpi=72)
        img_bytes = pix.tobytes("jpeg")
        
        print(f"Scanning {doc_name} Page {p_num} for figures...")
        resp = client.models.generate_content(
            model=config.MODEL_PRO,
            contents=[PROMPT_EXTRACT_FIGURES, types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg")],
            config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0)
        )
        
        try:
            data = json.loads(resp.text.strip())
            figures = data.get("figures", [])
            for fig in figures:
                ymin, xmin, ymax, xmax = fig["bbox"]
                # Convert normalized (0-1000) to actual PDF points
                y0, x0 = (ymin / 1000.0) * h, (xmin / 1000.0) * w
                y1, x1 = (ymax / 1000.0) * h, (xmax / 1000.0) * w
                
                # Render high-res crop
                rect = fitz.Rect(x0, y0, x1, y1)
                crop_pix = page.get_pixmap(dpi=300, clip=rect)
                img_path = f"data/figures/{fig['id']}.png"
                crop_pix.save(img_path)
                
                fig["doc"] = doc_name
                fig["page"] = p_num
                fig["image_path"] = img_path
                all_figures.append(fig)
                print(f"  -> Extracted: {fig['id']}")
        except Exception as e:
            print(f"  -> Error parsing figures: {e}")
            
    return all_figures

if __name__ == "__main__":
    client = genai.Client(vertexai=True, project=config.PROJECT_ID, location=config.LOCATION)
    os.makedirs("data/figures", exist_ok=True)
    
    figures = []
    figures.extend(extract_figures_from_pdf(client, config.MEDICATION_GUIDE_PDF, "medication_guide"))
    figures.extend(extract_figures_from_pdf(client, config.BROCHURE_PDF, "brochure", config.BROCHURE_PAGES))
    
    with open("data/figures_catalog.json", "w", encoding="utf-8") as f:
        json.dump({"figures": figures}, f, indent=2)
        
    print(f"\nDone! Extracted {len(figures)} figures total.")
