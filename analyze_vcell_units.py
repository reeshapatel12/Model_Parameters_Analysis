from __future__ import annotations
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
import pandas as pd
import pint

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data" / "vcell"
RAW_DIR = DATA_DIR / "raw"
STATS_DIR = DATA_DIR / "statistics"
CONFIG_DIR = DATA_DIR / "config"
STATS_DIR.mkdir(parents=True, exist_ok=True)

UREG = pint.UnitRegistry(autoconvert_offset_to_baseunit=True)
# SBML uses ``item`` as a count-of-entities unit. Register it under its own
# name so Pint can parse it without rewriting the label to ``count``.
UREG.define("item = []")
UREG._biomodels_aliases = {
    "sec": "second", "secs": "second", "s": "second", "min": "minute",
    "hr": "hour", "h": "hour", "L": "liter", "M": "mole / liter",
    "mM": "millimole / liter", "uM": "micromole / liter", "1/s": "1 / second",
    # Avogadro's constant is a dimensionless scaling unit in SBML.
    "avogadro": "dimensionless",
}

def pint_unit(unit_text: str):
    """Parse a unit string, applying common BioModels spellings first."""
    norm = str(unit_text).strip()
    norm = UREG._biomodels_aliases.get(norm, norm)
    norm = norm.replace("^", "**").replace("per ", "/")
    norm = re.sub(r"unit_kind_([a-zA-Z_]+)", r"\1", norm)
    norm = re.sub(r"\bavogadro\b", "dimensionless", norm)
    # SBML-rendered definitions include numeric scales (for example
    # ``0.001*mole``), so parse as an expression rather than a unit-only string.
    try: return UREG.parse_expression(norm)
    except Exception: return None

def unit_failure(record_type: str, unit_text: str) -> str | None:
    """Return why a declared unit is unusable or semantically wrong here."""
    parsed = pint_unit(unit_text)
    if parsed is None:
        return "unparseable_unit"

    dimension = str(parsed.dimensionality)
    if record_type == "time_unit" and dimension != "[time]":
        return "time_unit_not_time_dimension"
    if record_type == "compartment_size":
        # A compartment size must describe a spatial extent. A bare name such
        # as 'volume' is rejected by pint_unit unless its SBML definition was
        # resolved; dimensionless and non-spatial dimensions are not meaningful.
        if dimension not in {"[length]", "[length] ** 2", "[length] ** 3"}:
            return "compartment_unit_not_spatial_dimension"
    if record_type == "species" and dimension not in {"[substance]", "[mass]", "dimensionless"}:
        return "species_unit_not_substance_dimension"
    return None

def write_failed_models(df: pd.DataFrame) -> int:
    """Preserve earlier parse failures and add models with invalid declared units."""
    path = STATS_DIR / "failed_models.csv"
    existing: dict[str, dict[str, str]] = {}
    if path.exists():
        for row in csv.DictReader(path.open(newline="", encoding="utf-8")):
            model_id = (row.get("model_id") or "").strip()
            if model_id:
                # Recompute unit failures from the current raw file on each run,
                # while retaining unrelated earlier failure stages.
                stages = [stage for stage in (row.get("stage", "").split(";"))
                          if stage and stage != "non_normalizable_units"]
                if stages:
                    existing[model_id] = {
                        "model_id": model_id,
                        "stage": ";".join(stages),
                        "details": row.get("details", ""),
                    }

    issues: dict[str, set[str]] = defaultdict(set)
    for row in df.dropna(subset=["units"]).itertuples(index=False):
        unit_text = str(getattr(row, "units")).strip()
        if not unit_text:
            continue
        record_type = str(getattr(row, "record_type"))
        reason = unit_failure(record_type, unit_text)
        if reason:
            issues[str(getattr(row, "model_id"))].add(f"{record_type} [{unit_text}]: {reason}")

    for model_id, reasons in issues.items():
        old = existing.get(model_id, {"model_id": model_id, "stage": "", "details": ""})
        stages = set(filter(None, old.get("stage", "").split(";")))
        stages.add("non_normalizable_units")
        old["stage"] = ";".join(sorted(stages))
        old_details = set(filter(None, old.get("details", "").split("; ")))
        old_details.update(reasons)
        old["details"] = "; ".join(sorted(old_details))
        existing[model_id] = old

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["model_id", "stage", "details"])
        writer.writeheader()
        writer.writerows(existing[key] for key in sorted(existing))
    return len(issues)

def main():
    raw_path = RAW_DIR / "parameters_raw.csv"
    if not raw_path.exists():
        raise FileNotFoundError(f"Run extract_vcell_params.py first; missing {raw_path}")
    df = pd.read_csv(raw_path, low_memory=False)
    # Count raw strings first so unusual or unparseable units remain represented
    # in the report, even though only parsed units can contribute to dimensions.
    units = df["units"].dropna().astype(str).str.strip()
    counts = Counter(units[units.ne("")])
    
    # Exclude only rows that are invalid for their SBML role from dimensional
    # defaults. The raw unit-frequency report below deliberately retains all
    # declared strings, including units flagged for review.
    valid_unit_counts = Counter()
    for row in df.dropna(subset=["units"]).itertuples(index=False):
        unit = str(getattr(row, "units")).strip()
        if unit and unit_failure(str(getattr(row, "record_type")), unit) is None:
            valid_unit_counts[unit] += 1
    by_dimension = defaultdict(Counter)
    for unit, count in valid_unit_counts.items():
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
    failed_count = write_failed_models(df)
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
    print(f"Saved unit frequencies and summary for {len(defaults)} dimensions to {STATS_DIR}; "
          f"{failed_count} models have non-normalizable or role-incompatible units.")

if __name__ == "__main__":
    main()
