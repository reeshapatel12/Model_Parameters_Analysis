from __future__ import annotations

import csv
import io
import json
import logging
import re
import time
import zipfile
from pathlib import Path
from typing import Any

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import libsbml

ROOT = Path(__file__).resolve().parent
RAW_DIR = ROOT / "data" / "raw"
CONFIG_DIR = ROOT / "config"
RAW_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_DIR.mkdir(parents=True, exist_ok=True)

API = "https://www.biomodels.org"
TIMEOUT = 90
PAUSE_SECONDS = 0.15
OUTPUT_CSV = RAW_DIR / "parameters_raw.csv"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("biomodels-extractor")

session = requests.Session()
retry = Retry(total=5, backoff_factor=1, status_forcelist=(429, 500, 502, 503, 504), allowed_methods=("GET",))
session.mount("https://", HTTPAdapter(max_retries=retry))
session.headers.update({"User-Agent": "BioModelsParameterResearch/1.0"})

CSV_FIELDS = [
    "model_id", "model_name", "organism", "record_type",
    "parameter_id", "parameter_name", "value", "units",
    "compartment", "reaction_id", "sbml_file", "curated"
]

def get_all_public_model_ids() -> list[str]:
    try:
        from biomodels_restful_api_client import services as bmservices
    except ImportError as exc:
        raise RuntimeError("Install requirements first: pip install -r requirements.txt") from exc

    result = bmservices.get_model_identifiers()
    # BioModels uses BIOMD identifiers for curated models. Filtering here keeps
    # non-curated MODEL* identifiers out of both the download and output CSV.
    ids = sorted(mid for mid in set(result.get("models", [])) if mid.startswith("BIOMD"))
    log.info("Found %d public model identifiers", len(ids))
    return ids

def fetch_model_metadata(model_id: str) -> dict[str, Any]:
    try:
        response = session.get(f"{API}/{model_id}?format=json", timeout=TIMEOUT)
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        log.warning("Metadata request failed for %s: %s", model_id, exc)
        return {}

def get_model_organism(metadata: dict[str, Any], xml_text: str) -> str | None:
    keys = ("organism", "organismName", "taxon", "taxonomy", "species")
    def search(obj: Any) -> str | None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k.lower() in {key.lower() for key in keys} and isinstance(v, (str, int)):
                    return str(v)
                found = search(v)
                if found: return found
        elif isinstance(obj, list):
            for v in obj:
                found = search(v)
                if found: return found
        return None
    found = search(metadata)
    if found: return found
    match = re.search(r"(?:taxonomy|taxon|organism)[^>]{0,100}?(?:resource|id|name)?[^>]*>\s*([^<]{2,100})", xml_text, flags=re.IGNORECASE)
    return match.group(1).strip() if match else None

def sbml_unit_to_string(unit_definition: Any) -> str:
    """Render an SBML UnitDefinition as a compact, readable expression."""
    pieces = []
    kind_names = {getattr(libsbml, name): name.lower() for name in dir(libsbml) if name.startswith("UNIT_KIND_")}
    for i in range(unit_definition.getNumUnits()):
        unit = unit_definition.getUnit(i)
        kind = kind_names.get(unit.getKind(), "unknown").replace("unit_kind_", "")
        exponent, multiplier, scale = unit.getExponent(), unit.getMultiplier(), unit.getScale()
        token = kind
        if scale: token = f"{10 ** scale}*{token}"
        if multiplier != 1: token = f"{multiplier}*{token}"
        if exponent != 1: token = f"({token})**{exponent:g}"
        pieces.append(token)
    return " * ".join(pieces) if pieces else unit_definition.getId()

