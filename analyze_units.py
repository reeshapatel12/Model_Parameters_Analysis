from __future__ import annotations
import json
from collections import Counter, defaultdict
from pathlib import Path
import pandas as pd
import pint

ROOT = Path(__file__).resolve().parent
RAW_DIR = ROOT / "data" / "raw"
STATS_DIR = ROOT / "data" / "statistics"
CONFIG_DIR = ROOT / "config"
STATS_DIR.mkdir(parents=True, exist_ok=True)

UREG = pint.UnitRegistry(autoconvert_offset_to_baseunit=True)
UREG._biomodels_aliases = {
    "sec": "second", "secs": "second", "s": "second", "min": "minute",
    "hr": "hour", "h": "hour", "L": "liter", "M": "mole / liter",
    "mM": "millimole / liter", "uM": "micromole / liter", "1/s": "1 / second"
}

def pint_unit(unit_text: str):
    """Parse a unit string, applying common BioModels spellings first."""
    norm = str(unit_text).strip()
    norm = UREG._biomodels_aliases.get(norm, norm).replace("^", "**").replace("per ", "/")
    try: return UREG.parse_units(norm)
    except Exception: return None

def main():
    df = pd.read_csv(RAW_DIR / "parameters_raw.csv", low_memory=False)
    # Count raw strings first so unusual or unparseable units remain represented
    # in the report, even though only parsed units can contribute to dimensions.
    units = df["units"].dropna().astype(str).str.strip()
    counts = Counter(units[units.ne("")])
    
    by_dimension = defaultdict(Counter)
    for unit, count in counts.items():
        parsed = pint_unit(unit)
        if parsed is not None:
            by_dimension[str(parsed.dimensionality)][unit] += count

    # The most frequent observed unit per dimension is a reporting default; it
    # does not convert values or assert that this unit is biologically preferred.
    defaults = {dim: counter.most_common(1)[0][0] for dim, counter in by_dimension.items()}
    CONFIG_DIR.mkdir(exist_ok=True)
    (CONFIG_DIR / "default_units.json").write_text(json.dumps(defaults, indent=2, ensure_ascii=False))

    # Group frequencies by record_type so model time, compartment size, species,
    # and parameter units can be compared without combining their populations.
    freq = (df.dropna(subset=["units"]).assign(units=lambda x: x["units"].astype(str).str.strip())
            .query("units != ''").groupby(["record_type", "units"], dropna=False)
            .size().rename("count").reset_index()
            .sort_values(["record_type", "count", "units"], ascending=[True, False, True]))
    freq.to_csv(STATS_DIR / "unit_frequency.csv", index=False)
    summary = {
        "total_records": int(len(df)),
        "records_with_explicit_units": int(df["units"].notna().sum()),
        "records_without_units": int(df["units"].isna().sum()),
        "distinct_unit_strings": int(units[units.ne("")].nunique()),
        "records_by_type": {str(k): int(v) for k, v in df["record_type"].value_counts(dropna=False).items()},
        "units_by_type": {},
        "default_unit_by_dimension": defaults,
    }
    for record_type, group in freq.groupby("record_type"):
        summary["units_by_type"][str(record_type)] = [
            {"unit": row[1], "count": int(row[2])} for row in group.head(20).itertuples(index=False, name=None)
        ]
    (STATS_DIR / "unit_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"Saved unit frequencies and summary for {len(defaults)} dimensions to {STATS_DIR}.")

if __name__ == "__main__":
    main()
