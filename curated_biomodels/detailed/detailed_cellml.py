"""Read direct RDF annotations attached to CellML variables and model elements."""
from __future__ import annotations

import xml.etree.ElementTree as ET

from detailed_config import HEADERS
from jws_config import RDF_RESOURCE, QUALIFIER_NAMESPACES
from jws_sbml_utils import cv_id, local, numeric

RDF_ABOUT = "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}about"
META_ID = "{http://www.cellml.org/metadata/1.0#}id"


def _direct_links(description):
    links = set()
    for qualifier_node in description:
        namespace = qualifier_node.tag[1:].split("}", 1)[0] if qualifier_node.tag.startswith("{") else ""
        if namespace not in QUALIFIER_NAMESPACES:
            continue
        prefix = (
            "bqbiol" if namespace == QUALIFIER_NAMESPACES[0] else
            "bqmodel" if namespace == QUALIFIER_NAMESPACES[1] else "dc"
        )
        for node in qualifier_node.iter():
            uri = node.attrib.get(RDF_RESOURCE, "")
            if uri.startswith(("https://", "http://", "urn:")):
                links.add((f"{prefix}:{local(qualifier_node.tag)}", uri))
    return sorted(links)


def extract_cellml_annotations(model_id, source_file, xml_bytes, archive_url, page_url):
    root = ET.fromstring(xml_bytes)
    elements = {}
    component_by_id = {}
    for component in root.iter():
        if local(component.tag) != "component":
            continue
        component_name = component.get("name", "")
        for variable in component:
            if local(variable.tag) == "variable" and variable.get(META_ID):
                key = variable.get(META_ID)
                elements[key] = variable
                component_by_id[key] = component_name

    tables = {name: [] for name in HEADERS if name != "Model Inventory"}
    link_count = 0
    for description in root.iter():
        if local(description.tag) != "Description":
            continue
        target = description.get(RDF_ABOUT, "").lstrip("#")
        links = _direct_links(description)
        if not links:
            continue
        variable = elements.get(target)
        if variable is None:
            continue

        element_id = variable.get("name", target)
        qualifiers = "; ".join(sorted({qualifier for qualifier, _ in links}))
        annotation_ids = "; ".join(cv_id(uri)[1] for _, uri in links)
        annotation_urls = "; ".join(uri for _, uri in links)
        prop = "initial_value" if "initial_value" in variable.attrib else ""
        value = numeric(variable.get(prop)) if prop else ""
        tables["Annotated Elements"].append([
            None, model_id, "variable", element_id, element_id,
            component_by_id.get(target, ""), qualifiers, annotation_ids,
            annotation_urls, prop, value, variable.get("units", ""),
            "", "", "", "", "", "", "", f"CellML source: {source_file}",
            archive_url, page_url,
        ])
        for qualifier, uri in links:
            database, database_id = cv_id(uri)
            tables["Annotation Links"].append([
                model_id, "variable", element_id, qualifier, database,
                database_id, uri, archive_url,
            ])
            link_count += 1

    stats = {
        "Directly annotated elements": len(tables["Annotated Elements"]),
        "Annotated species": 0,
        "Annotated reactions": 0,
        "Total reactions": 0,
        "Total parameters": 0,
        "Direct RDF links": link_count,
    }
    return tables, stats
