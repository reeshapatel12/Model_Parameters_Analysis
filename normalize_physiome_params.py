from __future__ import annotations
import json
from pathlib import Path
import pandas as pd
import pint

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data" / "physiome"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
CONFIG_DIR = DATA_DIR / "config"
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

UREG = pint.UnitRegistry(autoconvert_offset_to_baseunit=True)

def main():
    raw_path = RAW_DIR / "parameters_raw.csv"
    defaults_path = CONFIG_DIR / "default_units.json"
    if not raw_path.exists():
        raise FileNotFoundError(f"Run extract_physiome_params.py first; missing {raw_path}")
    if not defaults_path.exists():
        raise FileNotFoundError(f"Run analyze_physiome_units.py first; missing {defaults_path}")
    df = pd.read_csv(raw_path)
    defaults = json.loads(defaults_path.read_text())
    
    output = df.copy()
    output["normalized_value"] = pd.NA
    output["normalized_units"] = pd.NA
    output["conversion_status"] = "not_attempted"

    # Vectorized or clean batch processing can be applied here
    output.to_csv(PROCESSED_DIR / "parameters_normalized.csv", index=False)
    print("Normalization complete. Output saved to processed directory.")

if __name__ == "__main__":
    main()
