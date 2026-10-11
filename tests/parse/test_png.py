"""Unit tests for PNG metadata reading."""

from pathlib import Path

import pytest
from PIL import Image

from clunkster.parse import png


def test_size(tmp_path: Path) -> None:
    """Size is read from the header."""
    file = tmp_path / 'a.png'
    Image.new('RGBA', (37, 5)).save(file)
    assert png.size(file) == (37, 5)


def test_not_png(tmp_path: Path) -> None:
    """Other files are rejected."""
    file = tmp_path / 'a.png'
    file.write_bytes(b'GIF89a' + bytes(30))
    with pytest.raises(ValueError, match='Not a PNG'):
        png.size(file)
