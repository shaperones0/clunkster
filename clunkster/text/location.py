"""Source navigation model."""

import bisect
from dataclasses import dataclass
from typing import Self
from pathlib import Path
import itertools as it


@dataclass(frozen=True, slots=True)
class Location:
    """Source location pointer."""

    file: Path
    loc_line: int
    loc_column: int
    loc_index: int
