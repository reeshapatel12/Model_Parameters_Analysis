from __future__ import annotations

import csv
import argparse
import logging
import re
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import libsbml
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data" / "vcell"
RAW_DIR = DATA_DIR / "raw"
STATS_DIR = DATA_DIR / "statistics"
RAW_DIR.mkdir(parents=True, exist_ok=True)
STATS_DIR.mkdir(parents=True, exist_ok=True)

API = "https://vcell-dev.cam.uchc.edu/api/v0"
TIMEOUT = (15, 30)
PAUSE_SECONDS = 0.1
OUTPUT_CSV = RAW_DIR / "parameters_raw.csv"
MODEL_METADATA_CSV = RAW_DIR / "models_metadata.csv"
FAILED_MODELS_CSV = STATS_DIR / "failed_models.csv"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("vcell-extractor")

session = requests.Session()
retry = Retry(total=2, connect=2, read=1, backoff_factor=0.25,
              status_forcelist=(429, 500, 502, 503, 504), allowed_methods=("GET",))
session.mount("https://", HTTPAdapter(max_retries=retry))
session.headers.update({"User-Agent": "VCellParameterResearch/1.0"})

# These fields match the parameter table used by the BioModels pipelines, with
# VCell source and collection fields added to support later cross-database joins.
CSV_FIELDS = [
    "model_id", "source_database", "model_collection", "curated",
    "model_name", "organism", "authors", "publication_id",
    "publication_title", "cell_type", "tissue", "disease", "pathway",
    "modeling_approach", "model_type", "model_format", "record_type",
    "parameter_id", "parameter_name", "value", "units", "compartment",
    "reaction_id", "sbml_file",
]
MODEL_METADATA_FIELDS = [
    "model_id", "source_database", "model_collection", "curated",
    "model_name", "owner_name", "owner_key", "privacy", "saved_date",
    "branch_id", "model_key", "authors", "publication_id",
    "publication_title", "pubmed_id", "doi", "publication_year",
    "citation", "publication_url", "annotation",
]

BIOMODEL_QUERY = {
    "bmName": "", "bmId": "", "savedLow": "", "savedHigh": "",
    "orderBy": "date_desc",
}
COLLECTION_QUERIES = (
    ("education", {**BIOMODEL_QUERY, "category": "education", "owner": ""}),
    ("owner:CMC", {**BIOMODEL_QUERY, "category": "all", "owner": "CMC"}),
    ("owner:CompCell", {**BIOMODEL_QUERY, "category": "all", "owner": "CompCell"}),
    ("owner:ModelBrick", {**BIOMODEL_QUERY, "category": "all", "owner": "ModelBrick"}),
)
PUBLICATION_QUERY = {
    "submitLow": "", "submitHigh": "", "hasData": "all",
    "waiting": "on", "queued": "on", "dispatched": "on", "running": "on",
}

def request_json(path: str, params: dict[str, Any] | None = None) -> Any:
    response = session.get(f"{API}{path}", params=params, timeout=TIMEOUT)
    response.raise_for_status()
    return response.json()

def _model_id(record: dict[str, Any]) -> str | None:
    value = record.get("bmKey") or record.get("bioModelKey") or record.get("biomodelKey")
    return str(value) if value is not None else None

def fetch_biomodel_pages(collection: str, base_params: dict[str, Any], page_size: int = 100) -> list[dict[str, Any]]:
    """Retrieve category models in pages; stop safely if this API ignores startRow."""
    all_rows: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    start_row = 1
    while True:
        params = {**base_params, "startRow": start_row, "maxRows": page_size}
        page = request_json("/biomodel", params)
        if not isinstance(page, list) or not page:
            break
        page_ids = {_model_id(row) for row in page} - {None}
        new_ids = page_ids - seen_ids
        if not new_ids:
            log.warning("VCell repeated a %s page at startRow=%d; stopping pagination", collection, start_row)
            break
        all_rows.extend(row for row in page if _model_id(row) in new_ids)
        seen_ids.update(new_ids)
        log.info("VCell %s: collected %d models", collection, len(seen_ids))
        if len(page) < page_size:
            break
        start_row += page_size
    return all_rows

