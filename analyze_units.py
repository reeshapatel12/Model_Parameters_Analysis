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
    norm = str(unit_text).strip()
    norm = UREG._biomodels_aliases.get(norm, norm).replace("^", "**").replace("per ", "/")
    try: return UREG.parse_units(norm)
    except Exception: return None

def main():
    df = pd.read_csv(RAW_DIR / "parameters_raw.csv", low_memory=False)
    units = df["units"].dropna().astype(str).str.strip()
    counts = Counter(units[units.ne("")])
    
    by_dimension = defaultdict(Counter)
    for unit, count in counts.items():
        parsed = pint_unit(unit)
        if parsed is not None:
            by_dimension[str(parsed.dimensionality)][unit] += count

    defaults = {dim: counter.most_common(1)[0][0] for dim, counter in by_dimension.items()}
    CONFIG_DIR.mkdir(exist_ok=True)
    (CONFIG_DIR / "default_units.json").write_text(json.dumps(defaults, indent=2, ensure_ascii=False))
    print(f"Saved default units for {len(defaults)} dimensions.")

if __name__ == "__main__":
    main()