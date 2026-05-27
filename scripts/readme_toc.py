"""Generate table of contents out of md headings."""

import re
from pathlib import Path

import cog  # ty: ignore[unresolved-import]


def generate_toc(filepath: str = 'README.md') -> None:
    """Generate table of contents out of md headings.

    :param filepath: File to read headings from.
    """
    with Path(filepath).open(encoding='utf-8') as f:
        lines = f.readlines()

    in_code_block = False
    toc_lines = []

    for line in lines:
        stripped_line = line.strip()

        # toggle code block state to avoid matching python comments
        if stripped_line.startswith('```'):
            in_code_block = not in_code_block
            continue

        if in_code_block:
            continue

        # match md headings
        match = re.match(r'^(#{1,4})\s+(.+)$', stripped_line)
        if match:
            level_chars = match.group(1)
            title = match.group(2)

            # bruuuuuh
            if title.lower() == 'toc':
                continue

            level = len(level_chars)
            indent = '  ' * (level - 1)

            # compatible anchor (please work)
            anchor = title.lower()
            anchor = re.sub(r'[^\w\-\s]', '', anchor)
            anchor = re.sub(r'\s+', '-', anchor)
            toc_lines.append(f'{indent}* [{title}](#{anchor})')

    # output to Cog
    for toc_line in toc_lines:
        cog.outl(toc_line)
