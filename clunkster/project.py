"""Source project."""

from pathlib import Path

from clunkster.text.line import LineMap


class Project:
    """Source project: root directory and cached reads of its text files.

    Reads are cached for the lifetime of the object, create a new one to see
    changes made to the files afterwards.
    """

    def __init__(self, root: Path) -> None:
        """Initialize the project.

        :param root: Absolute path to the project root, where the ``.gm82``
          file is stored.
        """
        if not root.is_absolute():
            raise ValueError(f"Expected an absolute path, got '{root}'")
        if not root.is_dir():
            raise NotADirectoryError(root)
        self.root = root
        self._text: dict[Path, str] = {}
        self._line_maps: dict[Path, LineMap] = {}
        self._lines: dict[Path, tuple[str, ...]] = {}

    def rel(self, path: Path) -> str:
        """Convert absolute path in the project to POSIX relative path."""
        if not path.is_absolute():
            raise ValueError(f"Expected an absolute path, got '{path}'")
        if not path.is_relative_to(self.root):
            raise ValueError(f"Path '{path}' isn't in root {self.root}")
        return path.relative_to(self.root).as_posix()

    def try_rel(self, path: Path) -> str:
        """Try to convert absolute path in the project to POSIX relative path.

        If impossible, returns path as is.
        """
        if not path.is_absolute():
            raise ValueError(f"Expected an absolute path, got '{path}'")
        if not path.is_relative_to(self.root):
            return str(path)
        return path.relative_to(self.root).as_posix()

    def read(self, path: Path) -> str:
        """Read project's text file with caching."""
        if path in self._text:
            return self._text[path]
        if not path.is_absolute():
            raise ValueError(f"Expected an absolute path, got '{path}'")
        if not path.is_relative_to(self.root):
            raise ValueError(f"Path '{path}' isn't in root {self.root}")
        txt = path.read_text(encoding='utf-8')
        self._text[path] = txt
        return txt

    def line_map(self, path: Path) -> LineMap:
        """Read line map with caching."""
        if path not in self._line_maps:
            self._line_maps[path] = LineMap.from_text(self.read(path))
        return self._line_maps[path]

    def lines(self, path: Path) -> tuple[str, ...]:
        """Read lines with caching."""
        if path not in self._lines:
            self._lines[path] = tuple(self.read(path).splitlines())
        return self._lines[path]
