"""Normalize Physiome CellML values to the modal unit for each dimension."""
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from unit_normalization.common import choose_modal_units, normalize_frame, write_choices

DATA = ROOT / "data" / "physiome"


def main():
    raw_path = DATA / "raw" / "parameters_raw.csv"
    if not raw_path.exists():
        raise FileNotFoundError(f"Run extract_physiome_params.py first; missing {raw_path}")
    raw = pd.read_csv(raw_path, low_memory=False)
    targets = choose_modal_units([(raw, "value", "units")])
    output = normalize_frame(raw.copy(), "value", "units", targets)
    output_path = DATA / "processed" / "parameters_normalized.csv"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(output_path, index=False)
    write_choices(DATA / "statistics" / "modal_units.csv", targets)

    details = ROOT / "data" / "detailed_cellml"
    for filename, value_column, unit_column in [
        ("cellml_annotations_values.csv", "Numerical value", "CellML units"),
        ("cellml_quantified_elements.csv", "Numerical value", "CellML units"),
    ]:
        source = details / filename
        if source.exists():
            frame = pd.read_csv(source, low_memory=False)
            normalize_frame(frame, value_column, unit_column, targets).to_csv(
                details / f"{source.stem}_normalized.csv", index=False)
    print(f"Normalized {len(output)} Physiome records; modal units: {len(targets)} dimensions")


if __name__ == "__main__":
    main()
