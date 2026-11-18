"""Write the detailed curated BioModels CSV tables and formatted workbook."""
from __future__ import annotations

import json
from pathlib import Path

from detailed_config import HEADERS, OUTPUT_DIR, WORKBOOK_NAME
from jws_export import csv_output, xlsx_output


def write_tables(tables: dict, report: dict, page_audit: list[dict] | None = None) -> Path | None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, rows in tables.items():
        csv_output(OUTPUT_DIR, name, rows, HEADERS[name])

    (OUTPUT_DIR / "extraction_readme.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    if page_audit is not None:
        (OUTPUT_DIR / "model_audit.json").write_text(
            json.dumps(page_audit, indent=2), encoding="utf-8"
        )
    return xlsx_output(OUTPUT_DIR, tables, report, filename=WORKBOOK_NAME)
