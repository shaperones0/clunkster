"""Linter system."""

import collections.abc as col
import itertools as it
import warnings
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import ClassVar, TypeVar, override

from clunkster import project
from clunkster.asset import Asset, AssetHasPath
from clunkster.text.location import Location

TError = TypeVar('TError', bound='LinterViolation')


class Severity(StrEnum):
    """Linter violation severity."""

    ERROR = 'error'
    WARNING = 'warning'
    INFO = 'info'


class LinterViolation(ABC):
    """Abstract linter violation."""

    rule: ClassVar[str]
    severity: ClassVar[Severity]

    @classmethod
    def format_many(
        cls: type[TError],
        errors: col.Iterable[TError],
        *,
        verbose: bool = False,
    ) -> str:
        """Compose an error message from a block of linter errors.

        Default implementation uses ``<file>:<line>:<column>: <err>`` format.
        """
        errors = tuple(errors)
        if not errors:
            return f'=== {cls.rule}: no issues'

        lines = [
            f'=== {cls.rule}({cls.__name__}): {len(errors)} '
            + {
                Severity.INFO: 'note(s)',
                Severity.WARNING: 'warning(s)!',
                Severity.ERROR: 'ERROR(S)!!!',
            }[cls.severity]
        ]
        for err in errors:
            if verbose:
                lines.append(err.format_verbose())
            else:
                lines.append(f'  {err.format_li()}')
        return '\n'.join(lines)

    def format_li(self) -> str:
        """Compose an error message to appear in a standard error list.

        Default implementation uses builtin formatter.
        """
        return linter_format_li(self)

    def format_verbose(self) -> str:
        """Compose verbose error message.

        Default implementation falls back to list item format ``format_li``.
        Linter bound to a location in a file should output part of the file.
        """
        return self.format_li()

    def sort_key(self) -> tuple[str, ...]:
        """Generate a sort key for this violation."""
        return (type(self).rule,)


class LinterViolationMessage(LinterViolation, ABC):
    """Mixin: violation gets a short message at the end."""

    @property
    @abstractmethod
    def message(self) -> str:
        """Get linter violation message."""


class LinterViolationFile(LinterViolation, ABC):
    """Mixin: Linter violation is bound to a file."""

    @property
    @abstractmethod
    def file(self) -> Path:
        """Get a file for this linter violation."""

    @override
    def sort_key(self) -> tuple[str, ...]:
        """Generate a sort key for this violation.

        This one adds file path.
        """
        return (
            type(self).rule,
            project.rel(self.file),
        )


class LinterViolationAsset(LinterViolation, ABC):
    """Mixin: Linter violation is bound to an asset."""

    @property
    @abstractmethod
    def asset(self) -> Asset:
        """Get an asset for this linter violation."""

    def format_asset(self) -> str:
        """Format asset repr for this violation."""
        asset = self.asset
        if isinstance(asset, AssetHasPath):
            return '/'.join(
                (type(asset).type_name(), *asset.tree_path, asset.name)
            )
        return '/'.join((type(asset).type_name(), asset.name))

    @override
    def sort_key(self) -> tuple[str, ...]:
        """Generate a sort key for this violation.

        This one adds asset name (or path).
        """
        return type(self).rule, self.format_asset()


class LinterViolationLocated(LinterViolationFile, ABC):
    """Mixin: Linter violation is bound to a location in a text file."""

    @property
    @abstractmethod
    def location(self) -> Location:
        """Get linter violation location."""

    @override
    @property
    def file(self) -> Path:
        """Get a file for this linter violation."""
        return self.location.file

    @override
    def format_verbose(self) -> str:
        """Compose verbose error message.

        Adds few lines of the source file to the output.
        """
        loc = self.location
        lines = tuple(enumerate(project.lines(loc.file), start=1))
        lines_slice = lines[
            max(0, loc.loc_line - 3) : min(len(lines), loc.loc_line + 3)
        ]
        output_lines: list[str] = [self.format_li()]

        for num, line in lines_slice:
            output_lines.append(f'{num:>3}|{line}')
            if num == loc.loc_line:
                output_lines.append('   ' + ' ' * (loc.loc_column - 1) + '^')
        return '\n'.join(output_lines)

    @override
    def sort_key(self) -> tuple[str, ...]:
        """Generate a sort key for this violation.

        This one adds location data, or asset path, if such is present.
        """
        key = [
            type(self).rule,
            project.rel(self.location.file),
            f'{self.location.loc_line:0>4}',
            f'{self.location.loc_column:0>4}',
        ]
        if isinstance(self, LinterViolationAsset):
            key.insert(1, self.format_asset())
        return tuple(key)


def linter_format_li(violation: LinterViolation) -> str:
    """Formats linter list item representation, accounting for subclasses."""
    parts: list[str] = []
    if isinstance(violation, LinterViolationFile):
        v_file: Path = violation.file
        fmt_path = project.rel(v_file)
        parts.append(f' {fmt_path or "???"}')
        if isinstance(violation, LinterViolationLocated):
            v_line_col: tuple[int, int] = (
                violation.location.loc_line,
                violation.location.loc_column,
            )
            parts.append(f':{v_line_col[0]}:{v_line_col[1]}')

    if isinstance(violation, LinterViolationAsset):
        fmt_asset = violation.format_asset()
        if fmt_asset:
            parts.append(f' ({violation.format_asset()})')
    if isinstance(violation, LinterViolationMessage):
        message = violation.message
        if message:
            parts.append(f' - {violation.message}')
    return ''.join(parts)


