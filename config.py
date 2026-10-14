import os
from dotenv import load_dotenv

load_dotenv()

PROJECT_ID = os.getenv("PROJECT_ID", "novartis-ai26hyd-803")
LOCATION = os.getenv("LOCATION", "global")

MODEL_PRO = os.getenv("MODEL_PRO", "gemini-4-argon")
MODEL_FLASH = os.getenv("MODEL_FLASH", "gemini-4-argon")
MODEL_EMBED = os.getenv("MODEL_EMBED", "gemini-embedding-001")

# gemini-embedding-001 scores run high: correct matches scored 0.98-1.00 in the first eval,
# while two WRONG answers were served at 0.88 and 0.91 with the old 0.80/0.65 defaults.
# Provisional values; confirm with the sweep in run_eval.py (pick the lowest pair with wrong = 0).
ACCEPT_THRESHOLD = float(os.getenv("ACCEPT_THRESHOLD", "0.94"))
RELATED_THRESHOLD = float(os.getenv("RELATED_THRESHOLD", "0.92"))

# 1-based PDF page numbers of the brochure to use. The brochure is the primary approved
# material; skipped: 1 cover, 3 and 5 study statistics, 10 testimonials, 12-13 full ISI
# (same text as the Medication Guide), 14 back cover.
BROCHURE_PAGES = [2, 4, 6, 7, 8, 9, 11]

# Serve a brochure answer when it scores within this margin of the best answer.
BROCHURE_PREFERENCE_MARGIN = float(os.getenv("BROCHURE_PREFERENCE_MARGIN", "0.02"))

DATA_DIR = os.getenv("DATA_DIR", "data")
MEDICATION_GUIDE_PDF = os.path.join(DATA_DIR, "medication_guide.pdf")
BROCHURE_PDF = os.path.join(DATA_DIR, "brochure.pdf")
SAFETY_PANEL_TXT = os.path.join(DATA_DIR, "safety_panel.txt")
ITEMS_JSON = os.path.join(DATA_DIR, "items.json")
LOG_JSONL = os.path.join(DATA_DIR, "log.jsonl")
