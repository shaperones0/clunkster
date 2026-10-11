"""Unit tests for room tiles and models."""

import zlib

from clunkster import model, tiles

LINE = 'sprAmeTiles,96,416,0,32,32,32,0,1,1,4294967295'


def test_roundtrip() -> None:
    """Lines are written back exactly."""
    tile = tiles.parse_line(LINE)
    assert tile.format() == LINE
    assert tile.alpha == 1
    assert tile.blend == 0xFFFFFF
    assert tiles.format_layer(tiles.parse_layer(LINE + '\n\n')) == LINE + '\n'


def test_sub_keeps_pixels_in_place() -> None:
    """Parts of a scaled or mirrored tile stay where they were drawn."""
    tile = tiles.parse_line('bg,100,50,10,20,64,32,0,2,-1,4294967295')
    part = tile.sub(16, 8, 8, 8)
    # source pixel (26, 28) was drawn at 100 + 16*2, 50 - 8
    assert (part.x, part.y, part.left, part.top) == (132, 42, 26, 28)
    assert part.format() == 'bg,132,42,26,28,8,8,0,2,-1,4294967295'


def test_bounds_and_contains() -> None:
    """Mirrored tiles extend to the left."""
    tile = tiles.parse_line('bg,100,50,0,0,10,10,0,-1,1,4294967295')
    assert tile.bounds() == (90, 50, 100, 60)
    assert tile.contains(95, 55)
    assert not tile.contains(105, 55)


def test_model_format() -> None:
    """Models match GameMaker's text format."""
    quad = model.Quad(0, 0, 32, 32, 0, 0, 0.5, 0.25, 0xFFFFFF, 1)
    text = zlib.decompress(model.model_g3z([quad])).decode()
    lines = text.split('\r\n')
    assert lines[0] == '100'
    assert int(lines[1]) == len(lines) - 3 == 8
    assert lines[2].startswith('0 4.0000')
    assert lines[3] == (
        '5 0.0000 0.0000 0.0000 0.0000 0.0000 16777215.0000 1.0000'
        ' 0.0000 0.0000 0.0000'
    )
    assert lines[-2].startswith('1 0.0000')


def test_sub_scaled_stays_on_whole_pixels() -> None:
    """Offsets that are whole pixels scaled don't pick up float error."""
    tile = tiles.parse_line('bg,112,0,0,0,1221,608,0,0.8,0.8,4294967295')
    part = tile.sub(185, 0, 794, 593)
    assert part.format() == 'bg,260,0,185,0,794,593,0,0.8,0.8,4294967295'