def extract_from_sbml(model_id: str, sbml_path: Path, metadata: dict[str, Any]) -> list[dict[str, Any]]:
    document = libsbml.readSBMLFromFile(str(sbml_path))
    model = document.getModel()
    if model is None: return []

    model_name = model.getName() if model.isSetName() else metadata.get("name")
    xml_text = sbml_path.read_text(errors="ignore")
    organism = get_model_organism(metadata, xml_text)
    
    # Unit attributes may refer to named <unitDefinition>s. Resolve those IDs
    # once so output contains their definitions instead of opaque references.
    unit_map = {}
    for i in range(model.getNumUnitDefinitions()):
        defn = model.getUnitDefinition(i)
        unit_map[defn.getId()] = sbml_unit_to_string(defn)

    records = []

    # Keep record construction consistent across all SBML element types. The
    # curated flag is true because the caller only supplies BIOMD model IDs.
    def add_record(record_type: str, parameter_id: str, name: str | None,
                   value: Any, units: str | None, compartment: str | None = None):
        records.append({
            "model_id": model_id, "model_name": model_name, "organism": organism,
            "record_type": record_type, "parameter_id": parameter_id,
            "parameter_name": name, "value": value,
            "units": unit_map.get(units, units) if units else None,
            "compartment": compartment, "reaction_id": None,
            "sbml_file": sbml_path.name, "curated": True,
        })

    # Time units belong to the <model> element (timeUnits in SBML Level 3).
    # This is a metadata record: its value is empty and units holds the unit.
    if model.isSetTimeUnits():
        add_record("time_unit", "model_time", "model time units", None, model.getTimeUnits())

    # Size comes only from <compartment>. Compartment units are preferred;
    # model volumeUnits is the SBML default when the compartment omits units.
    for i in range(model.getNumCompartments()):
        compartment = model.getCompartment(i)
        units = compartment.getUnits() if compartment.isSetUnits() else model.getVolumeUnits() if model.isSetVolumeUnits() else None
        add_record("compartment_size", compartment.getId(), compartment.getName() if compartment.isSetName() else None,
                   compartment.getSize() if compartment.isSetSize() else None, units, compartment.getId())
    # Species quantities and units come only from <species>. SBML stores either
    # initialAmount or initialConcentration; substanceUnits is the declared
    # species unit, with model substanceUnits as its default when omitted.
    for i in range(model.getNumSpecies()):
        species = model.getSpecies(i)
        units = species.getSubstanceUnits() if species.isSetSubstanceUnits() else model.getSubstanceUnits() if model.isSetSubstanceUnits() else None
        add_record("species", species.getId(), species.getName() if species.isSetName() else None,
                   species.getInitialAmount() if species.isSetInitialAmount() else species.getInitialConcentration() if species.isSetInitialConcentration() else None,
                   units, species.getCompartment())

    for i in range(model.getNumParameters()):
        p = model.getParameter(i)
        units = p.getUnits() if p.isSetUnits() else None
        add_record("global_parameter", p.getId(), p.getName() if p.isSetName() else None,
                   p.getValue() if p.isSetValue() else None, units)

    for i in range(model.getNumReactions()):
        rxn = model.getReaction(i)
        if not rxn.isSetKineticLaw(): 
            continue
        law = rxn.getKineticLaw()
        
        # SBML Level 3 calls these LocalParameters. Extract them when the
        # installed libSBML exposes that API; reaction ID keeps them traceable.
        local_params = []
        if hasattr(law, "getNumLocalParameters") and law.getNumLocalParameters() > 0:
            for j in range(law.getNumLocalParameters()):
                local_params.append(law.getLocalParameter(j))

        for p in local_params:
            units = p.getUnits() if p.isSetUnits() else None
            add_record("local_kinetic_parameter", p.getId(), p.getName() if p.isSetName() else None,
                       p.getValue() if p.isSetValue() else None, units)
            records[-1]["reaction_id"] = rxn.getId()

    return records

def main():
    # No sample limit is applied: this run covers all IDs in the curated branch.
    ids = get_all_public_model_ids()
    with OUTPUT_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()

        for index, model_id in enumerate(ids, start=1):
            log.info("[%d/%d] Processing %s", index, len(ids), model_id)
            metadata = fetch_model_metadata(model_id)
            
            try:
                response = session.get(f"{API}/model/download/{model_id}", timeout=TIMEOUT)
                response.raise_for_status()
                if not response.content.startswith(b"PK"):
                    continue
                
                # BioModels downloads are OMEX ZIP archives. Parse each SBML
                # document inside the archive and remove the temporary file
                # immediately after extraction to avoid accumulating files.
                with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
                    for member in zf.infolist():
                        if member.is_dir() or not member.filename.lower().endswith((".xml", ".sbml")):
                            continue
                        # Extract directly to memory/temp without saving thousands of OMEX files permanently
                        xml_bytes = zf.read(member)
                        temp_xml = RAW_DIR / f"temp_{model_id}.xml"
                        temp_xml.write_bytes(xml_bytes)
                        records = extract_from_sbml(model_id, temp_xml, metadata)
                        for r in records:
                            writer.writerow({k: r.get(k) for k in CSV_FIELDS})
                        temp_xml.unlink(missing_ok=True)
            except Exception as exc:
                log.warning("Failed processing %s: %s", model_id, exc)
            
            time.sleep(PAUSE_SECONDS)

if __name__ == "__main__":
    main()
