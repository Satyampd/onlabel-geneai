import os
from dotenv import load_dotenv

load_dotenv()

PROJECT_ID = os.getenv("PROJECT_ID", "novartis-ai26hyd-803")
LOCATION = os.getenv("LOCATION", "us-central1")

MODEL_PRO = os.getenv("MODEL_PRO", "gemini-2.5-pro")
MODEL_FLASH = os.getenv("MODEL_FLASH", "gemini-2.5-flash")
MODEL_EMBED = os.getenv("MODEL_EMBED", "gemini-embedding-001")

ACCEPT_THRESHOLD = float(os.getenv("ACCEPT_THRESHOLD", "0.80"))
RELATED_THRESHOLD = float(os.getenv("RELATED_THRESHOLD", "0.65"))

# 1-based PDF page numbers of the brochure to use
BROCHURE_PAGES = [4, 9, 11]

DATA_DIR = os.getenv("DATA_DIR", "data")
MEDICATION_GUIDE_PDF = os.path.join(DATA_DIR, "medication_guide.pdf")
BROCHURE_PDF = os.path.join(DATA_DIR, "brochure.pdf")
SAFETY_PANEL_TXT = os.path.join(DATA_DIR, "safety_panel.txt")
ITEMS_JSON = os.path.join(DATA_DIR, "items.json")
LOG_JSONL = os.path.join(DATA_DIR, "log.jsonl")