def fetch_publications() -> list[dict[str, Any]]:
    """Fetch publication records and detect the v0 endpoint's pagination behavior."""
    publications: list[dict[str, Any]] = []
    seen_pages: set[tuple[str, ...]] = set()
    start_row = 1
    # The supplied endpoint asks for 10 rows, but v0 currently returns up to
    # 250. Advance using the actual page length and stop if the server repeats.
    while True:
        params = {**PUBLICATION_QUERY, "startRow": start_row, "maxRows": 250}
        page = request_json("/publication", params)
        if not isinstance(page, list) or not page:
            break
        signature = tuple(str(row.get("pubKey", "")) for row in page)
        if signature in seen_pages:
            log.warning("VCell publication endpoint repeated a page at startRow=%d; stopping", start_row)
            break
        seen_pages.add(signature)
        publications.extend(page)
        log.info("VCell publication records collected: %d", len(publications))
        if len(page) < 250:
            break
        start_row += len(page)
    return publications

def _pub_authors(publication: dict[str, Any]) -> str | None:
    authors = publication.get("authors") or []
    if isinstance(authors, str):
        return authors.strip() or None
    labels = [str(author).strip() for author in authors if str(author).strip()]
    return "; ".join(labels) or None

def collect_target_models() -> dict[str, dict[str, Any]]:
    """Union the requested public VCell collections and publication references."""
    models: dict[str, dict[str, Any]] = {}

    def add_model(record: dict[str, Any], collection: str):
        model_id = _model_id(record)
        if not model_id:
            return
        target = models.setdefault(model_id, {"listing": {}, "collections": set(), "publications": []})
        target["listing"].update(record)
        target["collections"].add(collection)

    publications = fetch_publications()
    publication_count = 0
    for publication in publications:
        publication_record = {
            "publication_id": publication.get("pubKey"),
            "publication_title": publication.get("title"),
            "authors": _pub_authors(publication),
            "pubmed_id": publication.get("pubmedid"),
            "doi": str(publication.get("doi", "")).strip() or None,
            "publication_year": publication.get("year"),
            "citation": publication.get("citation"),
            "publication_url": publication.get("url"),
        }
        for reference in publication.get("biomodelReferences") or []:
            model_id = _model_id(reference)
            if not model_id:
                continue
            add_model(reference, "publication")
            models[model_id]["publications"].append(publication_record)
            publication_count += 1
    log.info("Publication endpoint returned %d publications with %d BioModel references", len(publications), publication_count)

    for collection, params in COLLECTION_QUERIES:
        for record in fetch_biomodel_pages(collection, params):
            add_model(record, collection)

    return models

