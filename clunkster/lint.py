"""Linter-related shims."""

from clunkster.text.location import Location
from clunkster.text import read
from abc import ABC, abstractmethod
import collections.abc as col
from typing import TypeVar, override, ClassVar
from pathlib import Path
import itertools as it
import warnings
from dataclasses import dataclass
from enum import StrEnum


TError = TypeVar("TError", bound="LinterViolation")


class Severity(StrEnum):
    """Linter violation severity.

    Errors are raised when consumed.
    """

    ERROR = 'error'
    WARNING = 'warning'
    INFO = 'info'


class LinterViolation(ABC):
    """Abstract linter violation."""

    rule: ClassVar[str]
    severity: ClassVar[Severity]

    def __init__(self) -> None:
        self.session: LinterSession | None = None

    def _try_path_rel(self, path: Path) -> str:
        if self.session is None:
            return str(path)
        return self.session.path_try_rel(path)

    @property
    @abstractmethod
    def message(self) -> str:
        """Get linter violation message."""

    @classmethod
    def format_many(cls: type[TError], errors: col.Iterable[TError], *, verbose: bool = False) -> str:
        """Compose an error message from a block of linter errors.

        Default implementation uses ``<file>:<line>:<column>: <err>`` format.
        """
        errors = list(errors)
        if not errors:
            return f"=== {cls.rule}: no issues"

        lines = [f"=== {cls.rule}: {len(errors)} issue(s)"]
        for err in errors:
            if verbose:
                lines.append(err.format_verbose())
            else:
                lines.append(f"  {err.format_li()}")
        return "\n".join(lines)

    def format_li(self) -> str:
        """Compose an error message to appear in a standard error list.

        Default implementation just outputs the error message.
        """
        return self.message

    def format_verbose(self) -> str:
        """Compose verbose error message.

        Linter bound to a location should output part of the file.
        """
        return self.message

    def sort_key(self) -> tuple[str, ...]:
        """Generate a sort key for this violation."""
        return (type(self).rule,)


class GenericViolation(LinterViolation):
    @property
    def message(self) -> str:
        return self.msg

    def __init__(self, message: str) -> None:
        super().__init__()
        self.msg = message


class LinterViolationBound(LinterViolation, ABC):
    """Linter violation bound to a location in a text file."""

    @property
    @abstractmethod
    def location(self) -> Location:
        """Get linter violation location."""

    @override
    def format_li(self) -> str:
        """Compose an error message to appear in a standard error list.

        Adds source file location info before the error message.
        """
        loc = self.location
        base = f"{self.rule} - {self._try_path_rel(loc.file)}:{loc.loc_line}:{loc.loc_column}"
        if self.message:
            return base + f": {self.message}"
        return base

    @override
    def format_verbose(self) -> str:
        """Compose verbose error message.

        Adds few lines of the source file to the output.
        """
        loc = self.location
        lines = list(enumerate(read.read_lines(loc.file), start=1))
        lines_slice = lines[max(0, loc.loc_line - 3):min(len(lines), loc.loc_line + 3)]
        output_lines: list[str] = [
            self.format_li()
        ]

        for num, line in lines_slice:
            output_lines.append(
                f"{num:>3}|{line}"
            )
            if num == loc.loc_line:
                output_lines.append("   " + " " * (loc.loc_column - 1) + "^")
        return "\n".join(output_lines)

    @override
    def sort_key(self) -> tuple[str, ...]:
        """Generate a sort key for this violation.

        This one adds location data.
        """
        return type(self).rule, self._try_path_rel(self.location.file), f"{self.location.loc_line:>4}", f"{self.location.loc_column:>4}",


class GenericBoundViolation(LinterViolationBound):
    @property
    def location(self) -> Location:
        return self.location

    @property
    def message(self) -> str:
        return self.msg

    def __init__(self, message: str, location: Location) -> None:
        super().__init__()
        self.msg = message
        self.loc = location


