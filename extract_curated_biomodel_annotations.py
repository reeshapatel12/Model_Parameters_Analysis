"""Build a model-level annotation table for curated BioModels entries.

The three annotation columns contain semicolon-separated identifiers in the
given namespaces. The requested identifiers are retained as ordinary values,
so downstream analysis can compare them with other annotations.
"""
from __future__ import annotations

import io
import logging
import re
import time
import zipfile
from pathlib import Path
from typing import Any

import libsbml
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "data" / "curated" / "statistics" / "curated_biomodel_annotations.csv"
API = "https://www.biomodels.org"
TIMEOUT = 90
PAUSE_SECONDS = 0.15
NAMESPACES = {"go": "GO", "taxonomy": "taxonomy", "mamo": "MAMO"}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("biomodel-annotations")
session = requests.Session()
session.mount("https://", HTTPAdapter(max_retries=Retry(
    total=5, backoff_factor=1, status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=("GET",),
)))
session.headers.update({"User-Agent": "BioModelsParameterResearch/1.0"})


def curated_model_ids() -> list[str]:
    """Return only public curated BioModels identifiers (BIOMD records)."""
    try:
        from biomodels_restful_api_client import services
    except ImportError as exc:
        raise RuntimeError("Install requirements first: pip install -r requirements.txt") from exc
    result = services.get_model_identifiers()
    return sorted({str(mid) for mid in result.get("models", []) if str(mid).startswith("BIOMD")})


def _resource_ids(annotation: str) -> dict[str, set[str]]:
    found = {name: set() for name in NAMESPACES}
    # BioModels SBML annotations normally use identifiers.org/{namespace}/{id}.
    for namespace in NAMESPACES:
        for match in re.finditer(
            rf"(?:identifiers\.org/|urn:miriam:){namespace}/([A-Za-z0-9_:.-]+)",
            annotation, re.I,
        ):
            accession = match.group(1).rstrip(".,;)")
            found[namespace].add(accession)
    return found


def model_annotation_row(model_id: str, metadata: dict[str, Any], archive: bytes) -> dict[str, Any]:
    with zipfile.ZipFile(io.BytesIO(archive)) as zf:
        for member in zf.infolist():
            if member.is_dir() or not member.filename.lower().endswith((".xml", ".sbml")):
                continue
            document = libsbml.readSBMLFromString(zf.read(member).decode("utf-8", errors="replace"))
            model = document.getModel()
            if model is None:
                continue
            annotation = model.getAnnotationString() or ""
            identifiers = _resource_ids(annotation)
            return {
                "database": "BioModels",
                "biomodel_id": model_id,
                "biomodel_name": model.getName() if model.isSetName() else metadata.get("name"),
                **{key: "; ".join(sorted(identifiers[key])) or pd.NA for key in NAMESPACES},
            }
    return {
        "database": "BioModels", "biomodel_id": model_id,
        "biomodel_name": metadata.get("name"), "go": pd.NA,
        "taxonomy": pd.NA, "mamo": pd.NA,
    }


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    ids = curated_model_ids()
    for index, model_id in enumerate(ids, 1):
        log.info("[%d/%d] Fetching %s", index, len(ids), model_id)
        try:
            metadata_response = session.get(f"{API}/{model_id}?format=json", timeout=TIMEOUT)
            metadata_response.raise_for_status()
            metadata = metadata_response.json()
            archive_response = session.get(f"{API}/model/download/{model_id}", timeout=TIMEOUT)
            archive_response.raise_for_status()
            if not archive_response.content.startswith(b"PK"):
                raise ValueError("BioModels download was not an OMEX ZIP archive")
            rows.append(model_annotation_row(model_id, metadata, archive_response.content))
        except Exception as exc:
            log.warning("Could not extract annotations for %s: %s", model_id, exc)
            rows.append({"database": "BioModels", "biomodel_id": model_id,
                         "biomodel_name": pd.NA, "go": pd.NA,
                         "taxonomy": pd.NA, "mamo": pd.NA})
        time.sleep(PAUSE_SECONDS)
    columns = ["database", "biomodel_id", "biomodel_name", "go", "taxonomy", "mamo"]
    pd.DataFrame(rows, columns=columns).to_csv(OUTPUT, index=False)
    log.info("Wrote %d curated models to %s", len(rows), OUTPUT)


if __name__ == "__main__":
    main()
