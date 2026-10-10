"""Linter primitives: rules, violations and their reports.

The library doesn't print or raise anything by itself; the pipeline
collects violations, formats them with ``format_report`` and decides what
to do with errors.
"""

import collections.abc as col
from dataclasses import dataclass
from enum import StrEnum

from clunkster.asset import Asset, AssetHasPath
from clunkster.project import Project
from clunkster.text.location import Location


class Severity(StrEnum):
    """Linter violation severity."""

    ERROR = 'error'
    WARNING = 'warning'
    INFO = 'info'


@dataclass(frozen=True, slots=True)
class Rule:
    """Linter rule."""

    # short rule id, like ``C100``
    code: str
    # human readable rule name
    title: str
    severity: Severity


@dataclass(frozen=True, slots=True)
class Violation:
    """Linter rule violation.

    Every field except ``rule`` is optional, the report shows those that
    are set.
    """

    rule: Rule
    message: str = ''
    # where in the source the violation is
    location: Location | None = None
    # which asset the violation belongs to
    asset: Asset | None = None
    # violations of the same rule are grouped by this (e.g. by cluster)
    group: str = ''
    # extra lines shown under the violation (e.g. traces)
    details: tuple[str, ...] = ()


class LinterFoundError(RuntimeError):
    """Raisable linter error."""

    def __init__(
        self, message: str, violations: col.Iterable[Violation]
    ) -> None:
        """Initialize ``LinterFoundError`` with violations found."""
        super().__init__(message)
        self.violations = tuple(violations)


def format_asset(asset: Asset) -> str:
    """Format asset as ``TYPE/tree/path/name``."""
    if isinstance(asset, AssetHasPath):
        return '/'.join((
            type(asset).type_name(),
            *asset.tree_path,
            asset.name,
        ))
    return '/'.join((type(asset).type_name(), asset.name))


def _asset_key(asset: Asset | None) -> tuple[str, ...]:
    if asset is None:
        return ()
    if isinstance(asset, AssetHasPath):
        return type(asset).type_name(), '/'.join(asset.tree_path), asset.name
    return type(asset).type_name(), asset.name


def _sort_key(
    violation: Violation, project: Project
) -> tuple[str, tuple[str, ...], str, int, int, str]:
    loc = violation.location
    return (
        violation.group,
        _asset_key(violation.asset),
        project.rel(loc.file) if loc else '',
        loc.loc_line if loc else 0,
        loc.loc_column if loc else 0,
        violation.message,
    )


def format_line(violation: Violation, project: Project) -> str:
    """Format violation as a single line.

    Uses ``<file>:<line>:<column> (<asset>) - <message>`` format, omitting
    parts that aren't set.
    """
    parts: list[str] = []
    loc = violation.location
    if loc is not None:
        parts.append(
            f'{project.rel(loc.file)}:{loc.loc_line}:{loc.loc_column}'
        )
    if violation.asset is not None:
        asset = format_asset(violation.asset)
        parts.append(f'({asset})' if parts else asset)
    if violation.message:
        parts.append(f'- {violation.message}' if parts else violation.message)
    return ' '.join(parts)


def format_excerpt(location: Location, project: Project) -> str:
    """Format a few source lines around the location, marking the column."""
    lines = project.lines(location.file)
    first = max(0, location.loc_line - 3)
    last = min(len(lines), location.loc_line + 3)
    output: list[str] = []
    for num in range(first + 1, last + 1):
        output.append(f'{num:>4}|{lines[num - 1]}')
        if num == location.loc_line:
            output.append('    ' + ' ' * location.loc_column + '^')
    return '\n'.join(output)


_SEVERITY_WORDS = {
    Severity.INFO: 'note(s)',
    Severity.WARNING: 'warning(s)!',
    Severity.ERROR: 'ERROR(S)!!!',
}


def format_report(
    violations: col.Iterable[Violation],
    project: Project,
    *,
    verbose: bool = False,
) -> str:
    """Format violations into a report.

    Violations are grouped by rule, then by their ``group``, and sorted by
    asset and location.

    :param violations: Violations to report.
    :param project: Linted project, used for formatting paths.
    :param verbose: Whether to include source excerpts.
    :return: Report text, empty if there are no violations.
    """
    by_rule: dict[Rule, list[Violation]] = {}
    for violation in violations:
        by_rule.setdefault(violation.rule, []).append(violation)

    blocks: list[str] = []
    for rule, rule_violations in sorted(
        by_rule.items(), key=lambda item: item[0].code
    ):
        rule_violations.sort(key=lambda v: _sort_key(v, project))
        count = f'{len(rule_violations)} {_SEVERITY_WORDS[rule.severity]}'
        lines = [f'=== {rule.code} ({rule.title}): {count}']
        group: str | None = None
        for violation in rule_violations:
            if violation.group and violation.group != group:
                lines.append(f'\n--- {violation.group} ---')
            group = violation.group
            lines.append(f'  {format_line(violation, project)}')
            lines.extend(f'    {detail}' for detail in violation.details)
            if verbose and violation.location is not None:
                lines.append(format_excerpt(violation.location, project))
        blocks.append('\n'.join(lines))
    return '\n\n'.join(blocks)
