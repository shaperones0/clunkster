"""Read PNG metadata."""

import struct
from pathlib import Path

_SIGNATURE = b'\x89PNG\r\n\x1a\n'


def size(path: Path) -> tuple[int, int]:
    """Read image width and height from PNG header, without decoding it.

    :param path: PNG file.
    :return: Width and height.
    """
    with path.open('rb') as f:
        header = f.read(24)
    # signature, then IHDR chunk: length, type, width, height
    if header[:8] != _SIGNATURE or header[12:16] != b'IHDR':
        raise ValueError(f'Not a PNG file: {path}')
    width, height = struct.unpack('>II', header[16:24])
    return width, height
