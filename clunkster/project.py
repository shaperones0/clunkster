"""Read cacher."""

from pathlib import Path

from clunkster.text.line import LineMap

# root from where caching may take place
ROOT: Path | None = None
CACHE_TXT: dict[Path, str] = {}
CACHE_MAPS: dict[Path, LineMap] = {}
CACHE_LINES: dict[Path, tuple[str, ...]] = {}


def set_root(root_path: Path) -> None:
    """Set project root."""
    global ROOT

    if not root_path.is_dir():
        raise NotADirectoryError(root_path)
    if ROOT is not None:
        raise KeyError(f'Root {root_path} is already registered.')
    ROOT = root_path


def rel(path: Path) -> str:
    """Convert absolute path in the project to POSIX relative path."""
    if not path.is_absolute():
        raise ValueError(f"Expected an absolute path, got '{path}'")
    if ROOT is None:
        raise ValueError('Root is not registered yet.')
    if not path.is_relative_to(ROOT):
        raise ValueError(f"Path '{path}' isn't in root {ROOT}")
    return path.relative_to(ROOT).as_posix()


def try_rel(path: Path) -> str:
    """Try to convert absolute path in the project to POSIX relative path.

    If impossible, returns path as is.
    """
    if not path.is_absolute():
        raise ValueError(f"Expected an absolute path, got '{path}'")
    if ROOT is None or not path.is_relative_to(ROOT):
        return str(path)
    return path.relative_to(ROOT).as_posix()


def read(path: Path, *, must_root: bool = True) -> str:
    """Read with caching."""
    if not path.is_absolute():
        raise ValueError(f"Expected an absolute path, got '{path}'")
    if not path.is_file():
        raise FileNotFoundError(f"Expected a directory, got '{path}'")

    if ROOT is not None and path.is_relative_to(ROOT):
        # found
        if path in CACHE_TXT:
            return CACHE_TXT[path]
        txt = path.read_text(encoding='utf-8')
        CACHE_TXT[path] = txt
        return txt
    if must_root:
        raise ValueError(f"Path '{path}' isn't in root {ROOT}")
    return path.read_text(encoding='utf-8')


def line_map(path: Path, *, must_root: bool = True) -> LineMap:
    """Read line map with caching."""
    if path in CACHE_MAPS:
        return CACHE_MAPS[path]
    lm = LineMap.from_text(read(path, must_root=must_root))
    CACHE_MAPS[path] = lm
    return lm


def lines(path: Path, *, must_root: bool = True) -> tuple[str, ...]:
    """Read lines with caching."""
    if path in CACHE_LINES:
        return CACHE_LINES[path]
    ls = tuple(read(path, must_root=must_root).splitlines())
    CACHE_LINES[path] = ls
    return ls
