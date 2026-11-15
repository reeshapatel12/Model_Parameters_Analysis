"""Normalize curated species units to the most common mole unit."""
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
    # Select the most frequent original unit spelling among units dimensionally
    # equivalent to moles. Convert only these rows; preserve all others as-is.
    counts = species.loc[mole_rows, "units"].dropna().value_counts()
    target_unit = parse_unit(counts.index[0]) if not counts.empty else None
    target_text = str(counts.index[0]) if not counts.empty else None

    output = species.copy()
    output["normalized_value"] = pd.NA
    output["normalized_units"] = pd.NA
    output["conversion_status"] = "not_attempted"
    for index, unit in parsed.items():
        value = species.at[index, "initial_value"]
        if pd.isna(species.at[index, "units"]) or not str(species.at[index, "units"]).strip():
            output.at[index, "conversion_status"] = "missing_unit"
        elif unit is None:
            output.at[index, "conversion_status"] = "unparseable_unit"
        elif not mole_rows.at[index]:
            output.at[index, "conversion_status"] = "non_mole_unit"
        elif target_unit is None:
            output.at[index, "conversion_status"] = "no_mole_target_unit"
        elif pd.isna(value):
            output.at[index, "normalized_units"] = target_text
            output.at[index, "conversion_status"] = "missing_value"
        else:
            try:
                quantity = float(value) * unit
                output.at[index, "normalized_value"] = quantity.to(target_unit).magnitude
                output.at[index, "normalized_units"] = target_text
                output.at[index, "conversion_status"] = "converted"
            except (pint.errors.DimensionalityError, TypeError, ValueError):
                output.at[index, "conversion_status"] = "conversion_error"

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(OUTPUT, index=False)
    print(f"Normalized {int(mole_rows.sum())} mole-unit rows to {target_text or 'no available target unit'}; wrote {OUTPUT}")


if __name__ == "__main__":
    main()
