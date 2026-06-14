"""Build progress caching."""

import collections.abc as col
import json
from pathlib import Path


class FileBuildCache:
    """Cache file.

    Save progress of each transformation into a file.
    """

    def __init__(self, cache_file: Path) -> None:
        """Initialize cache file.

        :param cache_file: Path to the cache file.
        """
        self.cache_file = cache_file
        self.data = {}
        if self.cache_file.exists():
            with self.cache_file.open('r') as f:
                self.data = json.load(f)

    def is_fresh(
        self,
        *,
        task_id: str,
        current_hash: str,
        outputs: col.Iterable[Path],
    ) -> bool:
        """Whether the task needs to be executed.

        Checks whether task input's `current_hash` has changed, or
        output files are gone.
        :param task_id: Task ID.
        :param current_hash: Hash of the task's inputs.
        :param outputs: Paths to task outputs.
        :return: ``True``, if task must be executed.
        """
        if not all(out.exists() for out in outputs):
            return False
        return self.data.get(task_id) == current_hash

    def update(self, task_id: str, current_hash: str) -> None:
        """Update task's hash.

        :param task_id: Task ID.
        :param current_hash: Task's current hash of the inputs.
        """
        self.data[task_id] = current_hash

    def save(self) -> None:
        """Save task's hashes back to cache file."""
        with self.cache_file.open('w') as f:
            json.dump(self.data, f, indent=2)
