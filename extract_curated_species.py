"""Extract species details from curated BioModels SBML records only."""
from __future__ import annotations

import io
import logging
import re
import time
import zipfile
from html.parser import HTMLParser
from pathlib import Path

import libsbml
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from extract_params import get_all_public_model_ids, get_model_organism

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "data" / "curated" / "annotations" / "species_raw.csv"
API = "https://www.biomodels.org"
TIMEOUT = 90
PAUSE_SECONDS = 0.15
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("curated-species")
session = requests.Session()
session.mount("https://", HTTPAdapter(max_retries=Retry(
    total=5, backoff_factor=1, status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=("GET",),
)))
session.headers.update({"User-Agent": "BioModelsParameterResearch/1.0"})


class _TextOnly(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.parts.append(data.strip())


def notes_text(species) -> str | None:
    if not species.isSetNotes():
        return None
    parser = _TextOnly()
    parser.feed(species.getNotesString() or "")
    result = " ".join(parser.parts)
    return result or None


def species_annotations(species) -> str | None:
    annotation = species.getAnnotationString() or ""
    ids: set[str] = set()
    for match in re.finditer(
        r"(?:identifiers\.org/|urn:miriam:)([A-Za-z][A-Za-z0-9_.-]*)/([A-Za-z0-9_:.-]+)",
        annotation, re.I,
    ):
        namespace, accession = match.groups()
        accession = accession.rstrip(".,;)")
        if accession.upper().startswith("CHEBI:"):
            ids.add(accession.upper())
        else:
            ids.add(f"{namespace.lower()}/{accession}")
    return "; ".join(sorted(ids)) or None


def extract_archive(model_id: str, metadata: dict, archive: bytes) -> list[dict]:
    rows = []
    with zipfile.ZipFile(io.BytesIO(archive)) as zf:
        for member in zf.infolist():
            if member.is_dir() or not member.filename.lower().endswith((".xml", ".sbml")):
                continue
            document = libsbml.readSBMLFromString(zf.read(member).decode("utf-8", errors="replace"))
            model = document.getModel()
            if model is None:
                continue
            organism = get_model_organism(metadata, "")
            unit_map = {}
            for index in range(model.getNumUnitDefinitions()):
                definition = model.getUnitDefinition(index)
                # Import the extractor's SBML unit formatter to resolve named units.
                from extract_params import sbml_unit_to_string
                unit_map[definition.getId()] = sbml_unit_to_string(definition)
            for index in range(model.getNumSpecies()):
                sp = model.getSpecies(index)
                raw_unit = (sp.getSubstanceUnits() if sp.isSetSubstanceUnits()
                            else model.getSubstanceUnits() if model.isSetSubstanceUnits() else None)
                value = (sp.getInitialAmount() if sp.isSetInitialAmount()
                         else sp.getInitialConcentration() if sp.isSetInitialConcentration() else None)
                rows.append({
                    "Database": "BioModels", "Biomodel_id": model_id,
                    "species_id": sp.getId(),
                    "species_name": sp.getName() if sp.isSetName() else None,
                    "organism": organism, "notes": notes_text(sp),
                    "species_annotations": species_annotations(sp),
                    "initial_value": value,
                    "units": unit_map.get(raw_unit, raw_unit) if raw_unit else None,
                })
            # An OMEX can contain multiple SBML documents; process them all.
    return rows


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    ids = get_all_public_model_ids()
    for index, model_id in enumerate(ids, 1):
        log.info("[%d/%d] Processing %s", index, len(ids), model_id)
        try:
            response = session.get(f"{API}/{model_id}?format=json", timeout=TIMEOUT)
            response.raise_for_status()
            metadata = response.json()
            archive = session.get(f"{API}/model/download/{model_id}", timeout=TIMEOUT)
            archive.raise_for_status()
            if not archive.content.startswith(b"PK"):
                raise ValueError("BioModels download was not an OMEX ZIP archive")
            rows.extend(extract_archive(model_id, metadata, archive.content))
        except Exception as exc:
            log.warning("Could not extract species for %s: %s", model_id, exc)
        time.sleep(PAUSE_SECONDS)
    columns = ["Database", "Biomodel_id", "species_id", "species_name", "organism",
               "notes", "species_annotations", "initial_value", "units"]
    pd.DataFrame(rows, columns=columns).to_csv(OUTPUT, index=False)
    log.info("Wrote %d species rows to %s", len(rows), OUTPUT)


if __name__ == "__main__":
    main()
