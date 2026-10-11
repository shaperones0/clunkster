"""GameMaker models (``d3d_model_*``)."""

import collections.abc as col
import zlib
from dataclasses import dataclass

# vertices per primitive, GameMaker splits larger ones anyway
MAX_PRIMITIVE_VERTICES = 31000

_PRIMITIVE_BEGIN = 0
_PRIMITIVE_END = 1
_VERTEX_TEXTURE_COLOR = 5
_TRIANGLE_LIST = 4


@dataclass(frozen=True, slots=True)
class Quad:
    """Textured rectangle."""

    x1: float
    y1: float
    x2: float
    y2: float
    u1: float
    v1: float
    u2: float
    v2: float
    # BGR
    color: int
    alpha: float


def _line(kind: int, *values: float) -> str:
    padded = (*values, *(0.0,) * (10 - len(values)))
    return ' '.join((str(kind), *(f'{value:.4f}' for value in padded)))


def model_text(quads: col.Sequence[Quad]) -> str:
    """Format quads as a GameMaker model (``d3d_model_save`` format).

    Every quad is two triangles of a triangle list, in the given order.
    """
    lines: list[str] = []
    vertices = 0
    for quad in quads:
        if vertices == 0:
            lines.append(_line(_PRIMITIVE_BEGIN, _TRIANGLE_LIST))
        corners = (
            (quad.x1, quad.y1, quad.u1, quad.v1),
            (quad.x2, quad.y1, quad.u2, quad.v1),
            (quad.x1, quad.y2, quad.u1, quad.v2),
            (quad.x1, quad.y2, quad.u1, quad.v2),
            (quad.x2, quad.y1, quad.u2, quad.v1),
            (quad.x2, quad.y2, quad.u2, quad.v2),
        )
        lines.extend(
            _line(_VERTEX_TEXTURE_COLOR, x, y, 0, u, v, quad.color, quad.alpha)
            for x, y, u, v in corners
        )
        vertices += 6
        if vertices + 6 > MAX_PRIMITIVE_VERTICES:
            lines.append(_line(_PRIMITIVE_END))
            vertices = 0
    if vertices:
        lines.append(_line(_PRIMITIVE_END))
    return '\r\n'.join(('100', str(len(lines)), *lines, ''))


def model_g3z(quads: col.Sequence[Quad]) -> bytes:
    """Format quads as a compressed model (``.g3z``)."""
    return zlib.compress(model_text(quads).encode('ascii'), 9)
