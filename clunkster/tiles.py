"""Room tile layers."""

import collections.abc as col
import dataclasses
from dataclasses import dataclass


def format_number(value: float) -> str:
    """Format a number the way room files store it (no ``.0`` on integers)."""
    if value == int(value):
        return str(int(value))
    return repr(value)


def _clean(value: float) -> float:
    """Remove float error from values meant to be whole (like 0.8 * 5)."""
    rounded = round(value)
    return float(rounded) if abs(value - rounded) < 1e-6 else value


@dataclass(frozen=True, slots=True)
class Tile:
    """Room tile, as stored in a tile layer file.

    Draws region ``left, top, width, height`` of background ``bg`` at
    ``x, y``, scaled by ``xscale, yscale`` (negative scales mirror).
    """

    bg: str
    x: float
    y: float
    left: int
    top: int
    width: int
    height: int
    # meaning unknown, kept as is
    flag: str
    xscale: float
    yscale: float
    # alpha in the highest byte, blend color (BGR) below
    color: int

    @property
    def alpha(self) -> float:
        """Tile's alpha (0-1)."""
        return (self.color >> 24) / 255

    @property
    def blend(self) -> int:
        """Tile's blend color (BGR)."""
        return self.color & 0xFFFFFF

    def region(self) -> tuple[int, int, int, int]:
        """Background region: left, top, width, height."""
        return self.left, self.top, self.width, self.height

    def bounds(self) -> tuple[float, float, float, float]:
        """Drawn area in the room: left, top, right, bottom."""
        x2 = self.x + self.width * self.xscale
        y2 = self.y + self.height * self.yscale
        return (
            min(self.x, x2),
            min(self.y, y2),
            max(self.x, x2),
            max(self.y, y2),
        )

    def contains(self, px: float, py: float) -> bool:
        """Check whether a point lies within the drawn area.

        Edges count as inside, so this errs on the side of a match.
        """
        left, top, right, bottom = self.bounds()
        return left <= px <= right and top <= py <= bottom

    def sub(self, dx: int, dy: int, width: int, height: int) -> Tile:
        """Get a tile drawing a part of this tile's region at the same place.

        :param dx: Part's offset from the region's left.
        :param dy: Part's offset from the region's top.
        :param width: Part's width.
        :param height: Part's height.
        """
        return dataclasses.replace(
            self,
            x=_clean(self.x + dx * self.xscale),
            y=_clean(self.y + dy * self.yscale),
            left=self.left + dx,
            top=self.top + dy,
            width=width,
            height=height,
        )

    def format(self) -> str:
        """Format as a tile layer line."""
        return ','.join((
            self.bg,
            format_number(self.x),
            format_number(self.y),
            str(self.left),
            str(self.top),
            str(self.width),
            str(self.height),
            self.flag,
            format_number(self.xscale),
            format_number(self.yscale),
            str(self.color),
        ))


def parse_line(line: str) -> Tile:
    """Parse a tile layer line."""
    fields = line.split(',')
    if len(fields) != 11:
        raise ValueError(f'Malformed tile line: {line!r}')
    return Tile(
        bg=fields[0],
        x=float(fields[1]),
        y=float(fields[2]),
        left=int(fields[3]),
        top=int(fields[4]),
        width=int(fields[5]),
        height=int(fields[6]),
        flag=fields[7],
        xscale=float(fields[8]),
        yscale=float(fields[9]),
        color=int(fields[10]),
    )


def parse_layer(text: str) -> list[Tile]:
    """Parse a tile layer file, in drawing order."""
    return [parse_line(line) for line in text.splitlines() if line]


def format_layer(tiles: col.Iterable[Tile]) -> str:
    """Format tiles as a tile layer file."""
    return ''.join(f'{tile.format()}\n' for tile in tiles)
