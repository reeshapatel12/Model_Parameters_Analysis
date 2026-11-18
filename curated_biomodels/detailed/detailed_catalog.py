"""Curated BioModels IDs and cached model metadata."""
from __future__ import annotations

import csv
from pathlib import Path

from detailed_config import ROOT
from extract_params import fetch_model_metadata, get_all_public_model_ids

METADATA_FILE = ROOT / "data" / "curated" / "raw" / "models_metadata.csv"


def load_saved_metadata() -> dict[str, dict[str, str]]:
    """Reuse metadata already collected by the standard curated extractor."""
    if not METADATA_FILE.exists():
        return {}
    with METADATA_FILE.open(newline="", encoding="utf-8") as handle:
        return {row["model_id"]: row for row in csv.DictReader(handle) if row.get("model_id")}


def curated_models() -> list[tuple[str, dict]]:
    """Return all current BIOMD IDs and available metadata for each model."""
    saved = load_saved_metadata()
    # The standard curated extraction already records the full BIOMD selection.
    # Reuse it when present, avoiding an unnecessary API-client cache write.
    model_ids = sorted(model_id for model_id in saved if model_id.startswith("BIOMD"))
    if not model_ids:
        model_ids = get_all_public_model_ids()
    models = []
    for model_id in model_ids:
        row = saved.get(model_id)
        if row:
            metadata = dict(row)
            metadata.setdefault("name", metadata.get("model_name"))
        else:
            metadata = fetch_model_metadata(model_id)
        models.append((model_id, metadata))
    return models
