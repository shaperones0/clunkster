"""Source navigation model."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Location:
    """Source location pointer."""

    file: Path
    loc_line: int
    loc_column: int
    loc_index: int
