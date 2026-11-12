from __future__ import annotations

import argparse
import csv
import io
import logging
import re
import tarfile
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from urllib.parse import urljoin
import xml.etree.ElementTree as ET

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data" / "physiome"
RAW_DIR = DATA_DIR / "raw"
STATS_DIR = DATA_DIR / "statistics"
RAW_DIR.mkdir(parents=True, exist_ok=True)
STATS_DIR.mkdir(parents=True, exist_ok=True)

BASE_URL = "https://models.physiomeproject.org"
TIMEOUT = (15, 45)
PAUSE_SECONDS = 0.05
OUTPUT_CSV = RAW_DIR / "parameters_raw.csv"
MODEL_METADATA_CSV = RAW_DIR / "models_metadata.csv"
FAILED_MODELS_CSV = STATS_DIR / "failed_models.csv"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("physiome-extractor")

def new_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(total=2, connect=2, read=1, backoff_factor=0.25,
                  status_forcelist=(429, 500, 502, 503, 504), allowed_methods=("GET",))
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers.update({"User-Agent": "PhysiomeParameterResearch/1.0"})
    return session

SESSION = new_session()

# Keep the shared BioModels parameter columns and add file-level provenance.
CSV_FIELDS = [
    "model_id", "source_database", "model_collection", "curated", "model_name",
    "organism", "authors", "publication_id", "publication_title", "cell_type",
    "tissue", "disease", "pathway", "modeling_approach", "model_type",
    "model_format", "record_type", "parameter_id", "parameter_name", "value",
    "units", "compartment", "reaction_id", "sbml_file", "source_file",
    "workspace_id", "exposure_id", "repository_url",
]
MODEL_METADATA_FIELDS = [
    "model_id", "source_database", "model_collection", "curated", "model_name",
    "organism", "authors", "publication_id", "publication_title", "cell_type",
    "tissue", "disease", "pathway", "modeling_approach", "model_type",
    "model_format", "workspace_id", "revision_id", "source_file", "exposure_id",
    "repository_url", "encoded_by", "description", "citation",
]
COLLECTION_PAGES = (
    ("cellml_exposure", "/exposure/listing/full-list"),
    ("fieldml", "/fieldml"),
    ("musculoskeletal_scaffold", "/msk"),
)

def get_page(url: str) -> str:
    response = SESSION.get(url, timeout=TIMEOUT)
    response.raise_for_status()
    return response.text

def _norm_text(value: str) -> str:
    return " ".join(value.split())

def catalog_targets() -> dict[str, dict[str, Any]]:
    """Collect exposure links from each model collection linked on welcome."""
    targets: dict[str, dict[str, Any]] = {}
    patterns = {
        "cellml_exposure": re.compile(r"/e/([0-9a-f]+)/view/?$", re.I),
        "fieldml": re.compile(r"/e/([0-9a-f]+)/[^/]+/view/?$", re.I),
        "musculoskeletal_scaffold": re.compile(r"/e/([0-9a-f]+)/?$", re.I),
    }
    for collection, path in COLLECTION_PAGES:
        soup = BeautifulSoup(get_page(urljoin(BASE_URL, path)), "html.parser")
        added = 0
        for anchor in soup.select("a[href]"):
            href = urljoin(BASE_URL, anchor["href"])
            match = patterns[collection].search(href)
            if not match:
                continue
            exposure_id = match.group(1)
            target = targets.setdefault(exposure_id, {
                "exposure_id": exposure_id, "collections": set(), "listing_title": None,
            })
            target["collections"].add(collection)
            title = _norm_text(anchor.get_text(" ", strip=True))
            if title and not target["listing_title"]:
                target["listing_title"] = title
            added += 1
        log.info("Catalog %s: found %d linked entries", collection, added)
    return targets

def _first_meta(soup: BeautifulSoup, patterns: tuple[str, ...]) -> str | None:
    for tag in soup.find_all("meta"):
        key = (tag.get("name") or tag.get("property") or "").lower()
        value = _norm_text(tag.get("content") or "")
        if value and any(pattern in key for pattern in patterns):
            return value
    return None