@dataclass(frozen=True, slots=True)
class DiagnosticBatch:
    infos: tuple[LinterViolation, ...]
    warnings: tuple[LinterViolation, ...]
    errors: tuple[LinterViolation, ...]


class DiagnosticConsumer(ABC):
    @abstractmethod
    def consume(self, batch: DiagnosticBatch, *, verbose: bool = False) -> None:
        """Consume a diagnostic batch."""


class LinterFoundErrors(RuntimeError):
    def __init__(self, message: str, errors: col.Iterable[LinterViolation]):
        super().__init__(message)
        self.errors = list(errors)


class CliConsumer(DiagnosticConsumer):
    @override
    def consume(self, batch: DiagnosticBatch, *, verbose: bool = False) -> None:
        if batch.infos:
            print(err_format(batch.infos, verbose=verbose))
        if batch.warnings:
            warnings.warn(err_format(batch.warnings, verbose=verbose))
        if batch.errors:
            raise LinterFoundErrors(err_format(batch.errors, verbose=verbose), batch.errors)

class LinterSession:
    """Linter session."""

    def __init__(self, root: Path, consumer: DiagnosticConsumer) -> None:
        self.root = root
        self.consumer = consumer
        self.errors: list[LinterViolation] = []

    def path_try_rel(self, path: Path) -> str:
        if path.is_relative_to(self.root):
            return str(path.relative_to(self.root))
        return str(path)

    def push(self, error: LinterViolation) -> None:
        error.session = self
        self.errors.append(error)

    def collect(self, *cls: type[LinterViolation], flush: bool = True) -> DiagnosticBatch:
        err_severities = self._classify(*cls)
        if flush:
            self._flush(it.chain.from_iterable(err_severities.values()))
        return DiagnosticBatch(
            infos=tuple(err_severities.get(Severity.INFO, [])),
            warnings=tuple(err_severities.get(Severity.WARNING, [])),
            errors=tuple(err_severities.get(Severity.ERROR, []))
        )

    def consume(self, *cls: type[LinterViolation], verbose: bool = False, flush: bool = True) -> None:
        batch = self.collect(*cls, flush=flush)
        self.consumer.consume(batch, verbose=verbose)

    def flush(self, *cls: type[LinterViolation]) -> None:
        err_severities = self._classify(*cls)
        self._flush(it.chain.from_iterable(err_severities.values()))

    def _flush(self, errors: col.Iterable[LinterViolation]) -> None:
        remove = {id(err) for err in errors}
        self.errors[:] = [
            err
            for err in self.errors
            if id(err) not in remove
        ]

    def _classify(self, *cls: type[LinterViolation]) -> dict[Severity, list[LinterViolation]]:
        """Filter violations into ones that should be raised or just warned."""

        err_severities: dict[Severity, list[LinterViolation]] = {}
        for err in self.errors:
            if cls and not isinstance(err, cls):
                continue
            err_severities.setdefault(type(err).severity, []).append(err)

        return err_severities

    def assert_empty(self) -> None:
        if self.errors:
            raise LinterFoundErrors(
                message=f"Expected no errors in queue, found: {self.errors}",
                errors=self.errors
            )


def err_format(errors: col.Iterable[LinterViolation], verbose: bool = False) -> str:
    """Turn errors into messages.

    :param errors: Errors to turn into messages.
    :param verbose: Whether to use verbose output.
    :return: Composed text.
    """
    grouped: dict[str, dict[type[LinterViolation], list[LinterViolation]]] = {}
    for err in errors:
        grouped.setdefault(type(err).rule, {}).setdefault(type(err), []).append(err)
    for rule, cls_grouped in grouped.items():
        for cls, violations in cls_grouped.items():
            violations.sort(key=cls.sort_key)

    return "\n\n".join(
        cls.format_many(violations, verbose=verbose)
        for rule, cls_grouped in grouped.items()
        for cls, violations in cls_grouped.items()
    )
