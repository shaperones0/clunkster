"""Build progress caching."""

import collections.abc as col
import json
import time
from pathlib import Path

from clunkster.pipeline.task import FileStat, Task

CACHE_VERSION = 2

# files modified this recently might change again without their stat showing
#  it (coarse mtime resolution on some filesystems), so their stats aren't
#  trusted and they get rehashed on the next run
RACY_WINDOW_NS = 2_000_000_000


class FileBuildCache:
    """Cache file.

    Save progress of each transformation into a file.

    Tasks are matched by hash of their inputs. To avoid reading every input
    on every build, stats (mtime, size, file id) of the inputs are stored as
    well: if none of them changed, the hash isn't recalculated. Changed stats
    with the same content (e.g. after git checkout) only cost a rehash.
    """

    def __init__(self, cache_file: Path) -> None:
        """Initialize cache file.

        :param cache_file: Path to the cache file.
        """
        self.cache_file = cache_file
        self.data: dict[str, str] = {}
        self.stats: dict[str, tuple[FileStat, ...]] = {}
        if self.cache_file.exists():
            with self.cache_file.open('r') as f:
                raw = json.load(f)
            if raw.get('version') == CACHE_VERSION:
                self.data = raw['hashes']
                self.stats = {
                    task_id: tuple(
                        (mtime, size, ino) for mtime, size, ino in stats
                    )
                    for task_id, stats in raw['stats'].items()
                }
            else:
                # version 1: flat task id to hash mapping
                self.data = raw

    def is_fresh(
        self,
        *,
        task_id: str,
        current_hash: str,
        outputs: col.Iterable[Path],
    ) -> bool:
        """Whether the task doesn't need to be executed.

        Checks whether task input's `current_hash` has changed, or
        output files are gone.
        :param task_id: Task ID.
        :param current_hash: Hash of the task's inputs.
        :param outputs: Paths to task outputs.
        :return: ``False``, if task must be executed.
        """
        if not all(out.exists() for out in outputs):
            return False
        return self.data.get(task_id) == current_hash

    def task_is_fresh(self, task: Task) -> bool:
        """Whether the task doesn't need to be executed.

        Skips hashing if input stats are unchanged. If the hash matches
        despite changed stats, stored stats are refreshed.
        """
        stats = task.inputs_stats
        if not all(out.exists() for out in task.outputs_cached):
            return False
        if task.task_id not in self.data:
            return False

        if self.stats.get(task.task_id) == stats:
            return True

        if self.data[task.task_id] != task.inputs_hash:
            return False
        self._update_stats(task.task_id, stats)
        return True

    def update(
        self,
        task_id: str,
        current_hash: str,
        stats: tuple[FileStat, ...] | None = None,
    ) -> None:
        """Update task's hash.

        :param task_id: Task ID.
        :param current_hash: Task's current hash of the inputs.
        :param stats: Stats of the inputs, taken before hashing them.
        """
        self.data[task_id] = current_hash
        self._update_stats(task_id, stats)

    def _update_stats(
        self, task_id: str, stats: tuple[FileStat, ...] | None
    ) -> None:
        """Store task's input stats, unless they are too recent to trust."""
        racy_after = time.time_ns() - RACY_WINDOW_NS
        if stats is None or any(mtime > racy_after for mtime, _, _ in stats):
            self.stats.pop(task_id, None)
        else:
            self.stats[task_id] = stats

    def save(self) -> None:
        """Save task's hashes back to cache file."""
        temp_file = self.cache_file.with_suffix('.tmp')

        with temp_file.open('w') as f:
            json.dump(
                {
                    'version': CACHE_VERSION,
                    'hashes': self.data,
                    'stats': self.stats,
                },
                f,
                indent=2,
            )
        temp_file.replace(self.cache_file)
