#!/usr/bin/env python3
"""Create the detailed annotation workbook for curated BioModels only."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import sys

from detailed_archive import (
    NoSBMLDocumentsError, archive_url, cellml_documents, fetch_archive,
    model_page_url, new_session, sbml_documents,
)
from detailed_catalog import curated_models
from detailed_config import CACHE_DIR, HEADERS, OUTPUT_DIR, WORKBOOK_NAME
from detailed_cellml import extract_cellml_annotations
from detailed_export import write_tables
from extract_params import get_model_organism
from jws_sbml import harvest_xml


def empty_counts() -> Counter:
    return Counter({
        "Directly annotated elements": 0,
        "Annotated species": 0,
        "Annotated reactions": 0,
        "Total reactions": 0,
        "Total parameters": 0,
        "Direct RDF links": 0,
    })


def extract_model(session, model_id, metadata, delay):
    """Download one curated model and aggregate all SBML documents in OMEX."""
    archive = fetch_archive(session, model_id, CACHE_DIR, delay)
    documents, malformed = sbml_documents(archive)
    source_url = archive_url(model_id)
    page_url = model_page_url(model_id)
    model_tables = {name: [] for name in HEADERS if name != "Model Inventory"}
    counts = empty_counts()
    organisms = []
    parsed_files = []
    errors = list(malformed)

    if not documents:
        cellml_files = cellml_documents(archive)
        if not cellml_files:
            raise NoSBMLDocumentsError("No SBML or CellML model document found in archive")
        for member, xml_bytes in cellml_files:
            tables, stats = extract_cellml_annotations(
                model_id, member, xml_bytes, source_url, page_url
            )
            for name, rows in tables.items():
                model_tables[name].extend(rows)
            counts.update(stats)
            parsed_files.append(member)
        return model_tables, counts, parsed_files, errors, "", "CELLML"

    for member, xml_bytes in documents:
        try:
            tables, stats = harvest_xml(
                model_id,
                xml_bytes,
                metadata,
                sbml_url=source_url,
                model_url=page_url,
            )
            for name, rows in tables.items():
                model_tables[name].extend(rows)
            counts.update(stats)
            organism = get_model_organism(
                metadata, xml_bytes.decode("utf-8", errors="replace")
            )
            if organism:
                organisms.append(organism)
            parsed_files.append(member)
        except Exception as exc:
            errors.append(f"{member}: {type(exc).__name__}: {str(exc)[:250]}")

    if not parsed_files:
        raise ValueError("No SBML documents could be parsed: " + "; ".join(errors[:3]))
    return (
        model_tables, counts, parsed_files, errors,
        "; ".join(dict.fromkeys(organisms)), "SBML",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--delay", type=float, default=0.15,
                        help="Pause between BioModels archive requests")
    parser.add_argument("--max-models", type=int, default=0,
                        help="Test subset only; output is marked incomplete")
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    models = curated_models()
    if args.max_models:
        models = models[:args.max_models]
    print(f"Curated BIOMD models to scan: {len(models)}", flush=True)

    session = new_session()
    tables = {name: [] for name in HEADERS}
    inventory = []
    audit = []

    for index, (model_id, metadata) in enumerate(models, start=1):
        summary = empty_counts()
        parsed_files = []
        errors = []
        organism = metadata.get("organism") or ""
        status = "ok"
        try:
            extracted, summary, parsed_files, errors, extracted_organism, source_format = extract_model(
                session, model_id, metadata, args.delay
            )
            for name, rows in extracted.items():
                tables[name].extend(rows)
            organism = organism or extracted_organism
            if errors:
                status = "PARTIAL"
            elif source_format == "CELLML":
                status = "CELLML"
        except NoSBMLDocumentsError as exc:
            status = "NO_SBML"
            errors.append(str(exc))
        except Exception as exc:
            status = "ERROR"
            errors.append(f"{type(exc).__name__}: {str(exc)[:400]}")
            print(f"[{index}/{len(models)}] {model_id}: {errors[-1]}", file=sys.stderr, flush=True)

        archive_source = archive_url(model_id)
        page_source = model_page_url(model_id)
        inventory.append([
            model_id, organism, metadata.get("tissue", ""),
            metadata.get("pathway", ""), metadata.get("model_type", ""), status,
            summary["Directly annotated elements"], summary["Annotated species"],
            summary["Annotated reactions"], summary["Total reactions"],
            summary["Total parameters"], summary["Direct RDF links"],
            hashlib.sha256((CACHE_DIR / f"{model_id}.omex").read_bytes()).hexdigest()
            if (CACHE_DIR / f"{model_id}.omex").exists() else "",
            "; ".join(errors), archive_source, page_source,
        ])
        audit.append({
            "model_id": model_id,
            "status": status,
            "sbml_files_parsed": parsed_files,
            "errors": errors,
        })
        if index % 50 == 0:
            print(
                f"Processed {index}/{len(models)} models: "
                f"{len(tables['Annotated Elements'])} annotated elements",
                flush=True,
            )

    tables["Model Inventory"] = inventory
    tables["Annotated Elements"].sort(key=lambda row: (row[1], row[2], row[3]))
    for number, row in enumerate(tables["Annotated Elements"], start=1):
        row[0] = number

    no_sbml = sum(row[5] == "NO_SBML" for row in inventory)
    complete = (
        len(models) > 0
        and all(row[5] in ("ok", "CELLML", "NO_SBML") for row in inventory)
        and not args.max_models
    )
    report = {
        "Status": (
            "COMPLETE (curated BIOMD catalog; records without SBML listed)"
            if complete and no_sbml else
            "COMPLETE (curated BIOMD catalog)" if complete else
            "INCOMPLETE (see Model Inventory)"
        ),
        "Extraction time UTC": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "Source": "Curated BioModels (BIOMD identifiers only)",
        "Models scanned": len(models),
        "Models parsed": sum(row[5] in ("ok", "CELLML", "PARTIAL") for row in inventory),
        "Models parsed from CellML": sum(row[5] == "CELLML" for row in inventory),
        "Models with no SBML/CellML source": no_sbml,
        "Models with errors": sum(row[5] in ("ERROR", "PARTIAL") for row in inventory),
        "Directly annotated elements": len(tables["Annotated Elements"]),
        "Annotation links": len(tables["Annotation Links"]),
        "Scope": "All curated BIOMD records returned by the BioModels identifier service",
        "What counts": "Direct SBML RDF links and supported CellML variable RDF annotations",
        "Output directory": str(OUTPUT_DIR),
        "OMEX cache": str(CACHE_DIR),
    }

    workbook = write_tables(tables, report, audit)
    print(f"Created {workbook}")
    print(report["Status"])
    return 0 if complete else 2


if __name__ == "__main__":
    sys.exit(main())
