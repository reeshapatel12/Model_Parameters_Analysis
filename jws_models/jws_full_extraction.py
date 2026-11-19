#!/usr/bin/env python3
"""Extract annotated model elements from every public JWS catalog model.

Run from the project root:
    python jws_models/jws_full_extraction.py

Parsing, catalog discovery, workbook layout, and file writing live in separate
modules alongside this orchestration script.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from jws_catalog import catalog
from jws_config import HEADERS, INDEX
from jws_export import csv_output, xlsx_output
from jws_sbml import harvest_xml


def make_session() -> requests.Session:
    """Create a retry-enabled session for catalog and SBML requests."""
    session = requests.Session()
    retries = Retry(
        total=4,
        backoff_factor=0.8,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
    )
    session.mount("https://", HTTPAdapter(max_retries=retries))
    session.headers.update({
        "User-Agent": "JWS-annotation-academic-export/1.0 (SBML metadata extraction)"
    })
    return session


def empty_model_counts() -> dict[str, int]:
    return {
        "Directly annotated elements": 0,
        "Annotated species": 0,
        "Total species": 0,
        "Annotated reactions": 0,
        "Total reactions": 0,
        "Total compartments": 0,
        "Annotated compartments": 0,
        "Total parameters": 0,
        "Direct RDF links": 0,
    }


def extract_catalog_models(session, models, cache_dir, delay):
    """Download or reuse SBML, then build all workbook tables and inventory."""
    tables = {name: [] for name in HEADERS}
    inventory = []
    model_names = sorted(models)

    for number, slug in enumerate(model_names, start=1):
        sbml_url = f"{INDEX}{slug}/sbml/?download=1"
        model_page = f"{INDEX}{slug}/"
        metadata = models[slug]
        cache_file = cache_dir / f"{slug}.xml"
        counts = empty_model_counts()
        status, error, checksum = "ok", "", ""

        try:
            raw = read_or_download_sbml(session, sbml_url, cache_file, delay)
            model_tables, counts = harvest_xml(slug, raw, metadata)
            checksum = hashlib.sha256(raw).hexdigest()
            if not cache_file.exists():
                cache_file.write_bytes(raw)
            for table_name, rows in model_tables.items():
                tables[table_name].extend(rows)
        except Exception as exc:
            status = "ERROR"
            error = f"{type(exc).__name__}: {str(exc)[:400]}"
            print(f"[{number}/{len(model_names)}] {slug}: {error}", file=sys.stderr, flush=True)

        inventory.append([
            slug, metadata.get("Organism", ""), metadata.get("Tissue", ""),
            metadata.get("Process", ""), metadata.get("Model type", ""), status,
            counts["Directly annotated elements"], counts["Annotated species"],
            counts["Total species"], counts["Annotated reactions"], counts["Total reactions"],
            counts["Total compartments"], counts["Annotated compartments"],
            counts["Total parameters"], counts["Direct RDF links"], checksum,
            error, sbml_url, model_page,
        ])

        if number % 50 == 0:
            total = len(tables["Annotated Elements"])
            print(f"Processed {number}/{len(model_names)}: {total} annotated elements", flush=True)

    tables["Model Inventory"] = inventory
    tables["Annotated Elements"].sort(key=lambda row: (row[1], row[2], row[3]))
    tables["Complete Element Inventory"].sort(key=lambda row: (row[0], row[1], row[2]))
    for number, row in enumerate(tables["Annotated Elements"], start=1):
        row[0] = number
    return tables


def read_or_download_sbml(session, url, cache_file, delay):
    """Use a valid cached SBML document or fetch it from JWS."""
    if cache_file.exists() and cache_file.stat().st_size > 10:
        return cache_file.read_bytes()

    time.sleep(delay)
    response = session.get(url, timeout=(15, 90))
    response.raise_for_status()
    raw = response.content
    if len(raw) < 100 or not raw.lstrip().startswith(b"<?xml"):
        raise ValueError("Download did not return SBML XML")
    return raw


def extraction_summary(tables, models, page_audit, duplicates, subset=False):
    """Describe the extraction scope and completeness in the workbook Readme."""
    inventory = tables["Model Inventory"]
    complete = (
        all(row[5] == "ok" for row in inventory)
        and len(inventory) == len(models)
        and not subset
    )
    status = "COMPLETE (curated catalog as crawled)" if complete else "INCOMPLETE (see inventory ERROR rows / subset flag)"
    report = {
        "Status": status,
        "Extraction time UTC": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "Repository": INDEX,
        "Catalog pages scanned": len(page_audit),
        "Unique catalog models": len(models),
        "Models downloaded and parsed": sum(row[5] == "ok" for row in inventory),
        "Models failed": sum(row[5] != "ok" for row in inventory),
        "Total annotated elements (RDF)": len(tables["Annotated Elements"]),
        "Total annotation links": len(tables["Annotation Links"]),
        "Total SBML species": sum(row[8] for row in inventory if row[5] == "ok"),
        "Total SBML reactions": sum(row[10] for row in inventory if row[5] == "ok"),
        "Total SBML compartments": sum(row[11] for row in inventory if row[5] == "ok"),
        "Annotated SBML compartments": sum(row[12] for row in inventory if row[5] == "ok"),
        "Complete species, reaction, and compartment inventory": "complete_element_inventory.csv",
        "Scope": "Curated models visible at /models/; excludes browser-session-only user models",
        "What counts": "Explicit element-level RDF resource URIs under biological/model/DC qualifiers",
        "What does not count": "SBO terms alone, model-level citations as element annotations, mere kinetic laws",
        "Numbers": "Raw SBML numeric values; initial assignments preserved separately; no silent unit guesses",
        "Rates": "Kinetic laws are transcribed from MathML; parameters listed by references in rate law",
        "References": "Model-level RDF references are in Model References, not duplicated onto elements",
        "SBO": "SBO terms on biologically annotated elements retained as a distinct field",
        "Duplicate slugs in pages": sum(count - 1 for count in duplicates.values() if count > 1),
        "Caveat": "An archived model may have changed after harvest; checksum provided for each successful SBML download",
    }
    return complete, report


def write_results(output_dir, tables, report, page_audit, csv_only=False):
    """Write CSV tables, page audit, Readme JSON, and formatted XLSX workbook."""
    for name, rows in tables.items():
        path = csv_output(output_dir, name, rows, HEADERS[name])
        print("Created", path)

    audit_path = output_dir / "catalog_page_audit.json"
    audit_path.write_text(json.dumps(page_audit, indent=2), encoding="utf-8")
    (output_dir / "extraction_readme.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    if csv_only:
        print("Skipped XLSX generation (--csv-only)")
    else:
        workbook_path = xlsx_output(output_dir, tables, report)
        print("Created", workbook_path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="data/jws", help="Output folder")
    parser.add_argument("--delay", type=float, default=0.18, help="Pause between model requests")
    parser.add_argument("--csv-only", action="store_true", help="Skip XLSX generation")
    parser.add_argument("--max-models", type=int, default=0,
                        help="Test subset only; output is marked incomplete")
    args = parser.parse_args()

    output_dir = Path(args.out)
    cache_dir = output_dir / "sbml_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    session = make_session()
    models, duplicates, page_audit = catalog(session, args.delay)
    model_names = sorted(models)
    if args.max_models:
        model_names = model_names[:args.max_models]
        models = {name: models[name] for name in model_names}
    print(f"Unique catalog models: {len(models)}; scanning {len(model_names)}", flush=True)

    tables = extract_catalog_models(session, models, cache_dir, args.delay)
    complete, report = extraction_summary(
        tables, models, page_audit, duplicates, subset=bool(args.max_models)
    )
    write_results(output_dir, tables, report, page_audit, csv_only=args.csv_only)
    print(report["Status"])
    return 0 if complete else 2


if __name__ == "__main__":
    sys.exit(main())
