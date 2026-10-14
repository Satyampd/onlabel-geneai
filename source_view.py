"""Render approved source pages with the answer passage highlighted.

Everything here is deterministic code: the highlight boxes are found by searching the
PDF page for the approved answer text. No model chooses what is shown.
"""
import re

import pymupdf

import config

DOC_PATHS = {
    "medication_guide": config.MEDICATION_GUIDE_PDF,
    "brochure": config.BROCHURE_PDF,
}
HIGHLIGHT_COLOR = (1.0, 0.85, 0.2)  # warm yellow
MIN_LINE_CHARS = 6
_BULLET = re.compile(r"^\s*([•○▪◦]|o\s)\s*")


def _search_lines(answer_parts: list[str]) -> list[str]:
    """Lines of the answer, as they appear in the PDF text, to search for."""
    lines = []
    for part in answer_parts or []:
        for line in str(part).splitlines():
            line = _BULLET.sub("", line).strip()
            if len(line) >= MIN_LINE_CHARS:
                lines.append(line)
    return lines


def find_passage_rects(page: "pymupdf.Page", answer_parts: list[str]) -> list["pymupdf.Rect"]:
    """Rectangles on the page covering the answer passage (empty if not found)."""
    rects: list = []
    for line in _search_lines(answer_parts):
        hits = page.search_for(line)
        if not hits and len(line) > 40:
            # Long lines can wrap differently in the layout: search both halves.
            mid = len(line) // 2
            cut = line.rfind(" ", 0, mid) or mid
            hits = page.search_for(line[:cut].strip()) + page.search_for(line[cut:].strip())
        if not hits:
            continue
        # A long phrase occurs once per page in practice: keep all its boxes together.
        occurrences = [hits] if len(line) >= 40 else _group_wrapped(hits)
        if not rects:
            rects.extend(occurrences[0])
            continue
        # The same words can appear elsewhere on the page ("headache"): take the
        # occurrence that continues the passage, i.e. closest after the previous line.
        last = rects[-1]

        def distance(occ, last=last):
            r = occ[0]
            dy = r.y0 - last.y0
            return (abs(dy) + (40 if dy < -2 else 0)) + 0.3 * abs(r.x0 - last.x0)

        best = min(occurrences, key=distance)
        if len(line) < 15 and distance(best) > 80:
            continue  # a short, far-away match is more likely a different passage
        rects.extend(best)
    return rects


def _group_wrapped(hits: list) -> list[list]:
    """search_for returns one box per text line, so a phrase that wraps comes back as
    several boxes. Group consecutive boxes that continue on the next line into one
    occurrence."""
    groups = [[hits[0]]]
    for r in hits[1:]:
        prev = groups[-1][-1]
        height = max(prev.height, r.height, 1)
        same_line = min(prev.y1, r.y1) - max(prev.y0, r.y0) > 0 and r.x0 >= prev.x0 - 2
        wraps = 0 < r.y0 - prev.y0 < 2.2 * height and r.x0 < prev.x1
        if same_line or wraps:
            groups[-1].append(r)
        else:
            groups.append([r])
    return groups


def _open(doc_name: str):
    path = DOC_PATHS.get(doc_name)
    if path is None:
        raise KeyError(doc_name)
    return pymupdf.open(path)


def render(doc_name: str, pdf_page: int, answer_parts: list[str] | None = None,
           snippet: bool = False, dpi: int = 150) -> bytes:
    """PNG of the page. With answer_parts, the passage is highlighted. With snippet=True,
    the image is cropped to the passage (plus some context); falls back to the full page
    if the passage can't be located."""
    doc = _open(doc_name)
    try:
        if not 1 <= pdf_page <= len(doc):
            raise IndexError(pdf_page)
        page = doc[pdf_page - 1]
        clip = None
        if answer_parts:
            rects = find_passage_rects(page, answer_parts)
            if rects:
                annot = page.add_highlight_annot(rects)
                annot.set_colors(stroke=HIGHLIGHT_COLOR)
                annot.update(opacity=0.45)
                if snippet:
                    box = pymupdf.Rect(rects[0])
                    for r in rects[1:]:
                        box |= r
                    clip = (box + (-24, -18, 24, 18)) & page.rect
        zoom = (dpi if not snippet else max(dpi, 200)) / 72
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=clip, annots=True)
        return pix.tobytes("png")
    finally:
        doc.close()  # the highlight is never saved to the PDF
