"""Generate table of contents out of md headings."""

import collections.abc as col
import re
from pathlib import Path


def str_to_anchor(text: str) -> str:
    """Convert string to Markdown anchor.

    :param text: Text to convert.
    :return: Safe anchor.
    """
    return re.sub(r'\s+', '-', re.sub(r'[^\w\-\s]', '', text.lower()))


def generate_toc(filepath: str = 'README.md') -> col.Iterator[str]:
    """Generate table of contents out of md headings.

    :param filepath: File to read headings from.
    """
    with Path(filepath).open(encoding='utf-8') as f:
        lines = f.readlines()

    in_code_block = False
    in_cog_block = False

    for line in lines:
        stripped_line = line.strip()

        # toggle code block state to avoid matching python comments
        if stripped_line.startswith('```'):
            in_code_block = not in_code_block
            continue

        if stripped_line.startswith('<!--[[[cog'):
            in_cog_block = True
        if stripped_line == ']]]-->':
            in_cog_block = False
            continue
        if in_cog_block:
            continue

        if in_code_block:
            continue

        # match md headings
        match = re.match(r'^(#{1,4})\s+(.+)$', stripped_line)
        if match:
            level_chars = match.group(1)
            title = match.group(2)

            # bruuuuuh
            if title.lower() in ['toc', 'clunkster']:
                continue

            level = len(level_chars)
            indent = '  ' * (level - 1)

            # compatible anchor (please work)
            anchor = title.lower()
            anchor = re.sub(r'[^\w\-\s]', '', anchor)
            anchor = re.sub(r'\s+', '-', anchor)
            yield f'{indent}* [{title}](#{anchor})'
