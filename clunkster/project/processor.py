"""Processors, aka Task factories."""

import collections.abc as col
from abc import ABC, abstractmethod
from pathlib import Path

from clunkster.asset import Asset
from clunkster.project.task import Task


class Processor(ABC):
    """Abstract factory class that analyzes the project and generates Tasks."""

    @abstractmethod
    def get_ignored_source_dirs(
        self, project_root: Path
    ) -> col.Iterable[Path]:
        """Return directories this processor manages exclusively.

        Any directories listed here should be skipped when copying the project.
        :param project_root: Project root directory.
        :return: Paths to directories that should be skipped.
        """

    @abstractmethod
    def generate_tasks(
        self, assets: col.Iterable[Asset], project_root: Path, dir_out: Path
    ) -> col.Iterable[Task]:
        """Analyze the parsed asset list and yield concrete Task objects.

        :param assets: Input asset list.
        :param project_root: Project root directory.
        :param dir_out: Path to build output directory.
        :return: Iterable of Tasks.
        """
