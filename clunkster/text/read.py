"""Read cacher."""
from collections.abc import Iterator
from pathlib import Path
from itertools import pairwise, chain
from clunkster.text.line import LineMap


# list of roots from where the caching may take place
READ_ONLY_ROOTS: list[Path] = []
CACHE_TXT: dict[Path, str] = {}
CACHE_MAPS: dict[Path, LineMap] = {}
CACHE_LINES: dict[Path, tuple[str, ...]] = {}


def reg_root(root_path: Path) -> None:
    if not root_path.is_dir():
        raise NotADirectoryError(root_path)
    if root_path in READ_ONLY_ROOTS:
        raise KeyError(f'Path {root_path} is already registered.')
    READ_ONLY_ROOTS.append(root_path)


def read(path: Path, *, must_readonly: bool = True) -> str:
    """Read with caching read-only locations."""
    if not path.is_absolute():
        raise ValueError(f"Expected an absolute path, got '{path}'")
    if not path.is_file():
        raise FileNotFoundError(path)

    for root in READ_ONLY_ROOTS:
        if path.is_relative_to(root):
            # found
            if path in CACHE_TXT:
                return CACHE_TXT[path]
            txt = path.read_text(encoding='utf-8')
            CACHE_TXT[path] = txt
            return txt
    else:
        if must_readonly:
            raise ValueError(f"Path '{path}' isn't in any of the registered read-only roots: '{repr(READ_ONLY_ROOTS)}'")
        return path.read_text(encoding='utf-8')


def line_map(path: Path, *, must_readonly: bool = True) -> LineMap:
    if path in CACHE_MAPS:
        return CACHE_MAPS[path]
    lm = LineMap.from_text(read(path, must_readonly=must_readonly))
    CACHE_MAPS[path] = lm
    return lm


def lines(path: Path, *, must_readonly: bool = True) -> tuple[str, ...]:
    if path in CACHE_LINES:
        return CACHE_LINES[path]
    ls = tuple(read(path, must_readonly=must_readonly).splitlines())
    CACHE_LINES[path] = ls
    return ls
