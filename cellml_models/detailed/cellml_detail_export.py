"""Write the CellML extraction tables in the uploaded workbook's column order."""
from __future__ import annotations

import csv
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

from cellml_detail_config import (ANNOTATION_HEADERS, AUDIT_HEADERS, OUTPUT_DIR,
                                 QUANTIFIED_HEADERS, READ_ME_HEADERS, WORKBOOK_NAME)


def _csv(path: Path, headers: list[str], rows: list[dict]):
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _sheet(workbook, title: str, headers: list[str], rows: list[dict]):
    sheet = workbook.create_sheet(title)
    sheet.append(headers)
    for row in rows:
        sheet.append([row.get(header, "") for header in headers])
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    for cell in sheet[1]:
        cell.fill = PatternFill("solid", fgColor="17365D")
        cell.font = Font(color="FFFFFF", bold=True)
        cell.alignment = Alignment(wrap_text=True, vertical="top")
    for column in sheet.columns:
        letter = get_column_letter(column[0].column)
        width = min(55, max(12, max((len(str(cell.value or "")) for cell in column[:200]), default=12) + 2))
        sheet.column_dimensions[letter].width = width
    return sheet


def write_outputs(annotations: list[dict], quantified: list[dict], audit: list[dict],
                  summary: dict):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    _csv(OUTPUT_DIR / "cellml_annotations_values.csv", ANNOTATION_HEADERS, annotations)
    _csv(OUTPUT_DIR / "cellml_quantified_elements.csv", QUANTIFIED_HEADERS, quantified)
    _csv(OUTPUT_DIR / "cellml_model_audit.csv", AUDIT_HEADERS, audit)

    readme = [
        {"Field": "Dataset", "Value": "Full CellML source-file annotation and numerical-value extraction from the Physiome Model Repository catalog."},
        {"Field": "Catalog entries", "Value": summary["catalog_count"]},
        {"Field": "CellML source files attempted", "Value": summary["model_count"]},
        {"Field": "Archive revisions", "Value": summary["archive_count"]},
        {"Field": "Successfully parsed model files", "Value": summary["success_count"]},
        {"Field": "Failed model files", "Value": summary["failed_count"]},
        {"Field": "Annotation associations", "Value": len(annotations)},
        {"Field": "Quantified elements", "Value": len(quantified)},
        {"Field": "Numerical value", "Value": "CellML variable initial_value when present; otherwise only values mapped through equivalent variables or evaluated from simple algebraic equations at t=0."},
        {"Field": "Units", "Value": "Original CellML units attribute; units are not normalized."},
        {"Field": "Direct", "Value": "Read from the variable's initial_value attribute."},
        {"Field": "Mapped", "Value": "Copied across an explicit CellML variable connection when units and known values agree."},
        {"Field": "Calculated at t=0", "Value": "Evaluated from a supported algebraic MathML relation using known initial values."},
        {"Field": "Not verified", "Value": "No direct or safely resolvable scalar initial value was found."},
        {"Field": "Annotation scope", "Value": "Direct RDF annotation associations on model, component, and variable elements with CellML metadata IDs."},
        {"Field": "Evidence", "Value": "Links point to the source_text view for the source file in its Physiome exposure."},
        {"Field": "Completeness", "Value": "All .cellml source files in the local full catalog are attempted. See the accompanying cellml_model_audit.csv for each file's outcome."},
    ]
    workbook = Workbook()
    workbook.remove(workbook.active)
    _sheet(workbook, "Annotations + values", ANNOTATION_HEADERS, annotations)
    _sheet(workbook, "Quantified elements", QUANTIFIED_HEADERS, quantified)
    readme_sheet = workbook.create_sheet("Read me")
    readme_sheet.append(READ_ME_HEADERS)
    for row in readme:
        readme_sheet.append([row[header] for header in READ_ME_HEADERS])
    readme_sheet.freeze_panes = "A2"
    readme_sheet.column_dimensions["A"].width = 32
    readme_sheet.column_dimensions["B"].width = 110
    for cell in readme_sheet[1]:
        cell.fill = PatternFill("solid", fgColor="17365D")
        cell.font = Font(color="FFFFFF", bold=True)
    for row in readme_sheet.iter_rows(min_row=2):
        row[1].alignment = Alignment(wrap_text=True, vertical="top")
    workbook.save(OUTPUT_DIR / WORKBOOK_NAME)
