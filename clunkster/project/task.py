"""Processing pipeline backbone."""

import collections.abc as col
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
import functools as ft
import hashlib


def file_hash(*paths: Path) -> str:
    """Calculate MD5 hash of all input files."""
    hasher = hashlib.md5()
    for filepath in sorted(paths):
        if filepath.exists():
            assert filepath.is_file()
            with filepath.open('rb') as f:
                for chunk in iter(lambda: f.read(4096), b''):
                    hasher.update(chunk)
    return hasher.hexdigest()


class Task(ABC):
    """Base class for project processing tasks."""

    @abstractmethod
    def execute(self) -> None:
        """Specific processing logic."""

    @property
    @abstractmethod
    def task_id(self) -> str:
        """Task ID."""

    @property
    @abstractmethod
    def inputs(self) -> col.Iterable[Path]:
        """Input files."""

    @ft.cached_property
    def inputs_cached(self) -> col.Iterable[Path]:
        """Input files."""
        return self.inputs

    @abstractmethod
    @property
    def outputs(self) -> col.Iterable[Path]:
        """Output files."""

    @ft.cached_property
    def outputs_cached(self) -> col.Iterable[Path]:
        """Output files."""
        return self.outputs

    @ft.cached_property
    def inputs_hash(self) -> str:
        """Calculate MD5 hash of all input files."""
        return file_hash(*self.inputs_cached)
