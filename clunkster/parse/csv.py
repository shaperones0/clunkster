"""Parse CSV-like metadata files into dataclasses."""

import collections.abc as col
import csv
from typing import Any, get_type_hints


def apply_hints(row: dict[str, Any], hints: dict[str, Any]) -> None:
    """Apply type hints to a dict."""
    for field_name, field_type in hints.items():
        if field_name not in row:
            raise ValueError(f'Missing field: {field_name}')

        value = row[field_name]

        if field_type is int:
            row[field_name] = int(value)
        elif field_type is float:
            row[field_name] = float(value)
        elif field_type is str:
            row[field_name] = value
        else:
            raise TypeError(
                f'Unsupported type {field_type!r} for field {field_name}'
            )


def parse[T](cls: type[T], lines: col.Iterable[str]) -> col.Iterable[T]:
    """Parse lines into collection of dataclasses."""
    hints = get_type_hints(cls)

    for row in csv.DictReader(lines, list(hints.keys())):
        apply_hints(row, hints)
        yield cls(**row)
