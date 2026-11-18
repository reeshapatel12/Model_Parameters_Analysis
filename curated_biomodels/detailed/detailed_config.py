"""Paths and output names for the detailed curated BioModels extraction."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = ROOT / "data" / "detailed_curated"
CACHE_DIR = OUTPUT_DIR / "omex_cache"
BIO_MODELS_API = "https://www.biomodels.org"
WORKBOOK_NAME = "detailed_curated_model_elements_full.xlsx"

JWS_SCRIPTS = ROOT / "jws_models"
CURATED_SCRIPTS = ROOT / "curated_biomodels"
sys.path.insert(0, str(JWS_SCRIPTS))
sys.path.insert(0, str(CURATED_SCRIPTS))

from jws_config import HEADERS  # noqa: E402
