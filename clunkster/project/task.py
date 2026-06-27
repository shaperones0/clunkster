"""Processing pipeline backbone."""

import collections.abc as col
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
import functools as ft
import hashlib
import shutil
from typing import override


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


class TaskGeneric(Task, ABC):
    def __init__(self, *, task_id: str, inputs: col.Sequence[Path], outputs: col.Sequence[Path]) -> None:
        self._task_id = task_id
        self._inputs = inputs
        self._outputs = outputs

    @override
    @property
    def task_id(self) -> str:
        return self._task_id

    @override
    @property
    def inputs(self) -> col.Iterable[Path]:
        return self._inputs

    @override
    @property
    def outputs(self) -> col.Iterable[Path]:
        return self._outputs


class TaskCopy(TaskGeneric):

    def __init__(self, file: Path, dir_input_root: Path, dir_output_root: Path) -> None:
        assert file.is_file()
        self.file_input = file
        self.file_output = dir_output_root / file.relative_to(dir_input_root)
        super().__init__(
            task_id=f'copy_{self.file_output}',
            inputs=(self.file_input,),
            outputs=(self.file_output,)
        )

    @override
    def execute(self) -> None:
        shutil.copy2(self.file_input, self.file_output)


class TaskCopyTree(TaskGeneric):

    def __init__(self, dir_input: Path, dir_output: Path) -> None:
        assert dir_input.is_dir()
        assert dir_output.is_dir()
        self.dir_input = dir_input
        self.dir_output = dir_output

        self.input_files = tuple(
            pth for pth in dir_input.rglob('*') if pth.is_file()
        )
        self.output_files = tuple(
            dir_output / pth.relative_to(dir_input) for pth in self.input_files
        )

        super().__init__(
            task_id=f'copytree_{self.dir_input}',
            inputs=self.input_files,
            outputs=self.output_files
        )

    @override
    def execute(self) -> None:
        shutil.copytree(self.dir_input, self.dir_output)
