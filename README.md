# Model Parameters Analysis
What statistical distributions characterize the numerical parameters used in published mechanistic models, and how do those distributions depend on parameter type and biological context?

## Extraction and unit statistics

`extract_params.py` extracts only curated BioModels records (`BIOMD…` identifiers) and marks each row with `curated=true`. It records model time units, compartment sizes, and species initial amounts/concentrations as distinct `record_type` values, alongside global and kinetic parameters.

The extractor processes the full curated set:

```sh
python extract_params.py
```

Run `python analyze_units.py` after extraction to generate `data/statistics/unit_frequency.csv` and `unit_summary.json`. Frequencies are grouped by record type, and `config/default_units.json` contains the most common parseable unit for each dimension.

The analysis also refreshes `data/statistics/failed_models.csv`. A model is marked `non_normalizable_units` when a declared unit cannot be parsed, when a time unit is not a time dimension, when a compartment size unit is not a spatial dimension (including dimensionless or unresolved `volume`), or when a species unit is not a substance, mass, or dimensionless unit. The raw unit values and unit-frequency counts are retained for review; only role-compatible, parseable units contribute to default-unit selection.

Each parameter row includes the selected model context needed for analysis: `model_id`, `model_name`, organism, authors, publication ID and title, cell type, tissue, disease, pathway, modeling approach, model type, and format. Rows share the stable `model_id` key; `data/raw/models_metadata.csv` stores the broader set of identifiable named metadata fields, including journal, year, description, and submitter. It does not store the full API JSON response.
