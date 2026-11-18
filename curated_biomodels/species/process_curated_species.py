"""Keep mole-dimension species and normalize their values to moles."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pint

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data" / "curated"
INPUT = DATA_DIR / "annotations" / "species_raw.csv"
OUTPUT = DATA_DIR / "annotations" / "species_processed.csv"
UREG = pint.UnitRegistry(autoconvert_offset_to_baseunit=True)


def parse_unit(value):
    if pd.isna(value) or not str(value).strip():
        return None
    try:
        # SBML unit definitions use "substance" for the mole base dimension;
        # Pint calls that unit "mole". Resolve the SBML spelling explicitly.
        normalized = str(value).strip()
        normalized = normalized.replace("[substance]", "mole")
        normalized = normalized.replace("substance", "mole")
        return UREG.parse_units(normalized)
    except (pint.errors.PintError, TypeError, ValueError):
        return None


def main() -> None:
    if not INPUT.exists():
        raise FileNotFoundError(f"Run extract_curated_species.py first: {INPUT}")
    species = pd.read_csv(INPUT)
    parsed = species["units"].map(parse_unit)
    mole_rows = parsed.map(lambda unit: unit is not None and unit.dimensionality == UREG.mole.dimensionality)
    # Exclude all non-mole, missing, and unparseable units from this processed
    # table. The normalized target is always the SI amount unit, mole.
    output = species.loc[mole_rows].copy()
    output["normalized_value"] = pd.NA
    output["normalized_units"] = "mole"
    output["conversion_status"] = "missing_value"
    for index, unit in parsed.loc[mole_rows].items():
        value = species.at[index, "initial_value"]
        if pd.isna(value):
            continue
        try:
            quantity = float(value) * unit
            output.at[index, "normalized_value"] = quantity.to(UREG.mole).magnitude
            output.at[index, "conversion_status"] = "converted"
        except (pint.errors.PintError, TypeError, ValueError):
            output.at[index, "conversion_status"] = "conversion_error"

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(OUTPUT, index=False)
    print(f"Kept {len(output)} mole-unit species and normalized to mole; wrote {OUTPUT}")


if __name__ == "__main__":
    main()
