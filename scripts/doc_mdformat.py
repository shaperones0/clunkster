"""Apply mdformat to README.md."""

from pathlib import Path

import mdformat

FILE_README = Path(__file__).parent.parent / 'README.md'

UNDERSCORE_70 = '_' * 70


def format_text(txt: str) -> str:
    """Format markdown text."""
    formatted = mdformat.text(
        txt,
        options={
            'wrap': 'no',
            'number': True,
            'end_of_line': 'lf',
            'validate': True,
        },
        extensions=(
            'gfm',
            'tables',
            'admon',
        ),
    )

    return formatted.replace(UNDERSCORE_70, '___')
