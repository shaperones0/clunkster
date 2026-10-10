"""Unit tests for linter reports."""

from pathlib import Path

import pytest

from clunkster import asset as my_asset
from clunkster import lint as my_lint
from clunkster.project import Project
from clunkster.text.location import Location

RULE_E = my_lint.Rule('E100', 'some error', my_lint.Severity.ERROR)
RULE_W = my_lint.Rule('W100', 'some warning', my_lint.Severity.WARNING)


@pytest.fixture
def project(tmp_path: Path) -> Project:
    """Project with a single script."""
    (tmp_path / 'scripts').mkdir()
    (tmp_path / 'scripts' / 'a.gml').write_text('one\ntwo\nthree\n')
    return Project(tmp_path)


def loc(project: Project, line: int, column: int) -> Location:
    """Location in the project's script."""
    return Location(
        file=project.root / 'scripts' / 'a.gml',
        loc_line=line,
        loc_column=column,
        loc_index=0,
    )


def test_empty(project: Project) -> None:
    """No violations, no report."""
    assert not my_lint.format_report([], project)


def test_grouped_and_sorted(project: Project) -> None:
    """Report is grouped by rule and group, sorted by asset and location."""
    spr = my_asset.Sprite(name='sprA', tree_path=('Stage', 'Sub'))
    report = my_lint.format_report(
        [
            my_lint.Violation(RULE_W, 'w'),
            my_lint.Violation(
                RULE_E, 'late', location=loc(project, 3, 1), group='B'
            ),
            my_lint.Violation(
                RULE_E,
                'early',
                location=loc(project, 1, 2),
                asset=spr,
                group='B',
                details=('trace',),
            ),
            my_lint.Violation(RULE_E, asset=spr, group='A'),
        ],
        project,
    )
    assert report == (
        '=== E100 (some error): 3 ERROR(S)!!!\n'
        '\n--- A ---\n'
        '  SPRITE/Stage/Sub/sprA\n'
        '\n--- B ---\n'
        '  scripts/a.gml:3:1 - late\n'
        '  scripts/a.gml:1:2 (SPRITE/Stage/Sub/sprA) - early\n'
        '    trace\n'
        '\n'
        '=== W100 (some warning): 1 warning(s)!\n'
        '  w'
    )


def test_verbose_excerpt(project: Project) -> None:
    """Verbose report shows source with a column marker."""
    report = my_lint.format_report(
        [my_lint.Violation(RULE_E, 'x', location=loc(project, 2, 2))],
        project,
        verbose=True,
    )
    assert report.splitlines()[2:] == [
        '   1|one',
        '   2|two',
        '      ^',
        '   3|three',
    ]