@dataclass(frozen=True, slots=True)
class DiagnosticBatch:
    """Internal collected diagnostic batch."""

    infos: tuple[LinterViolation, ...]
    warnings: tuple[LinterViolation, ...]
    errors: tuple[LinterViolation, ...]

    def len_total(self) -> int:
        """Total length of the diagnostic batch."""
        return len(self.infos) + len(self.warnings) + len(self.errors)


class DiagnosticConsumer(ABC):
    """Abstract diagnostic consumer."""

    @abstractmethod
    def consume(
        self, batch: DiagnosticBatch, *, verbose: bool = False
    ) -> None:
        """Consume a diagnostic batch."""


class LinterFoundError(RuntimeError):
    """Raisable linter error."""

    def __init__(
        self, message: str, errors: col.Iterable[LinterViolation]
    ) -> None:
        """Initialize ``LinterFoundError`` with violations found."""
        super().__init__(message)
        self.errors = tuple(errors)


class CliConsumer(DiagnosticConsumer):
    """Simple diagnostic consumer.

    Prints infos, warns warnings and raises errors.
    """

    @override
    def consume(
        self, batch: DiagnosticBatch, *, verbose: bool = False
    ) -> None:
        if batch.infos:
            print(err_format(batch.infos, verbose=verbose))
        if batch.warnings:
            warnings.warn(
                '\n' + err_format(batch.warnings, verbose=verbose),
                stacklevel=1,
            )
        if batch.errors:
            raise LinterFoundError(
                '\n' + err_format(batch.errors, verbose=verbose), batch.errors
            )


class LinterSession:
    """Linter session."""

    def __init__(self, consumer: DiagnosticConsumer | None = None) -> None:
        """Initialize linter session.

        :param consumer: Consumer for found violations. Defaults to simple
          ``CliConsumer``.
        """
        self.consumer: DiagnosticConsumer = (
            consumer if consumer is not None else CliConsumer()
        )
        self.errors: list[LinterViolation] = []

    def push(self, error: LinterViolation) -> None:
        """Enqueue a violation."""
        self.errors.append(error)

    def collect(
        self, *cl: type[LinterViolation], flush: bool = True
    ) -> DiagnosticBatch:
        """Collect errors into a diagnostic batch.

        :param cl: Classes to filter against. Pass nothing to collect
          everything.
        :param flush: Whether to remove collected errors.
        :return: Diagnostic batch.
        """
        err_severities = self._classify(*cl)
        if flush:
            self._flush(it.chain.from_iterable(err_severities.values()))
        return DiagnosticBatch(
            infos=tuple(err_severities.get(Severity.INFO, [])),
            warnings=tuple(err_severities.get(Severity.WARNING, [])),
            errors=tuple(err_severities.get(Severity.ERROR, [])),
        )

    def consume(
        self,
        *cl: type[LinterViolation],
        verbose: bool = False,
        flush: bool = True,
    ) -> int:
        """Collect and consume errors.

        :param cl: Classes to filter against. Pass nothing to collect
          everything.
        :param verbose: Whether to produce verbose report.
        :param flush: Whether to remove collected errors.
        :return: Number of errors collected.
        """
        batch = self.collect(*cl, flush=flush)
        self.consumer.consume(batch, verbose=verbose)
        return batch.len_total()

    def flush(self, *cl: type[LinterViolation]) -> int:
        """Remove errors from queue.

        :param cl: Classes to filter against. Pass nothing to collect
          everything.
        :return: Number of elements removed.
        """
        err_severities = self._classify(*cl)
        return self._flush(it.chain.from_iterable(err_severities.values()))

    def _flush(self, errors: col.Iterable[LinterViolation]) -> int:
        """Remove errors from queue.

        :param errors: Errors to remove.
        :return: Number of elements removed.
        """
        remove = {id(err) for err in errors}
        self.errors[:] = [err for err in self.errors if id(err) not in remove]
        return len(remove)

    def _classify(
        self, *cl: type[LinterViolation]
    ) -> dict[Severity, list[LinterViolation]]:
        """Filter violations by severity.

        :param cl: Classes to filter against. Pass nothing to collect
          everything.
        :return: Dictionary of severities by classes.
        """
        err_severities: dict[Severity, list[LinterViolation]] = {}
        for err in self.errors:
            if cl and not isinstance(err, cl):
                continue
            err_severities.setdefault(type(err).severity, []).append(err)

        return err_severities

    def assert_empty(self) -> None:
        """Assert no errors remaining the in the queue."""
        if self.errors:
            raise LinterFoundError(
                message=f'Expected no errors in queue, found: {self.errors}',
                errors=self.errors,
            )


def err_format(
    errors: col.Iterable[LinterViolation], *, verbose: bool = False
) -> str:
    """Turn errors into messages.

    :param errors: Errors to turn into messages.
    :param verbose: Whether to use verbose output.
    :return: Composed text.
    """
    grouped: dict[str, dict[type[LinterViolation], list[LinterViolation]]] = {}
    for err in errors:
        grouped.setdefault(type(err).rule, {}).setdefault(
            type(err), []
        ).append(err)
    for cls_grouped in grouped.values():
        for cls, violations in cls_grouped.items():
            violations.sort(key=cls.sort_key)

    return '\n\n'.join(
        cls.format_many(violations, verbose=verbose)
        for rule, cls_grouped in grouped.items()
        for cls, violations in cls_grouped.items()
    )
