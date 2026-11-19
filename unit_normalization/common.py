"""Shared modal-unit selection and conversion helpers for model databases."""
from __future__ import annotations

from collections import Counter
from pathlib import Path
import math

import pandas as pd
import pint

UREG = pint.UnitRegistry(autoconvert_offset_to_baseunit=True)
try:
    UREG.define("substance = mole")
except (pint.errors.DefinitionSyntaxError, pint.errors.RedefinitionError):
    pass


def parse_units(value):
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    if not text or text.lower() in {"not explicitly declared", "unknown", "none", "nan"}:
        return None
    text = text.replace("^", "**")
    try:
        return UREG.parse_units(text)
    except (pint.errors.UndefinedUnitError, pint.errors.DefinitionSyntaxError,
            pint.errors.OffsetUnitCalculusError, ValueError, TypeError):
        return None


def _numeric(value):
    if value is None or pd.isna(value) or str(value).strip() == "":
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def choose_modal_units(frames: list[tuple[pd.DataFrame, str, str]]):
    """Pick the most frequent declared unit separately for each dimensionality."""
    counts: dict[str, Counter] = {}
    dimensions = {}
    for frame, value_column, unit_column in frames:
        if value_column not in frame or unit_column not in frame:
            continue
        for value, unit_text in zip(frame[value_column], frame[unit_column]):
            if _numeric(value) is None:
                continue
            unit = parse_units(unit_text)
            if unit is None:
                continue
            dimension = str(unit.dimensionality)
            text = str(unit_text).strip()
            counts.setdefault(dimension, Counter())[text] += 1
            dimensions[(dimension, text)] = unit
    targets = {}
    for dimension, counter in counts.items():
        # Stable lexical tie-break makes repeated runs deterministic.
        best = min(counter, key=lambda text: (-counter[text], text))
        targets[dimension] = {"unit_text": best, "unit": dimensions[(dimension, best)],
                             "observations": counter[best]}
    return targets


def normalize_frame(frame: pd.DataFrame, value_column: str, unit_column: str, targets: dict):
    """Add normalized_value, normalized_units, conversion_status to a data frame."""
    normalized_values, normalized_units, statuses = [], [], []
    if value_column not in frame.columns or unit_column not in frame.columns:
        raise KeyError(f"Expected value/unit columns {value_column!r}, {unit_column!r}")
    for value, unit_text in zip(frame[value_column], frame[unit_column]):
        number = _numeric(value)
        if number is None:
            normalized_values.append(pd.NA)
            normalized_units.append(pd.NA)
            statuses.append("no numeric value")
            continue
        source = parse_units(unit_text)
        if source is None:
            normalized_values.append(pd.NA)
            normalized_units.append(pd.NA)
            statuses.append("unit missing or unrecognized")
            continue
        dimension = str(source.dimensionality)
        target = targets.get(dimension)
        if target is None:
            normalized_values.append(pd.NA)
            normalized_units.append(pd.NA)
            statuses.append("no modal unit for dimensionality")
            continue
        try:
            converted = (number * source).to(target["unit"])
        except (pint.errors.DimensionalityError, pint.errors.OffsetUnitCalculusError,
                ValueError, TypeError):
            normalized_values.append(pd.NA)
            normalized_units.append(pd.NA)
            statuses.append("conversion failed")
            continue
        normalized_values.append(float(converted.magnitude))
        normalized_units.append(target["unit_text"])
        statuses.append("already modal unit" if str(unit_text).strip() == target["unit_text"] else "converted")
    frame["normalized_value"] = normalized_values
    frame["normalized_units"] = normalized_units
    frame["conversion_status"] = statuses
    return frame


def write_choices(path: Path, targets: dict):
    rows = [{"dimensionality": dim, "most_common_unit": item["unit_text"],
             "count": item["observations"]} for dim, item in sorted(targets.items())]
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=["dimensionality", "most_common_unit", "count"]).to_csv(path, index=False)
