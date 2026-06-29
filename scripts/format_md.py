"""Apply mdformat to README.md."""

from pathlib import Path

import mdformat

FILE_README = Path(__file__).parent.parent / 'README.md'

UNDERSCORE_70 = '_' * 70


def _main() -> None:
    readme_txt = FILE_README.read_text(encoding='utf-8')
    formatted = mdformat.text(
        readme_txt,
        options={
            'wrap': 'no',
            'number': True,
            'end_of_line': 'lf',
            'validate': True,
        },
        codeformatters=('python',),
        extensions=(
            'gfm',
            'tables',
        ),
    )

    formatted = formatted.replace(UNDERSCORE_70, '___')

    FILE_README.write_text(formatted, encoding='utf-8')
    print('Readme formatted.')


if __name__ == '__main__':
    _main()
