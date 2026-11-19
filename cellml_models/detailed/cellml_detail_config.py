"""Configuration, source paths, and workbook columns for detailed CellML data."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
METADATA_FILE = ROOT / "data" / "physiome" / "raw" / "models_metadata.csv"
OUTPUT_DIR = ROOT / "data" / "detailed_cellml"
CACHE_DIR = OUTPUT_DIR / "archive_cache"
BASE_URL = "https://models.physiomeproject.org"
WORKBOOK_NAME = "cellml_annotated_models_with_values_units_full.xlsx"

ANNOTATION_HEADERS = [
    "CellML model", "Annotated model element", "Element type", "Database",
    "Database ID", "Annotation link", "Annotation relation", "Numerical value",
    "CellML units", "Value status", "Biological interpretation",
    "Value resolution / caution", "Annotation source", "Numerical value evidence",
]
QUANTIFIED_HEADERS = [
    "CellML model", "Element", "Numerical value", "CellML units",
    "Value provenance", "Notes", "Value evidence",
]
AUDIT_HEADERS = [
    "Model ID", "CellML model", "Workspace", "Revision", "Source file",
    "Exposure IDs", "Status", "Total components", "Annotated components",
    "Total variables", "Annotated variables", "Annotated elements", "Annotation links",
    "Quantified elements", "Error",
]
ELEMENT_INVENTORY_HEADERS = [
    "Model ID", "CellML model", "Element type", "Element ID", "Element name",
    "Component", "CellML units", "Initial value", "Annotation IDs",
    "Annotation relations", "Is directly annotated", "Source file",
]
READ_ME_HEADERS = ["Field", "Value"]
