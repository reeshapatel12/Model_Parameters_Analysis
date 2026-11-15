"""Count model-level GO, taxonomy, and MAMO annotations in the curated table."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data" / "curated"
INPUT = DATA_DIR / "annotations" / "curated_biomodel_annotations.csv"
OUTPUT = DATA_DIR / "annotations" / "curated_biomodel_annotation_statistics.csv"
TERM_COLUMNS = ("go", "taxonomy", "mamo")


def main() -> None:
    if not INPUT.exists():
        raise FileNotFoundError(f"Run extract_curated_biomodel_annotations.py first: {INPUT}")
    models = pd.read_csv(INPUT, keep_default_na=False)
    rows = []
    for column in TERM_COLUMNS:
        term_counts: dict[str, int] = {}
        no_term = 0
        for value in models[column]:
            terms = {term.strip() for term in str(value).split(";") if term.strip()}
            if not terms:
                no_term += 1
            for term in terms:
                term_counts[term] = term_counts.get(term, 0) + 1
        rows.extend({"category": column, "term": term, "model_count": count}
                    for term, count in sorted(term_counts.items()))
        rows.append({"category": column, "term": "no term", "model_count": no_term})
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=["category", "term", "model_count"]).to_csv(OUTPUT, index=False)


if __name__ == "__main__":
    main()
