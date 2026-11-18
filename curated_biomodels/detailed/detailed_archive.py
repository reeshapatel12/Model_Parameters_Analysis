"""Download and inspect BioModels OMEX archives for embedded SBML files."""
from __future__ import annotations

import io
from pathlib import Path
import time
import zipfile
import xml.etree.ElementTree as ET

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from detailed_config import BIO_MODELS_API
from jws_sbml_utils import local


class NoSBMLDocumentsError(ValueError):
    """The BioModels archive is readable but contains no SBML model document."""


def new_session() -> requests.Session:
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=Retry(
        total=4, backoff_factor=0.75, status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
    )))
    session.headers.update({"User-Agent": "BioModelsDetailedAnnotationExport/1.0"})
    return session


def archive_url(model_id: str) -> str:
    return f"{BIO_MODELS_API}/model/download/{model_id}"


def model_page_url(model_id: str) -> str:
    return f"{BIO_MODELS_API}/{model_id}"


def fetch_archive(session, model_id: str, cache_dir: Path, delay: float) -> bytes:
    """Return a cached OMEX archive or download and cache it."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{model_id}.omex"
    if path.exists() and path.stat().st_size > 10:
        return path.read_bytes()

    time.sleep(delay)
    response = session.get(archive_url(model_id), timeout=(15, 90))
    response.raise_for_status()
    if not response.content.startswith(b"PK"):
        raise ValueError("BioModels download was not an OMEX ZIP archive")
    path.write_bytes(response.content)
    return response.content


def sbml_documents(archive_data: bytes) -> tuple[list[tuple[str, bytes]], list[str]]:
    """Return SBML XML members, including models in nested OMEX archives."""
    documents = []
    errors = []

    def scan_zip(archive: zipfile.ZipFile, prefix: str, depth: int) -> None:
        for member in archive.infolist():
            if member.is_dir():
                continue
            name = f"{prefix}{member.filename}"
            lower_name = member.filename.lower()
            if lower_name.endswith((".xml", ".sbml")):
                payload = archive.read(member)
                try:
                    root = ET.fromstring(payload)
                except ET.ParseError as exc:
                    errors.append(f"{name}: {exc}")
                    continue
                if any(local(child.tag) == "model" for child in root):
                    documents.append((name, payload))
            elif lower_name.endswith(".omex") and depth < 3:
                try:
                    nested_data = archive.read(member)
                    with zipfile.ZipFile(io.BytesIO(nested_data)) as nested:
                        scan_zip(nested, f"{name}!/", depth + 1)
                except (OSError, zipfile.BadZipFile) as exc:
                    errors.append(f"{name}: nested OMEX error: {exc}")

    with zipfile.ZipFile(io.BytesIO(archive_data)) as archive:
        scan_zip(archive, "", 0)
    return documents, errors


def cellml_documents(archive_data: bytes) -> list[tuple[str, bytes]]:
    """Return CellML model files when a curated record has no SBML."""
    documents = []

    def scan_zip(archive: zipfile.ZipFile, prefix: str, depth: int) -> None:
        for member in archive.infolist():
            if member.is_dir():
                continue
            name = f"{prefix}{member.filename}"
            lower_name = member.filename.lower()
            if lower_name.endswith(".cellml"):
                payload = archive.read(member)
                try:
                    root = ET.fromstring(payload)
                except ET.ParseError:
                    continue
                if local(root.tag) == "model" and any("cellml.org" in key for key in root.attrib):
                    documents.append((name, payload))
            elif lower_name.endswith(".omex") and depth < 3:
                try:
                    nested_data = archive.read(member)
                    with zipfile.ZipFile(io.BytesIO(nested_data)) as nested:
                        scan_zip(nested, f"{name}!/", depth + 1)
                except (OSError, zipfile.BadZipFile):
                    continue

    with zipfile.ZipFile(io.BytesIO(archive_data)) as archive:
        scan_zip(archive, "", 0)
    return documents
