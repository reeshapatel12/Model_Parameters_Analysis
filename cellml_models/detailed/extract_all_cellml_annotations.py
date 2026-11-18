"""Extract annotations and values from every CellML source in the PMR catalog."""
from __future__ import annotations

import logging
import posixpath
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from cellml_detail_annotations import extract_model
from cellml_detail_archive import read_archive, session
from cellml_detail_catalog import load_cellml_catalog
from cellml_detail_export import write_outputs

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
LOG = logging.getLogger("cellml-detail-extractor")


def _match_file(model: dict, archive_files: dict[str, bytes]):
    desired = model.get("source_file", "").lstrip("./")
    if desired in archive_files:
        return archive_files[desired]
    basename_matches = [data for path, data in archive_files.items()
                        if posixpath.basename(path) == posixpath.basename(desired)]
    if len(basename_matches) == 1:
        return basename_matches[0]
    return None


def main():
    catalog, models, groups = load_cellml_catalog()
    LOG.info("Catalog has %d records, %d CellML files in %d archive revisions",
             len(catalog), len(models), len(groups))
    client = session()
    archive_contents = {}
    failures = {}

    def fetch(item):
        key, rows = item
        workspace, revision = key
        try:
            return key, read_archive(workspace, revision, client), None
        except Exception as exc:
            return key, {}, str(exc)

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(fetch, item) for item in groups.items()]
        for index, future in enumerate(as_completed(futures), start=1):
            key, contents, error = future.result()
            archive_contents[key] = contents
            if error:
                failures[key] = error
                LOG.warning("Archive %s/%s failed: %s", key[0], key[1], error)
            if index % 20 == 0 or index == len(futures):
                LOG.info("Fetched archive revisions %d/%d", index, len(futures))

    annotations, quantified, audit = [], [], []
    success_count = 0
    for index, model in enumerate(models, start=1):
        key = (model["workspace_id"], model["revision_id"])
        base = {
            "Model ID": model.get("model_id", ""),
            "CellML model": model.get("model_name", "") or model.get("source_file", ""),
            "Workspace": key[0], "Revision": key[1], "Source file": model.get("source_file", ""),
            "Exposure IDs": model.get("exposure_id", ""),
        }
        error = failures.get(key, "")
        try:
            xml_bytes = _match_file(model, archive_contents.get(key, {}))
            if not xml_bytes:
                raise FileNotFoundError(f"Source file not found in archive: {model.get('source_file')}")
            model_annotations, model_quantified, element_count = extract_model(model, xml_bytes)
            annotations.extend(model_annotations)
            quantified.extend(model_quantified)
            success_count += 1
            audit.append({**base, "Status": "parsed", "Annotated elements": element_count,
                          "Annotation links": len(model_annotations),
                          "Quantified elements": len(model_quantified), "Error": ""})
        except Exception as exc:
            audit.append({**base, "Status": "failed", "Annotated elements": 0,
                          "Annotation links": 0, "Quantified elements": 0,
                          "Error": f"{error}; {exc}".strip("; ")})
        if index % 100 == 0 or index == len(models):
            LOG.info("Processed CellML files %d/%d", index, len(models))

    summary = {"catalog_count": len(catalog), "model_count": len(models),
               "archive_count": len(groups), "success_count": success_count,
               "failed_count": len(models) - success_count}
    write_outputs(annotations, quantified, audit, summary)
    LOG.info("Wrote %d annotation associations and %d quantified elements to detailed_cellml",
             len(annotations), len(quantified))


if __name__ == "__main__":
    main()
