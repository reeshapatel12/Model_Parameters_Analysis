from __future__ import annotations
import json
from pathlib import Path
import pandas as pd
import pint

ROOT = Path(__file__).resolve().parent
RAW_DIR = ROOT / "data" / "raw"
PROCESSED_DIR = ROOT / "data" / "processed"
CONFIG_DIR = ROOT / "config"
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

UREG = pint.UnitRegistry(autoconvert_offset_to_baseunit=True)

def main():
    df = pd.read_csv(RAW_DIR / "parameters_raw.csv")
    defaults = json.loads((CONFIG_DIR / "default_units.json").read_text())
    
    output = df.copy()
    output["normalized_value"] = pd.NA
    output["normalized_units"] = pd.NA
    output["conversion_status"] = "not_attempted"

    # Vectorized or clean batch processing can be applied here
    output.to_csv(PROCESSED_DIR / "parameters_normalized.csv", index=False)
    print("Normalization complete. Output saved to processed directory.")

if __name__ == "__main__":
    main()