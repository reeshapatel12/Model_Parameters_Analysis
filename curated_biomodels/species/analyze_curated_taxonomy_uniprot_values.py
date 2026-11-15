"""Find the most frequent model-taxonomy/species-UniProt pair and its values."""
from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data" / "curated" / "annotations"
SPECIES_INPUT = DATA_DIR / "species_raw.csv"
MODEL_INPUT = DATA_DIR / "curated_biomodel_annotations.csv"
OUTPUT = DATA_DIR / "top_taxonomy_uniprot_value_distribution.csv"


def main() -> None:
    species = pd.read_csv(SPECIES_INPUT, keep_default_na=False)
    models = pd.read_csv(MODEL_INPUT, keep_default_na=False)
    taxonomy_by_model = {
        row.biomodel_id: {term.strip() for term in row.taxonomy.split(";") if term.strip()}
        for row in models.itertuples()
    }

    pair_counts: Counter[tuple[str, str]] = Counter()
    pair_values: dict[tuple[str, str], list[tuple[float, str]]] = defaultdict(list)
    pair_models: dict[tuple[str, str], set[str]] = defaultdict(set)
    for row in species.itertuples():
        taxonomies = taxonomy_by_model.get(row.Biomodel_id, set())
        uniprots = {
            term.split("/", 1)[1]
            for term in row.species_annotations.split(";")
            if term.lower().startswith("uniprot/")
        }
        for taxonomy in taxonomies:
            for uniprot in uniprots:
                pair = (taxonomy, uniprot)
                pair_counts[pair] += 1
                pair_models[pair].add(row.Biomodel_id)
                try:
                    pair_values[pair].append((float(row.initial_value), row.units))
                except (TypeError, ValueError):
                    pass

    if not pair_counts:
        raise ValueError("No model taxonomy and species UniProt combinations were found")

    (taxonomy, uniprot), combination_count = pair_counts.most_common(1)[0]
    values = Counter(value for value, _ in pair_values[(taxonomy, uniprot)])
    units = Counter(unit or "no data" for _, unit in pair_values[(taxonomy, uniprot)])
    output = pd.DataFrame([
        {
            "taxonomy": taxonomy,
            "uniprot": uniprot,
            "combination_species_count": combination_count,
            "model_count": len(pair_models[(taxonomy, uniprot)]),
            "initial_value": value,
            "species_count": count,
            "units": "; ".join(f"{unit} ({n})" for unit, n in units.most_common()),
        }
        for value, count in sorted(values.items())
    ])
    output.to_csv(OUTPUT, index=False)
    print(f"Most frequent pair: taxonomy {taxonomy} + UniProt {uniprot} ({combination_count} species across {len(pair_models[(taxonomy, uniprot)])} models)")
    print(f"Value distribution: {dict(sorted(values.items()))}")
    print(f"Units: {dict(units)}")
    print(f"Wrote {OUTPUT}")


if __name__ == "__main__":
    main()
