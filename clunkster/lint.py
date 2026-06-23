"""Linter-related shims."""

from clunkster.text.location import Location
from clunkster.asset import AssetHasPath, Asset
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

    def format_path(self, path: Path) -> str:
        """Format given path."""
        if self.session is None:
            return str(path)
        return self.session.path_try_rel(path)

    @classmethod
    def format_many(cls: type[TError], errors: col.Iterable[TError], *, verbose: bool = False) -> str:
        """Compose an error message from a block of linter errors.

        Default implementation uses ``<file>:<line>:<column>: <err>`` format.
        """
        errors = tuple(errors)
        if not errors:
            return f"=== {cls.rule}: no issues"

        lines = [f"=== {cls.rule}({cls.__name__}): {len(errors)} " + {
            Severity.INFO: "note(s)",
            Severity.WARNING: "warning(s)!",
            Severity.ERROR: "ERROR(S)!!!",
        }[cls.severity]]
        for err in errors:
            if verbose:
                lines.append(err.format_verbose())
            else:
                lines.append(f"  {err.format_li()}")
        return "\n".join(lines)

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
    @property
    @abstractmethod
    def message(self) -> str:
        """Get linter violation message."""

class LinterViolationFile(LinterViolation, ABC):
    """Linter violation bound to a file."""

    @property
    @abstractmethod
    def file(self) -> Path:
        """Get a file for this linter violation."""

    @override
    def sort_key(self) -> tuple[str, ...]:
        """Generate a sort key for this violation.

        This one adds file path.
        """
        return type(self).rule, self.format_path(self.file),

class LinterViolationAsset(LinterViolation, ABC):
    """Linter violation bound to an asset."""

    @property
    @abstractmethod
    def asset(self) -> Asset:
        """Get an asset for this linter violation."""

    def format_asset(self) -> str:
        asset = self.asset
        if isinstance(asset, AssetHasPath):
            return '/'.join((
                type(asset).type_name(),
                *asset.tree_path,
                asset.name
            ))
        else:
            return '/'.join((
                type(asset).type_name(),
                asset.name
            ))

    @override
    def sort_key(self) -> tuple[str, ...]:
        """Generate a sort key for this violation.

        This one adds asset name (or path).
        """
        return type(self).rule, self.format_asset()


class LinterViolationLocated(LinterViolationFile, ABC):
    """Linter violation bound to a location in a text file."""

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
        lines = tuple(enumerate(read.lines(loc.file), start=1))
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

        This one adds location data, or asset path, if such is present.
        """

        key = [type(self).rule, self.format_path(self.location.file), f"{self.location.loc_line:0>4}", f"{self.location.loc_column:0>4}",]
        if isinstance(self, LinterViolationAsset):
            key.insert(1, self.format_asset())
        return tuple(key)


def linter_format_li(violation: LinterViolation) -> str:
    """Formats linter list item representation, accounting for subclasses."""

    parts: list[str] = []
    if isinstance(violation, LinterViolationFile):
        v_file: Path = violation.file
        fmt_path = violation.format_path(v_file)
        parts.append(f" {fmt_path if fmt_path else '???'}")
        if isinstance(violation, LinterViolationLocated):
            v_line_col: tuple[int, int] = (violation.location.loc_line, violation.location.loc_column)
            parts.append(f":{v_line_col[0]}:{v_line_col[1]}")

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
    infos: tuple[LinterViolation, ...]
    warnings: tuple[LinterViolation, ...]
    errors: tuple[LinterViolation, ...]

    def len_total(self) -> int:
        return len(self.infos) + len(self.warnings) + len(self.errors)


class DiagnosticConsumer(ABC):
    @abstractmethod
    def consume(self, batch: DiagnosticBatch, *, verbose: bool = False) -> None:
        """Consume a diagnostic batch."""


class LinterFoundErrors(RuntimeError):
    def __init__(self, message: str, errors: col.Iterable[LinterViolation]):
        super().__init__(message)
        self.errors = tuple(errors)


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

    def consume(self, *cls: type[LinterViolation], verbose: bool = False, flush: bool = True) -> int:
        batch = self.collect(*cls, flush=flush)
        self.consumer.consume(batch, verbose=verbose)
        return batch.len_total()

    def flush(self, *cls: type[LinterViolation]) -> bool:
        err_severities = self._classify(*cls)
        return self._flush(it.chain.from_iterable(err_severities.values()))

    def _flush(self, errors: col.Iterable[LinterViolation]) -> bool:
        remove = {id(err) for err in errors}
        self.errors[:] = [
            err
            for err in self.errors
            if id(err) not in remove
        ]
        return bool(remove)

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
