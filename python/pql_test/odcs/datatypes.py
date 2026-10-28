# SPDX-License-Identifier: AGPL-3.0-only
"""ODCS types and semantic model data types.

Model type names are the ones ``INFO.VIEW.COLUMNS()[DataType]`` reports, which
the catalog's ``tbl.column_type`` check compares (case-insensitively). They were
read from the deployed SampleModel on 2026-10-28; TMDL stores the same types under
the names in ``TMDL_TYPES``.
"""

from __future__ import annotations

TEXT, INTEGER, NUMBER, CURRENCY, DATE, BOOLEAN, BINARY = (
    "Text",
    "Integer",
    "Number",
    "Currency",
    "Date",
    "True/False",
    "Binary",
)
MODEL_TYPES = (TEXT, INTEGER, NUMBER, CURRENCY, DATE, BOOLEAN, BINARY)

# TMDL `dataType:` value -> model type name.
TMDL_TYPES = {
    "string": TEXT,
    "int64": INTEGER,
    "double": NUMBER,
    "decimal": CURRENCY,
    "datetime": DATE,
    "boolean": BOOLEAN,
    "binary": BINARY,
}

ONE_DATE_TYPE = "the model has one date/time type (Date), so a date-only column also passes"

# ODCS logicalType -> (model types that satisfy it, approximation reason or None).
LOGICAL_TYPES: dict[str, tuple[tuple[str, ...], str | None]] = {
    "string": ((TEXT,), None),
    "integer": ((INTEGER,), None),
    "number": ((NUMBER, CURRENCY), None),  # decimal or fixed decimal; pin one with pbiDataType
    "boolean": ((BOOLEAN,), None),
    "date": ((DATE,), None),
    "timestamp": ((DATE,), ONE_DATE_TYPE),
    "time": ((DATE,), ONE_DATE_TYPE),
}


def model_type(name: object) -> str | None:
    """The canonical model type name for *name* (any case), or None when it is not one."""
    wanted = str(name).strip().lower()
    return next((t for t in MODEL_TYPES if t.lower() == wanted), None)


def tmdl_model_type(tmdl_data_type: str) -> str | None:
    """The model type name for a TMDL ``dataType`` value, or None when unknown."""
    return TMDL_TYPES.get(tmdl_data_type.strip().lower())
