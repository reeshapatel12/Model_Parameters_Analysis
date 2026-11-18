"""Download and read revision-specific Physiome archives, with a local cache."""
from __future__ import annotations

import io
import tarfile
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from cellml_detail_config import BASE_URL, CACHE_DIR


def session() -> requests.Session:
    client = requests.Session()
    retry = Retry(total=3, connect=3, read=2, backoff_factor=0.5,
                  status_forcelist=(429, 500, 502, 503, 504), allowed_methods=("GET",))
    client.mount("https://", HTTPAdapter(max_retries=retry))
    client.headers["User-Agent"] = "CellMLModelAnnotationResearch/1.0"
    return client


def read_archive(workspace: str, revision: str, client: requests.Session):
    """Return {archive-relative path: CellML XML bytes}; cache archive files."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / f"{workspace}_{revision}.tgz"
    if not cache_file.exists() or cache_file.stat().st_size == 0:
        url = f"{BASE_URL}/workspace/{workspace}/@@archive/{revision}/tgz"
        response = client.get(url, timeout=(20, 120))
        response.raise_for_status()
        cache_file.write_bytes(response.content)
    result = {}
    with tarfile.open(cache_file, "r:gz") as archive:
        for member in archive.getmembers():
            if member.isfile() and member.name.lower().endswith(".cellml"):
                stream = archive.extractfile(member)
                if stream:
                    result[member.name.lstrip("./")] = stream.read()
    return result
