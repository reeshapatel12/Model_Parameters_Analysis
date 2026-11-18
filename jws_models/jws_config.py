"""Shared JWS repository settings and workbook columns."""

ROOT_URL = "https://jjj.mib.ac.uk"
INDEX = f"{ROOT_URL}/models/"
RDF_RESOURCE = "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}resource"
QUALIFIER_NAMESPACES = (
    "http://biomodels.net/biology-qualifiers/",
    "http://biomodels.net/model-qualifiers/",
    "http://purl.org/dc/terms/",
    "http://purl.org/dc/elements/1.1/",
)

HEADERS = {
    "Annotated Elements": [
        "No.", "Model", "Element type", "Element ID", "Element name",
        "Compartment", "Qualifier", "Annotation IDs", "Annotation URLs",
        "Numerical property", "Numerical value", "Unit", "Kinetic rate law",
        "Rate-law parameters", "Reactants", "Products", "Modifiers", "SBO term",
        "Initial assignment", "Notes", "SBML source URL", "Model page URL",
    ],
    "Annotation Links": [
        "Model", "Element type", "Element ID", "Qualifier", "Database",
        "Database ID", "Annotation URL", "SBML source URL",
    ],
    "Reaction Kinetics": [
        "Model", "Reaction ID", "Reaction name", "Is directly RDF annotated",
        "Reaction annotations", "Reactants", "Products", "Modifiers",
        "Kinetic formula", "Rate-law parameters", "Kinetic MathML", "SBML source URL",
    ],
    "Parameters": [
        "Model", "Scope", "Reaction ID", "Parameter ID", "Value", "Units",
        "Is directly RDF annotated", "Qualifiers", "Annotation IDs", "SBML source URL",
    ],
    "Model References": [
        "Model", "Qualifier", "Database", "Database ID", "URL", "SBML source URL",
    ],
    "Model Inventory": [
        "Model", "Organism", "Tissue", "Process", "Model type", "Download status",
        "Directly annotated elements", "Annotated species", "Annotated reactions",
        "Total reactions", "Total parameters", "Direct RDF links", "SBML SHA256",
        "Error", "SBML source URL", "Model page URL",
    ],
}
