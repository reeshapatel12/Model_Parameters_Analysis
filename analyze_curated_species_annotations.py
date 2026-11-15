"""Count species-level annotation identifiers in curated BioModels data."""
from __future__ import annotations

from collections import Counter
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data" / "curated" / "annotations"
INPUT = DATA_DIR / "species_raw.csv"
OUTPUT = DATA_DIR / "species_annotation_statistics.csv"


def split_annotation(value: str) -> tuple[str, str] | None:
    value = value.strip()
    if not value:
        return None
    if value.upper().startswith("CHEBI:"):
        return "chebi", value.upper()
    if "/" in value:
        namespace, identifier = value.split("/", 1)
        return namespace.lower(), identifier
    return "other", value


def main() -> None:
    if not INPUT.exists():
        raise FileNotFoundError(f"Run extract_curated_species.py first: {INPUT}")
    species = pd.read_csv(INPUT, keep_default_na=False)
    per_species = []
    for value in species.get("species_annotations", pd.Series(dtype=str)):
        per_species.append({item for token in str(value).split(";")
                            if (item := split_annotation(token))})
    namespaces = sorted({namespace for annotations in per_species
                         for namespace, _ in annotations})
    counts: dict[str, Counter[str]] = {namespace: Counter() for namespace in namespaces}
    missing: Counter[str] = Counter()
    for annotations in per_species:
        present = {namespace for namespace, _ in annotations}
        for namespace, identifier in annotations:
            counts[namespace][identifier] += 1
        for namespace in namespaces:
            if namespace not in present:
                missing[namespace] += 1

    rows = []
    for namespace in sorted(counts):
        rows.append({"namespace": namespace, "annotation": "no data",
                     "species_count": missing[namespace]})
        rows.extend({"namespace": namespace, "annotation": identifier, "species_count": count}
                    for identifier, count in sorted(counts[namespace].items()))
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=["namespace", "annotation", "species_count"]).to_csv(OUTPUT, index=False)
    print(f"Wrote annotation counts for {len(counts)} namespaces to {OUTPUT}")


if __name__ == "__main__":
    main()
