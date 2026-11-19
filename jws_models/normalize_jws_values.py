"""Normalize JWS numerical values to the modal unit for each dimension."""
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from unit_normalization.common import choose_modal_units, normalize_frame, write_choices

DATA = ROOT / "data" / "jws"


def main():
    parameter_path = DATA / "parameters.csv"
    parameters = pd.read_csv(parameter_path, low_memory=False)
    targets = choose_modal_units([(parameters, "Value", "Units")])
    normalized_parameters = DATA / "parameters_normalized.csv"
    normalize_frame(parameters, "Value", "Units", targets).to_csv(normalized_parameters, index=False)
    write_choices(DATA / "modal_units.csv", targets)

    annotated_path = DATA / "annotated_elements.csv"
    normalized_annotated = DATA / "annotated_elements_normalized.csv"
    if annotated_path.exists():
        annotated = pd.read_csv(annotated_path, low_memory=False)
        normalize_frame(annotated, "Numerical value", "Unit", targets).to_csv(normalized_annotated, index=False)
    print(f"Normalized {len(parameters)} JWS parameter records; modal units: {len(targets)} dimensions")


if __name__ == "__main__":
    main()
