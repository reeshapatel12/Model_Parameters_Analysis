# Model Parameters Analysis
What statistical distributions characterize the numerical parameters used in published mechanistic models, and how do those distributions depend on parameter type and biological context?

## Script layout

Pipeline scripts are grouped by source: `curated_biomodels/`, `uncurated_biomodels/`, `cellml_models/` (Physiome), and `vcell_models/`. Curated BioModels species scripts are in `curated_biomodels/species/`; model annotation scripts are in `curated_biomodels/annotations/`. Run commands from the project root as shown below.

## Extraction and unit statistics

`curated_biomodels/extract_params.py` extracts only curated BioModels records (`BIOMD…` identifiers) and marks each row with `curated=true`. It records model time units, compartment sizes, and species initial amounts/concentrations as distinct `record_type` values, alongside global and kinetic parameters. Curated pipeline files are isolated under `data/curated/`: raw tables in `raw/`, reports in `statistics/`, normalized parameters in `processed/`, and unit defaults in `config/`.

The extractor processes the full curated set:

```sh
python curated_biomodels/extract_params.py
```

## Curated BioModels ontology annotations

`curated_biomodels/annotations/extract_curated_biomodel_annotations.py` creates a model-level table for curated `BIOMD…` records only. It reads the model-level SBML annotations and writes the available GO, taxonomy, and MAMO identifiers (including `GO:0007173`, `10116`, or `MAMO_0000046` when present) to `data/curated/annotations/curated_biomodel_annotations.csv`. Multiple identifiers in a category are separated by semicolons; an empty field means no identifier was found for that category. Annotation extraction and summary outputs are kept under `data/curated/annotations/`.

Run `curated_biomodels/annotations/analyze_curated_biomodel_annotations.py` after extraction to count each observed identifier by category and include a `no term` count for each category. It writes `data/curated/annotations/curated_biomodel_annotation_statistics.csv`.

## Curated BioModels species

`curated_biomodels/species/extract_curated_species.py` creates a species-level table from curated `BIOMD…` models only at `data/curated/annotations/species_raw.csv`. It includes model and species identifiers, organism, text from each species `<notes>` block, species annotations (semicolon-separated when multiple identifiers exist), the SBML initial amount or concentration, and units. `curated_biomodels/species/analyze_curated_species_annotations.py` counts each annotation identifier by namespace and adds a `no data` count for species with no identifier in that namespace; it writes `data/curated/annotations/species_annotation_statistics.csv`. `curated_biomodels/species/process_curated_species.py` parses units, selects the most frequent exact unit string among units dimensionally equivalent to moles, and converts those species values to that unit. Non-mole, missing, and unparseable units remain visible with a conversion status. Output is `data/curated/annotations/species_processed.csv`. `curated_biomodels/species/analyze_curated_taxonomy_uniprot_values.py` writes the value distribution for the most frequent taxonomy–UniProt combination.

```sh
python curated_biomodels/species/extract_curated_species.py
python curated_biomodels/species/analyze_curated_species_annotations.py
python curated_biomodels/species/process_curated_species.py
python curated_biomodels/species/analyze_curated_taxonomy_uniprot_values.py
```

```sh
python curated_biomodels/annotations/extract_curated_biomodel_annotations.py
python curated_biomodels/annotations/analyze_curated_biomodel_annotations.py
```

Run `python curated_biomodels/analyze_units.py` after extraction to generate `data/curated/statistics/unit_frequency.csv` and `unit_summary.json`. Frequencies are grouped by record type, and `data/curated/config/default_units.json` contains the most common parseable unit for each dimension.

The analysis also refreshes `data/curated/statistics/failed_models.csv`. A model is marked `non_normalizable_units` when a declared unit cannot be parsed, when a time unit is not a time dimension, when a compartment size unit is not a spatial dimension (including dimensionless or unresolved `volume`), or when a species unit is not a substance, mass, or dimensionless unit. The raw unit values and unit-frequency counts are retained for review; only role-compatible, parseable units contribute to default-unit selection.

Each parameter row includes the selected model context needed for analysis: `model_id`, `model_name`, organism, authors, publication ID and title, cell type, tissue, disease, pathway, modeling approach, model type, and format. Rows share the stable `model_id` key; `data/curated/raw/models_metadata.csv` stores the broader set of identifiable named metadata fields, including journal, year, description, and submitter. It does not store the full API JSON response.

## Uncurated and automatically generated BioModels

The separate scripts in `uncurated_biomodels/` apply the same extraction, unit review, and normalized-output steps to BioModels' uncurated submissions (`MODEL…`) and Path2Models autogenerated records (`BMID…` or records tagged as autogenerated). They write only under `data/uncurated/`, keeping this dataset separate from the curated pipeline while using the same `model_id` and parameter-column conventions.

Run the steps in order:

```sh
python uncurated_biomodels/extract_uncurated_params.py
python uncurated_biomodels/analyze_uncurated_units.py
python uncurated_biomodels/normalize_uncurated_params.py
```

## VCell models

The separate VCell pipeline selects public models referenced by publication records with data, educational models, and models owned by `CMC`, `CompCell`, or `ModelBrick`. It downloads each model's SBML and extracts the same time, compartment, species, global parameter, and kinetic parameter records as the BioModels pipelines. A model selected through more than one collection is extracted once; `model_collection` records all matching sources. `curated` is left blank because VCell does not provide the BioModels curation flag.

Run the steps in order:

```sh
python vcell_models/extract_vcell_params.py
python vcell_models/analyze_vcell_units.py
python vcell_models/normalize_vcell_params.py
```

VCell outputs are isolated under `data/vcell/`: raw parameter and model metadata tables, unit statistics and failed model records under `statistics/`, defaults under `config/`, and normalized parameters under `processed/`. The parameter table contains publication context when the publication endpoint links that model to a publication; broader identifiable fields are kept in `models_metadata.csv`. The extractor detects repeated API pages to avoid looping if the endpoint ignores its `startRow` pagination parameter.

## Physiome Model Repository

The separate Physiome pipeline reads the repository's processed model exposure list, FieldML collection, and musculoskeletal scaffold collection. It parses variables, initial values, and unit definitions from CellML files in each linked workspace archive. CellML does not use SBML's compartment and species elements, so records use `cellml_variable` and `time_unit` types. Entries without CellML files remain in the model metadata table and are recorded as unavailable for this CellML parameter extraction.

Run the steps in order:

```sh
python cellml_models/extract_physiome_params.py
python cellml_models/analyze_physiome_units.py
python cellml_models/normalize_physiome_params.py
```

Outputs are isolated under `data/physiome/`. The extractor resumes model IDs already saved in `models_metadata.csv`; use `python cellml_models/extract_physiome_params.py --restart` to replace the previous extraction.
