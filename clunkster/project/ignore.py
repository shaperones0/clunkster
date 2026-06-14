"""Git-ignore-style matcher."""

import collections.abc as col
import fnmatch
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Self

_GLOB_CHARS = '*?['


def _is_glob(pattern: str) -> bool:
    return any(ch in pattern for ch in _GLOB_CHARS)


def _glob_compile(pattern: str) -> re.Pattern[str]:
    return re.compile(fnmatch.translate(pattern))


@dataclass(frozen=True, slots=True)
class FileIgnore:
    """Precompiled ignore matcher for gitignore-like patterns.

    Supported behavior:
    - ignore empty lines and # comments
    - patterns ending with '/' treated as directory-name rules
    - patterns without '/' matched against both basename and full relative path
    - patterns with '/' matched against the full relative path only
    """

    dir_names: frozenset[str]
    exact_names: frozenset[str]
    exact_paths: frozenset[str]
    glob_names: tuple[re.Pattern[str], ...]
    glob_paths: tuple[re.Pattern[str], ...]

    @classmethod
    def from_file(cls, ignore_file: Path) -> Self:
        """Read patterns from file."""
        if not ignore_file.exists():
            return cls(
                dir_names=frozenset(),
                exact_names=frozenset(),
                exact_paths=frozenset(),
                glob_names=(),
                glob_paths=(),
            )

        return cls.from_lines(
            ignore_file.read_text(encoding='utf-8').splitlines()
        )

    @classmethod
    def from_lines(cls, lines: col.Iterable[str]) -> Self:
        """Read patterns from lines."""
        dir_names: set[str] = set()
        exact_names: set[str] = set()
        exact_paths: set[str] = set()
        glob_names: list[re.Pattern[str]] = []
        glob_paths: list[re.Pattern[str]] = []

        for raw_line in lines:
            line = raw_line.strip()
            if not line or line.startswith('#'):
                continue

            if line.endswith('/'):
                # dir rule ("cache/", ".git/")
                dir_name = line.rstrip('/')
                if dir_name:
                    dir_names.add(dir_name)
                continue

            has_slash = '/' in line
            if _is_glob(line):
                compiled = _glob_compile(line)
                if has_slash:
                    glob_paths.append(compiled)
                else:
                    glob_names.append(compiled)
            # literal rule
            elif has_slash:
                exact_paths.add(line)
            else:
                exact_names.add(line)

        return cls(
            dir_names=frozenset(dir_names),
            exact_names=frozenset(exact_names),
            exact_paths=frozenset(exact_paths),
            glob_names=tuple(glob_names),
            glob_paths=tuple(glob_paths),
        )

    def is_ignored(self, path_rel_posix: str) -> bool:
        """Check whether a path should be ignored.

        Input paths should be relative and POSIX, like "src/foo/bar.txt"
        :param path_rel_posix: Relative POSIX path.
        :return: True, if ignored.
        """
        if not path_rel_posix:
            return False

        base = path_rel_posix.rsplit('/', 1)[-1]

        # dir: ignore if any path segment matches.
        if self.dir_names:
            for part in path_rel_posix.split('/'):
                if part in self.dir_names:
                    return True

        # literal
        if path_rel_posix in self.exact_paths or base in self.exact_names:
            return True

        # globs
        for rx in self.glob_paths:
            if rx.match(path_rel_posix):
                return True

        for rx in self.glob_names:
            if rx.match(base) or rx.match(path_rel_posix):
                return True

        return False
