"""Pipeline task."""

import collections.abc as col
import functools as ft
import hashlib
import shutil
from abc import ABC, abstractmethod
from pathlib import Path
from typing import override

from clunkster import project


def file_hash(*paths: Path) -> str:
    """Calculate MD5 hash of all input files."""
    hasher = hashlib.md5()
    for filepath in sorted(paths):
        if not filepath.exists():
            raise FileNotFoundError(filepath)
        if not filepath.is_file():
            raise ValueError(f'{filepath} is not a file')
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
    def inputs(self) -> col.Sequence[Path]:
        """Input files."""

    @ft.cached_property
    def inputs_cached(self) -> col.Sequence[Path]:
        """Input files."""
        return self.inputs

    @property
    @abstractmethod
    def outputs(self) -> col.Sequence[Path]:
        """Output files."""

    @ft.cached_property
    def outputs_cached(self) -> col.Sequence[Path]:
        """Output files."""
        return self.outputs

    @ft.cached_property
    def inputs_hash(self) -> str:
        """Calculate MD5 hash of all input files."""
        return file_hash(*self.inputs_cached)


class TaskGeneric(Task, ABC):
    """Generic task with constant properties."""

    def __init__(
        self,
        *,
        task_id: str,
        inputs: col.Sequence[Path],
        outputs: col.Sequence[Path],
    ) -> None:
        """Initialize generic task.

        :param task_id: Task ID.
        :param inputs: Task input files.
        :param outputs: Task output files.
        """
        self._task_id = task_id
        self._inputs = inputs
        self._outputs = outputs

    @override
    @property
    def task_id(self) -> str:
        return self._task_id

    @override
    @property
    def inputs(self) -> col.Sequence[Path]:
        return self._inputs

    @override
    @property
    def outputs(self) -> col.Sequence[Path]:
        return self._outputs


class TaskCopy(TaskGeneric):
    """File copy task."""

    def __init__(self, *files: tuple[Path, Path]) -> None:
        """Initialize file copy task.

        :param files: Pairs of (input file, output file).
        """
        files_input, files_output = zip(*files, strict=True)

        not_files = tuple(file for file in files_input if not file.is_file())
        if not_files:
            raise ValueError(f'Inputs {not_files} not files')
        exist_but_not_file = tuple(
            file
            for file in files_output
            if file.exists() and not file.is_file()
        )
        if exist_but_not_file:
            raise ValueError(
                f'Attempted file write into directory {exist_but_not_file}'
            )

        self.files = files
        super().__init__(
            task_id=f'copy_{
                ":".join(project.try_rel(file) for file in files_input)
            }->{":".join(project.try_rel(file) for file in files_output)}',
            inputs=files_input,
            outputs=files_output,
        )

    @override
    def execute(self) -> None:
        for file_input, file_output in self.files:
            shutil.copy2(file_input, file_output)


class TaskCopyTree(TaskGeneric):
    """Copy tree task."""

    def __init__(self, dir_input: Path, dir_output: Path) -> None:
        """Initialize copy tree task.

        :param dir_input: Input directory to copy from.
        :param dir_output: Output directory to copy to.
        """
        if not dir_input.is_dir():
            raise ValueError(f'Input {dir_input} is not a directory')
        if dir_output.exists() and not dir_output.is_dir():
            raise ValueError(
                f'Attempted dir write into non-directory {dir_output}'
            )
        self.dir_input = dir_input
        self.dir_output = dir_output

        self.input_files = tuple(
            pth for pth in dir_input.rglob('*') if pth.is_file()
        )
        self.output_files = tuple(
            dir_output / pth.relative_to(dir_input) for pth in self.input_files
        )

        super().__init__(
            task_id=f'copytree_{self.dir_input}->{self.dir_output}',
            inputs=self.input_files,
            outputs=self.output_files,
        )

    @override
    def execute(self) -> None:
        shutil.copytree(self.dir_input, self.dir_output, dirs_exist_ok=True)
