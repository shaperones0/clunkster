"""Processing pipeline backbone."""

import collections.abc as col
from abc import ABC, abstractmethod
from pathlib import Path
import functools as ft
import hashlib
import shutil
from typing import override


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
    def inputs(self) -> col.Sequence[Path]:
        return self._inputs

    @override
    @property
    def outputs(self) -> col.Sequence[Path]:
        return self._outputs


class TaskCopy(TaskGeneric):
    def __init__(self, file_input: Path, file_output: Path) -> None:
        if not file_input.is_file():
            raise ValueError(f'Input {file_input} is not a file')
        if file_output.exists():
            if not file_output.is_file():
                raise ValueError(f'Attempted file write into directory {file_output}')

        self.file_input = file_input
        self.file_output = file_output
        super().__init__(
            task_id=f'copy_{file_input}',
            inputs=(file_input,),
            outputs=(file_output,),
        )

    @override
    def execute(self) -> None:
        shutil.copy2(self.file_input, self.file_output)


class TaskCopyRebase(TaskGeneric):

    def __init__(self, *files: Path, dir_input_root: Path, dir_output_root: Path) -> None:
        not_files = tuple(file for file in files if not file.is_file())
        if not_files:
            raise ValueError(f'Input {not_files} are not files')

        self.files_input = files
        self.files_output = tuple(
            dir_output_root / pth.relative_to(dir_input_root) for pth in self.files_input
        )
        super().__init__(
            task_id=f'copy_rebase_{self.files_input}',
            inputs=self.files_input,
            outputs=self.files_output,
        )

    @override
    def execute(self) -> None:
        for file_input, file_dest in zip(self.files_input, self.files_output):
            shutil.copy2(file_input, file_dest)


class TaskCopyTree(TaskGeneric):

    def __init__(self, dir_input: Path, dir_output: Path) -> None:
        if not dir_input.is_dir():
            raise ValueError(f'Input {dir_input} is not a directory')
        if dir_output.exists():
            if not dir_output.is_dir():
                raise ValueError(f'Attempted dir write into non-directory {dir_output}')
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
        shutil.copytree(self.dir_input, self.dir_output, dirs_exist_ok=True)
