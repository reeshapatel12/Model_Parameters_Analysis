"""Extract RDF annotations and pair them with resolved CellML values."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from urllib.parse import urljoin

from cellml_detail_config import BASE_URL
from cellml_detail_values import local, resolve_variable_values

RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
QUALIFIERS = {
    "http://biomodels.net/biology-qualifiers/": "bqbiol",
    "http://biomodels.net/model-qualifiers/": "bqmodel",
    "http://purl.org/dc/terms/": "dcterms",
    "http://purl.org/dc/elements/1.1/": "dc",
}
LABELS = {"label", "title", "description", "comment"}


def source_url(model: dict) -> str:
    exposure = (model.get("exposure_id", "").split(";")[0]).strip()
    path = model.get("source_file", "").lstrip("/")
    return urljoin(BASE_URL, f"/e/{exposure}/{path}/source_text")


def _identifier(uri: str):
    clean = uri.strip()
    if clean.startswith("urn:miriam:"):
        clean = "https://identifiers.org/" + clean[len("urn:miriam:"):].replace(":", "/", 1)
    if "identifiers.org/" in clean:
        tail = clean.split("identifiers.org/", 1)[1].strip("/")
        database, _, accession = tail.partition("/")
        database = {"uniprot": "UniProt", "chebi": "ChEBI", "obo.chebi": "ChEBI",
                    "taxonomy": "NCBI Taxonomy", "pubmed": "PubMed", "go": "GO",
                    "obo.go": "GO", "ec-code": "EC"}.get(database.lower(), database)
        if database == "ChEBI" and accession.startswith("CHEBI:"):
            accession = accession[6:]
        if database == "GO" and accession.startswith("GO:"):
            accession = accession[3:]
        return database, accession
    return "", clean


def _rdf_records(root: ET.Element):
    records = {}
    labels = {}
    for rdf in root.iter():
        if local(rdf.tag) != "RDF":
            continue
        for description in rdf:
            subject = description.get(f"{{{RDF}}}about", "")
            if subject.startswith("#"):
                subject = subject[1:]
            if not subject:
                continue
            links = []
            for qualifier in description:
                namespace = qualifier.tag[1:].split("}", 1)[0] if qualifier.tag.startswith("{") else ""
                qualifier_name = local(qualifier.tag)
                prefix = QUALIFIERS.get(namespace)
                if prefix:
                    for item in qualifier.iter():
                        uri = item.get(f"{{{RDF}}}resource", "")
                        if uri:
                            links.append((f"{prefix}:{qualifier_name}", uri))
                if qualifier_name in LABELS:
                    value = " ".join("".join(qualifier.itertext()).split())
                    if value:
                        labels.setdefault(subject, []).append(value)
            records.setdefault(subject, []).extend(links)
    return records, labels


def extract_model(model: dict, xml_bytes: bytes):
    root = ET.fromstring(xml_bytes)
    resolved = resolve_variable_values(root)
    rdf_records, labels = _rdf_records(root)
    by_meta = {}
    for component in root.iter():
        if local(component.tag) != "component":
            continue
        component_name = component.get("name", "")
        component_meta = component.get("{http://www.cellml.org/metadata/1.0#}id", "")
        for variable in component:
            if local(variable.tag) != "variable":
                continue
            key = (component_name, variable.get("name", ""))
            meta = variable.get("{http://www.cellml.org/metadata/1.0#}id", "")
            if meta:
                by_meta[meta] = ("Variable", f"{key[1]} ({component_name})", resolved[key])
        if component_meta:
            by_meta[component_meta] = ("Component", component_name, None)

    # Model-level cmeta id, if present.
    model_meta = root.get("{http://www.cellml.org/metadata/1.0#}id", "")
    if model_meta:
        by_meta[model_meta] = ("Model", model.get("model_name", ""), None)

    annotations, quantified = [], []
    url = source_url(model)
    display_name = model.get("model_name") or model.get("source_file", "")
    for element_id, (kind, element_name, value_info) in by_meta.items():
        info = value_info or {}
        value = info.get("value")
        status = info.get("status", "Not verified")
        caution = info.get("notes", "Component/model annotations do not identify a scalar variable value.")
        for relation, uri in sorted(set(rdf_records.get(element_id, []))):
            database, accession = _identifier(uri)
            annotations.append({
                "CellML model": display_name, "Annotated model element": element_name,
                "Element type": kind, "Database": database, "Database ID": accession,
                "Annotation link": uri, "Annotation relation": relation,
                "Numerical value": value if value is not None else "",
                "CellML units": info.get("units", ""), "Value status": status,
                "Biological interpretation": "; ".join(labels.get(element_id, [])),
                "Value resolution / caution": caution,
                "Annotation source": url, "Numerical value evidence": url if value is not None else "",
            })

    for (component, variable), info in resolved.items():
        quantified.append({
            "CellML model": display_name, "Element": f"{variable} ({component})",
            "Numerical value": info["value"] if info["value"] is not None else "",
            "CellML units": info["units"], "Value provenance": info["status"],
            "Notes": info["notes"], "Value evidence": url if info["value"] is not None else "",
        })
    return annotations, quantified, len(by_meta)
