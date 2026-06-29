"""Parse GameMaker 8.2 ``key=value`` metadata files."""

import collections.abc as col
from typing import Any, get_type_hints


def parse_pairs(lines: col.Iterable[str]) -> col.Iterator[tuple[str, str]]:
    """Parse ``key=value`` pairs from ``lines``.

    :param lines: Input lines.
    :return: Iterator of (key, value) pairs.
    """
    for line in lines:
        if not line.strip():
            # skip blank lines
            continue
        key, value = line.rstrip().split('=', 1)
        yield key, value


def parse_dataclass[T](cls: type[T], lines: col.Iterable[str]) -> T:
    """Parse ``key=value`` pairs from ``lines`` into given dataclass.

    Performs validation, only ``str`` and ``int`` fields are supported.
    :param cls: Dataclass class to parse into.
    :param lines: Input lines.
    :return: Validated dataclass from given lines.
    """
    raw: dict[str, str] = dict(parse_pairs(lines))

    hints = get_type_hints(cls)
    result: dict[str, Any] = {}

    unknown = raw.keys() - hints.keys()
    if unknown:
        raise ValueError(f'Unknown fields: {sorted(unknown)}')

    for field_name, field_type in hints.items():
        if field_name not in raw:
            raise ValueError(f'Missing field: {field_name}')

        value = raw[field_name]

        if field_type is int:
            result[field_name] = int(value)
        elif field_type is str:
            result[field_name] = value
        else:
            raise TypeError(
                f'Unsupported type {field_type!r} for field {field_name}'
            )

    return cls(**result)