def _metadata_from_page(exposure_id: str, target: dict[str, Any]) -> dict[str, Any]:
    url = urljoin(BASE_URL, f"/e/{exposure_id}/view")
    soup = BeautifulSoup(get_page(url), "html.parser")
    title_node = soup.find("h1")
    title = _norm_text(title_node.get_text(" ", strip=True)) if title_node else target.get("listing_title") or exposure_id
    content = soup.select_one("#content-core") or soup.select_one("#content") or soup
    description = _norm_text(content.get_text(" ", strip=True))[:8000]

    workspace_id = revision_id = archive_url = None
    for anchor in soup.select("a[href]"):
        href = urljoin(BASE_URL, anchor["href"])
        archive_match = re.search(r"/workspace/([^/]+)/@@archive/([^/]+)/tgz", href)
        if archive_match:
            workspace_id, revision_id, archive_url = archive_match.group(1), archive_match.group(2), href
        elif workspace_id is None:
            workspace_match = re.search(r"/workspace/([^/]+)", href)
            if workspace_match:
                workspace_id = workspace_match.group(1)

    doi_match = re.search(r"10\.\d{4,9}/[^\s<>\"']+", description, re.I)
    pmid_match = re.search(r"(?:PMID|PubMed)\s*[:#]?\s*(\d{5,9})", description, re.I)
    publication_id = f"DOI:{doi_match.group(0).rstrip('.,;')}" if doi_match else None
    if pmid_match:
        publication_id = "; ".join(filter(None, [publication_id, f"PMID:{pmid_match.group(1)}"])) or None
    encoded_match = re.search(r"Encoded in CellML by\s+([^\n.]{2,160})", description, re.I)
    encoded_by = _norm_text(encoded_match.group(1)) if encoded_match else None
    return {
        "model_id": f"PMR:exposure:{exposure_id}",
        "source_database": "Physiome Model Repository",
        "model_collection": "; ".join(sorted(target["collections"])),
        "curated": None,
        "model_name": title,
        "organism": _first_meta(soup, ("organism", "taxon")),
        "authors": _first_meta(soup, ("author", "creator")),
        "publication_id": publication_id,
        "publication_title": _first_meta(soup, ("citation_title",)),
        "cell_type": None, "tissue": None, "disease": None, "pathway": None,
        "modeling_approach": None, "model_type": None,
        "model_format": "CellML/FieldML",
        "workspace_id": workspace_id, "revision_id": revision_id,
        "source_file": None, "exposure_id": exposure_id,
        "repository_url": url, "encoded_by": encoded_by,
        "description": description,
        "citation": _first_meta(soup, ("citation", "dc.relation", "dc.source")),
        "archive_url": archive_url,
    }

def _fetch_page_info(target: dict[str, Any]) -> dict[str, Any]:
    try:
        return _metadata_from_page(target["exposure_id"], target)
    except Exception as exc:
        log.warning("Could not read exposure %s: %s", target["exposure_id"], exc)
        return {
            "model_id": f"PMR:exposure:{target['exposure_id']}",
            "source_database": "Physiome Model Repository",
            "model_collection": "; ".join(sorted(target["collections"])),
            "curated": None, "model_name": target.get("listing_title") or target["exposure_id"],
            "workspace_id": None, "revision_id": None, "source_file": None,
            "exposure_id": target["exposure_id"],
            "repository_url": urljoin(BASE_URL, f"/e/{target['exposure_id']}/view"),
            "archive_url": None, "page_error": str(exc),
        }

