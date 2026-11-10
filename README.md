# Model Parameters Analysis
What statistical distributions characterize the numerical parameters used in published mechanistic models, and how do those distributions depend on parameter type and biological context?

## Extraction and unit statistics

`extract_params.py` extracts only curated BioModels records (`BIOMD…` identifiers) and marks each row with `curated=true`. It records model time units, compartment sizes, and species initial amounts/concentrations as distinct `record_type` values, alongside global and kinetic parameters.

The extractor processes the full curated set:

```sh
python extract_params.py
```

Run `python analyze_units.py` after extraction to generate `data/statistics/unit_frequency.csv` and `unit_summary.json`. Frequencies are grouped by record type, and `config/default_units.json` contains the most common parseable unit for each dimension.
