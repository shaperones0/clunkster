"""Per-file cache of reference scan results."""

import collections.abc as col
import json
import time
from dataclasses import dataclass
from pathlib import Path

from clunkster.pipeline.cache import RACY_WINDOW_NS
from clunkster.pipeline.task import FileStat

CACHE_VERSION = 1


@dataclass(frozen=True, slots=True)
class FileMatch:
    """Reference found in a file."""

    # absolute index in the file's text
    idx: int
    line: int
    column: int
    # referenced name
    target: str
    # guard contexts the reference is in
    contexts: tuple[str, ...]


class ScanCache:
    """Per-file cache of reference scan results.

    A file's matches are reused while its stat is unchanged and the set of
    scanned names stays the same (see ``set_names``). Entries of files that
    weren't looked up since the last save are dropped on save.
    """

    def __init__(self, cache_file: Path) -> None:
        """Initialize the cache, loading the cache file if it exists.

        :param cache_file: Path to the cache file.
        """
        self.cache_file = cache_file
        self.names_key = ''
        self._entries: dict[str, tuple[FileStat, tuple[FileMatch, ...]]] = {}
        self._used: set[str] = set()
        self._dirty = False

        if not cache_file.exists():
            return
        with cache_file.open('r', encoding='utf-8') as f:
            raw = json.load(f)
        if raw.get('version') != CACHE_VERSION:
            return
        self.names_key = raw['names_key']
        for file, ((mtime, size, ino), matches) in raw['files'].items():
            self._entries[file] = (
                (mtime, size, ino),
                tuple(
                    FileMatch(idx, line, column, target, tuple(contexts))
                    for idx, line, column, target, contexts in matches
                ),
            )

    def set_names(self, names_key: str) -> None:
        """Set the key of scanned names, e.g. a hash of all asset names.

        Entries scanned for different names are dropped.
        """
        if names_key != self.names_key:
            self.names_key = names_key
            self._entries.clear()
            self._dirty = True

    def get(self, path: Path, stat: FileStat) -> tuple[FileMatch, ...] | None:
        """Get file's cached matches, ``None`` if missing or outdated.

        :param path: Scanned file.
        :param stat: File's current stat.
        """
        key = str(path)
        self._used.add(key)
        entry = self._entries.get(key)
        if entry is None or entry[0] != stat:
            return None
        return entry[1]

    def put(
        self, path: Path, stat: FileStat, matches: col.Iterable[FileMatch]
    ) -> None:
        """Store file's matches.

        :param path: Scanned file.
        :param stat: File's stat, taken before reading it.
        :param matches: Matches found in the file.
        """
        key = str(path)
        self._used.add(key)
        self._dirty = True
        if stat[0] > time.time_ns() - RACY_WINDOW_NS:
            # too recent to trust the stat, rescan next time
            self._entries.pop(key, None)
            return
        self._entries[key] = (stat, tuple(matches))

    def save(self) -> None:
        """Save the cache, if anything changed."""
        unused = self._entries.keys() - self._used
        for key in unused:
            del self._entries[key]
        self._dirty = self._dirty or bool(unused)
        self._used.clear()
        if not self._dirty:
            return

        data = {
            'version': CACHE_VERSION,
            'names_key': self.names_key,
            'files': {
                key: (
                    stat,
                    [
                        (m.idx, m.line, m.column, m.target, m.contexts)
                        for m in matches
                    ],
                )
                for key, (stat, matches) in self._entries.items()
            },
        }
        temp_file = self.cache_file.with_suffix('.tmp')
        # dumps, unlike dump, uses the C encoder, which is a lot faster
        temp_file.write_text(
            json.dumps(data, separators=(',', ':')), encoding='utf-8'
        )
        temp_file.replace(self.cache_file)
        self._dirty = False