def fetch_exposure_metadata(targets: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Read model context and revision-specific workspace archive links."""
    results = []
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(_fetch_page_info, target) for target in targets.values()]
        for index, future in enumerate(as_completed(futures), start=1):
            results.append(future.result())
            if index % 50 == 0:
                log.info("Read metadata pages for %d/%d Physiome entries", index, len(futures))
    return results

def _prefix_scale(prefix: str | None) -> float:
    if not prefix:
        return 1.0
    named = {
        "yotta": 24, "zetta": 21, "exa": 18, "peta": 15, "tera": 12, "giga": 9,
        "mega": 6, "kilo": 3, "hecto": 2, "deka": 1, "deci": -1, "centi": -2,
        "milli": -3, "micro": -6, "nano": -9, "pico": -12, "femto": -15,
        "atto": -18, "zepto": -21, "yocto": -24,
    }
    try:
        power = int(prefix)
    except ValueError:
        power = named.get(prefix.lower(), 0)
    return 10.0 ** power

def cellml_unit_map(root: ET.Element) -> dict[str, str]:
    """Resolve local CellML unit definitions into Pint-readable expressions."""
    definitions = {}
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] == "units" and element.get("name"):
            definitions[element.get("name")] = [child for child in element if child.tag.rsplit("}", 1)[-1] == "unit"]
    resolved: dict[str, str] = {}
    aliases = {"metre": "meter", "litre": "liter"}
    resolving: set[str] = set()

    def resolve(name: str) -> str:
        if name in resolved:
            return resolved[name]
        if name not in definitions:
            return aliases.get(name, name)
        if name in resolving:
            return name
        resolving.add(name)
        terms = []
        for unit in definitions[name]:
            base = resolve(unit.get("units", "dimensionless"))
            factor = _prefix_scale(unit.get("prefix")) * float(unit.get("multiplier", "1"))
            exponent = float(unit.get("exponent", "1"))
            if factor != 1:
                base = f"{factor:g} * ({base})"
            if exponent != 1:
                base = f"({base}) ** {exponent:g}"
            terms.append(base)
        resolving.remove(name)
        resolved[name] = " * ".join(terms) if terms else "dimensionless"
        return resolved[name]

    for unit_name in definitions:
        resolve(unit_name)
    return resolved

def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]

def parse_cellml_source(model_id: str, source_name: str, xml_bytes: bytes,
                        context: dict[str, Any]) -> list[dict[str, Any]]:
    root = ET.fromstring(xml_bytes)
    model_name = root.get("name") or context.get("model_name") or Path(source_name).stem
    units = cellml_unit_map(root)
    records = []
    for component in root.iter():
        if local_name(component.tag) != "component":
            continue
        component_name = component.get("name")
        for variable in component:
            if local_name(variable.tag) != "variable":
                continue
            name = variable.get("name") or ""
            unit_name = variable.get("units")
            unit_text = units.get(unit_name, unit_name) if unit_name else None
            records.append({
                **context,
                "model_id": model_id,
                "source_database": "Physiome Model Repository",
                "model_name": model_name,
                "model_format": "CellML",
                "record_type": "time_unit" if name.strip().lower() == "time" else "cellml_variable",
                "parameter_id": f"{component_name or 'component'}/{name}",
                "parameter_name": name,
                "value": variable.get("initial_value"),
                "units": unit_text,
                "compartment": component_name,
                "reaction_id": None, "sbml_file": None,
                "source_file": source_name,
            })
    return records

def archive_cellml_files(archive_url: str) -> list[tuple[str, bytes]]:
    response = SESSION.get(archive_url, timeout=TIMEOUT)
    response.raise_for_status()
    archive = tarfile.open(fileobj=io.BytesIO(response.content), mode="r:gz")
    files = []
    for member in archive.getmembers():
        if member.isfile() and member.name.lower().endswith(".cellml"):
            handle = archive.extractfile(member)
            if handle:
                files.append((member.name, handle.read()))
    return files

def record_failure(model_id: str, stage: str, detail: str):
    rows = {}
    if FAILED_MODELS_CSV.exists():
        with FAILED_MODELS_CSV.open(newline="", encoding="utf-8") as handle:
            rows = {row["model_id"]: row for row in csv.DictReader(handle) if row.get("model_id")}
    row = rows.get(model_id, {"model_id": model_id, "stage": "", "details": ""})
    stages = set(filter(None, row["stage"].split(";")))
    details = set(filter(None, row["details"].split("; ")))
    stages.add(stage)
    details.add(detail)
    rows[model_id] = {"model_id": model_id, "stage": ";".join(sorted(stages)), "details": "; ".join(sorted(details))}
    with FAILED_MODELS_CSV.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["model_id", "stage", "details"])
        writer.writeheader()
        writer.writerows(rows[key] for key in sorted(rows))

def metadata_row(context: dict[str, Any]) -> dict[str, Any]:
    return {field: context.get(field) for field in MODEL_METADATA_FIELDS}

def main():
    parser = argparse.ArgumentParser(description="Extract CellML variables and units from Physiome repository collections.")
    parser.add_argument("--restart", action="store_true", help="start fresh instead of resuming IDs already in models_metadata.csv")
    args = parser.parse_args()

    if args.restart and FAILED_MODELS_CSV.exists():
        FAILED_MODELS_CSV.unlink()
    targets = catalog_targets()
    log.info("Unique Physiome catalog entries: %d", len(targets))
    pages = fetch_exposure_metadata(targets)
    archives: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for page in pages:
        if page.get("page_error"):
            record_failure(page["model_id"], "model_page", page["page_error"])
        elif page.get("archive_url"):
            archives[page["archive_url"]].append(page)

    resume_ids: set[str] = set()
    if not args.restart and MODEL_METADATA_CSV.exists():
        with MODEL_METADATA_CSV.open(newline="", encoding="utf-8") as handle:
            resume_ids = {row["model_id"] for row in csv.DictReader(handle) if row.get("model_id")}
    mode = "a" if resume_ids else "w"
    with OUTPUT_CSV.open(mode, newline="", encoding="utf-8") as raw_handle, MODEL_METADATA_CSV.open(mode, newline="", encoding="utf-8") as metadata_handle:
        raw_writer = csv.DictWriter(raw_handle, fieldnames=CSV_FIELDS)
        metadata_writer = csv.DictWriter(metadata_handle, fieldnames=MODEL_METADATA_FIELDS)
        if mode == "w":
            raw_writer.writeheader()
            metadata_writer.writeheader()

        # Keep non-CellML collection entries in metadata and record why they
        # could not yield numerical model parameters in this CellML pipeline.
        for page in pages:
            if page.get("model_id") in resume_ids or page.get("archive_url"):
                continue
            metadata_writer.writerow(metadata_row(page))
            if page.get("page_error"):
                record_failure(page["model_id"], "model_page", page["page_error"])
            else:
                record_failure(page["model_id"], "no_model_archive", "No downloadable workspace archive was linked from the exposure page")
        metadata_handle.flush()

        for index, (archive_url, archive_pages) in enumerate(archives.items(), start=1):
            active_pages = [page for page in archive_pages if page.get("model_id") not in resume_ids]
            if not active_pages:
                continue
            try:
                cellml_files = archive_cellml_files(archive_url)
            except Exception as exc:
                for page in active_pages:
                    record_failure(page["model_id"], "archive_download", str(exc))
                    metadata_writer.writerow(metadata_row(page))
                metadata_handle.flush()
                continue

            if not cellml_files:
                for page in active_pages:
                    metadata_writer.writerow(metadata_row(page))
                    record_failure(page["model_id"], "no_cellml_source", "Workspace archive contains no .cellml source files")
                metadata_handle.flush()
                continue

            exposure_ids = "; ".join(sorted({str(p.get("exposure_id")) for p in active_pages if p.get("exposure_id")}))
            collection_names = "; ".join(sorted({name for p in active_pages for name in p.get("model_collection", "").split("; ") if name}))
            page = active_pages[0]
            for source_name, xml_bytes in cellml_files:
                workspace_id = page.get("workspace_id") or "unknown"
                revision = (page.get("revision_id") or "unknown")[:12]
                model_id = f"PMR:{workspace_id}:{revision}:{source_name}"
                if model_id in resume_ids:
                    continue
                context = {
                    **page, "model_id": model_id, "model_name": Path(source_name).stem,
                    "model_collection": collection_names, "model_format": "CellML",
                    "source_file": source_name, "workspace_id": workspace_id,
                    "exposure_id": exposure_ids,
                }
                try:
                    records = parse_cellml_source(model_id, source_name, xml_bytes, context)
                    if not records:
                        record_failure(model_id, "no_variables", "CellML source contained no component variables")
                    for record in records:
                        raw_writer.writerow({field: record.get(field) for field in CSV_FIELDS})
                except Exception as exc:
                    record_failure(model_id, "cellml_parse", str(exc))
                metadata_writer.writerow(metadata_row(context))
                raw_handle.flush()
                metadata_handle.flush()
            if index % 25 == 0:
                log.info("Processed %d/%d unique workspace archives", index, len(archives))
                time.sleep(PAUSE_SECONDS)

if __name__ == "__main__":
    main()
