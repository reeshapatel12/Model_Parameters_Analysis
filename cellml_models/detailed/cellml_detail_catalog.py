"""Load the complete Physiome catalog previously harvested for CellML sources."""
from __future__ import annotations

import csv
from collections import defaultdict

from cellml_detail_config import METADATA_FILE


def load_cellml_catalog():
    """Return all catalog rows, CellML source rows, and archive groupings."""
    if not METADATA_FILE.exists():
        raise FileNotFoundError(
            "Run cellml_models/extract_physiome_params.py first to create the full "
            f"Physiome catalog: {METADATA_FILE}"
        )
    with METADATA_FILE.open(newline="", encoding="utf-8") as handle:
        catalog = list(csv.DictReader(handle))

    models = [
        row for row in catalog
        if row.get("source_file", "").lower().endswith(".cellml")
        and row.get("workspace_id") and row.get("revision_id")
    ]
    groups = defaultdict(list)
    for row in models:
        groups[(row["workspace_id"], row["revision_id"])].append(row)
    return catalog, models, dict(groups)