def get_model_organism(metadata: dict[str, Any], xml_text: str) -> str | None:
    for key in ("organism", "organismName", "taxon", "taxonomy"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    match = re.search(r"(?:taxonomy|taxon|organism)[^>]{0,120}?[^>]*>\s*([^<]{2,120})", xml_text, re.IGNORECASE)
    return match.group(1).strip() if match else None

def _joined_publication_value(publications: list[dict[str, Any]], key: str) -> str | None:
    values = []
    for publication in publications:
        value = publication.get(key)
        if value is not None and str(value).strip():
            values.append(str(value).strip())
    unique = list(dict.fromkeys(values))
    return "; ".join(unique) or None

def sbml_unit_to_string(unit_definition: Any) -> str:
    pieces = []
    kind_names = {getattr(libsbml, name): name.lower() for name in dir(libsbml) if name.startswith("UNIT_KIND_")}
    for i in range(unit_definition.getNumUnits()):
        unit = unit_definition.getUnit(i)
        kind = kind_names.get(unit.getKind(), "unknown").replace("unit_kind_", "")
        exponent, multiplier, scale = unit.getExponent(), unit.getMultiplier(), unit.getScale()
        token = kind
        if scale:
            token = f"{10 ** scale}*{token}"
        if multiplier != 1:
            token = f"{multiplier}*{token}"
        if exponent != 1:
            token = f"({token})**{exponent:g}"
        pieces.append(token)
    return " * ".join(pieces) if pieces else unit_definition.getId()

def extract_from_sbml(model_id: str, sbml_text: str, metadata: dict[str, Any], model_collection: str) -> list[dict[str, Any]]:
    document = libsbml.readSBMLFromString(sbml_text)
    model = document.getModel()
    if model is None:
        return []

    model_name = model.getName() if model.isSetName() else metadata.get("name")
    organism = get_model_organism(metadata, sbml_text)
    publications = metadata.get("publications", [])
    context = {
        "source_database": "VCell",
        "model_collection": model_collection,
        # VCell does not expose a BioModels-style curation flag.
        "curated": None,
        "model_name": model_name,
        "organism": organism,
        "authors": _joined_publication_value(publications, "authors"),
        "publication_id": _joined_publication_value(publications, "publication_id"),
        "publication_title": _joined_publication_value(publications, "publication_title"),
        "cell_type": None, "tissue": None, "disease": None, "pathway": None,
        "modeling_approach": None, "model_type": None,
        "model_format": "SBML",
    }

    unit_map = {}
    for i in range(model.getNumUnitDefinitions()):
        definition = model.getUnitDefinition(i)
        unit_map[definition.getId()] = sbml_unit_to_string(definition)

    records: list[dict[str, Any]] = []
    def add_record(record_type: str, identifier: str, name: str | None,
                   value: Any, units: str | None, compartment: str | None = None):
        records.append({
            **context, "model_id": model_id, "record_type": record_type,
            "parameter_id": identifier, "parameter_name": name, "value": value,
            "units": unit_map.get(units, units) if units else None,
            "compartment": compartment, "reaction_id": None,
            "sbml_file": f"vcell_{model_id}.sbml",
        })

    if model.isSetTimeUnits():
        add_record("time_unit", "model_time", "model time units", None, model.getTimeUnits())

    for i in range(model.getNumCompartments()):
        compartment = model.getCompartment(i)
        units = compartment.getUnits() if compartment.isSetUnits() else model.getVolumeUnits() if model.isSetVolumeUnits() else None
        add_record("compartment_size", compartment.getId(), compartment.getName() if compartment.isSetName() else None,
                   compartment.getSize() if compartment.isSetSize() else None, units, compartment.getId())

    for i in range(model.getNumSpecies()):
        species = model.getSpecies(i)
        units = species.getSubstanceUnits() if species.isSetSubstanceUnits() else model.getSubstanceUnits() if model.isSetSubstanceUnits() else None
        value = species.getInitialAmount() if species.isSetInitialAmount() else species.getInitialConcentration() if species.isSetInitialConcentration() else None
        add_record("species", species.getId(), species.getName() if species.isSetName() else None,
                   value, units, species.getCompartment())

    for i in range(model.getNumParameters()):
        parameter = model.getParameter(i)
        units = parameter.getUnits() if parameter.isSetUnits() else None
        add_record("global_parameter", parameter.getId(), parameter.getName() if parameter.isSetName() else None,
                   parameter.getValue() if parameter.isSetValue() else None, units)

    for i in range(model.getNumReactions()):
        reaction = model.getReaction(i)
        if not reaction.isSetKineticLaw():
            continue
        law = reaction.getKineticLaw()
        if hasattr(law, "getNumLocalParameters"):
            for j in range(law.getNumLocalParameters()):
                parameter = law.getLocalParameter(j)
                units = parameter.getUnits() if parameter.isSetUnits() else None
                add_record("local_kinetic_parameter", parameter.getId(), parameter.getName() if parameter.isSetName() else None,
                           parameter.getValue() if parameter.isSetValue() else None, units)
                records[-1]["reaction_id"] = reaction.getId()

    return records

def metadata_row(model_id: str, item: dict[str, Any], detail: dict[str, Any], model_name: str) -> dict[str, Any]:
    publications = item.get("publications", [])
    listing = item.get("listing", {})
    return {
        "model_id": model_id,
        "source_database": "VCell",
        "model_collection": "; ".join(sorted(item.get("collections", []))),
        "curated": None,
        "model_name": model_name,
        "owner_name": detail.get("ownerName") or listing.get("ownerName"),
        "owner_key": detail.get("ownerKey") or listing.get("ownerKey"),
        "privacy": detail.get("privacy", listing.get("privacy")),
        "saved_date": detail.get("savedDate") or listing.get("savedDate"),
        "branch_id": detail.get("branchID") or listing.get("branchID"),
        "model_key": detail.get("modelKey") or listing.get("modelKey"),
        "authors": _joined_publication_value(publications, "authors"),
        "publication_id": _joined_publication_value(publications, "publication_id"),
        "publication_title": _joined_publication_value(publications, "publication_title"),
        "pubmed_id": _joined_publication_value(publications, "pubmed_id"),
        "doi": _joined_publication_value(publications, "doi"),
        "publication_year": _joined_publication_value(publications, "publication_year"),
        "citation": _joined_publication_value(publications, "citation"),
        "publication_url": _joined_publication_value(publications, "publication_url"),
        "annotation": detail.get("annot") or listing.get("annot"),
    }

def record_failure(model_id: str, stage: str, detail: str):
    rows = {}
    if FAILED_MODELS_CSV.exists():
        with FAILED_MODELS_CSV.open(newline="", encoding="utf-8") as handle:
            rows = {row["model_id"]: row for row in csv.DictReader(handle) if row.get("model_id")}
    row = rows.get(model_id, {"model_id": model_id, "stage": "", "details": ""})
    stages = set(filter(None, row["stage"].split(";")))
    stages.add(stage)
    details = set(filter(None, row["details"].split("; ")))
    details.add(detail)
    rows[model_id] = {"model_id": model_id, "stage": ";".join(sorted(stages)), "details": "; ".join(sorted(details))}
    with FAILED_MODELS_CSV.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["model_id", "stage", "details"])
        writer.writeheader()
        writer.writerows(rows[key] for key in sorted(rows))

def main():
    parser = argparse.ArgumentParser(description="Extract selected public VCell models to data/vcell/.")
    parser.add_argument("--restart", action="store_true", help="start fresh instead of resuming models already in models_metadata.csv")
    args = parser.parse_args()
    models = collect_target_models()
    log.info("Unique VCell public models selected: %d", len(models))
    resume_ids: set[str] = set()
    if not args.restart and MODEL_METADATA_CSV.exists():
        with MODEL_METADATA_CSV.open(newline="", encoding="utf-8") as handle:
            resume_ids = {row["model_id"] for row in csv.DictReader(handle) if row.get("model_id")}
    raw_mode = "a" if resume_ids else "w"
    metadata_mode = "a" if resume_ids else "w"
    with OUTPUT_CSV.open(raw_mode, newline="", encoding="utf-8") as raw_handle, MODEL_METADATA_CSV.open(metadata_mode, newline="", encoding="utf-8") as metadata_handle:
        raw_writer = csv.DictWriter(raw_handle, fieldnames=CSV_FIELDS)
        metadata_writer = csv.DictWriter(metadata_handle, fieldnames=MODEL_METADATA_FIELDS)
        if raw_mode == "w":
            raw_writer.writeheader()
        if metadata_mode == "w":
            metadata_writer.writeheader()
        for index, (model_id, item) in enumerate(sorted(models.items()), start=1):
            if model_id in resume_ids:
                continue
            log.info("[%d/%d] Processing VCell BioModel %s", index, len(models), model_id)
            try:
                detail = request_json(f"/biomodel/{model_id}")
                privacy = detail.get("privacy")
                if privacy is None:
                    privacy = item.get("listing", {}).get("privacy")
                if privacy is not None and int(privacy) != 0:
                    log.info("Skipping non-public model %s", model_id)
                    continue
                response = session.get(f"{API}/biomodel/{model_id}/biomodel.sbml", timeout=TIMEOUT)
                response.raise_for_status()
                sbml_text = response.text
                document = libsbml.readSBMLFromString(sbml_text)
                model = document.getModel()
                if model is None:
                    record_failure(model_id, "no_parseable_sbml", "SBML response did not contain a model")
                    continue
                model_name = model.getName() if model.isSetName() else detail.get("name") or item.get("listing", {}).get("name")
                context_item = {
                    **detail,
                    "publications": item.get("publications", []),
                    "name": model_name or detail.get("name") or item.get("listing", {}).get("name"),
                }
                metadata_writer.writerow(metadata_row(model_id, item, detail, model_name or ""))
                records = extract_from_sbml(model_id, sbml_text, context_item, "; ".join(sorted(item["collections"])))
                for record in records:
                    raw_writer.writerow({key: record.get(key) for key in CSV_FIELDS})
                raw_handle.flush()
                metadata_handle.flush()
            except Exception as exc:
                log.warning("Failed processing VCell model %s: %s", model_id, exc)
                record_failure(model_id, "model_processing", str(exc))
            time.sleep(PAUSE_SECONDS)

if __name__ == "__main__":
    main()
