"""Compile parsed DOM into useful data."""

import re

from scripts.doc_parse import NodeTag, NodeText
from scripts.doc_snippets import Snippet, s_md, s_py

RX_MD_LINE = re.compile(r'^\s*# ?(.*)')


def _process_md(child: NodeTag) -> Snippet | None:
    if any(isinstance(c, NodeTag) for c in child.children):
        raise ValueError('Encountered nested tags inside md tag.')
    if len(child.children) != 1:
        raise ValueError(
            'Encountered either empty md tag or malformed md tag with '
            'multiple text nodes.'
        )

    md_text_node = child.children[0]
    assert isinstance(md_text_node, NodeText)

    raw_text = '\n'.join(md_text_node.content).strip('\n')
    if not raw_text.strip():
        return None

    cleaned_lines = []
    for line in raw_text.splitlines():
        if not line.strip():
            cleaned_lines.append('')
            continue
        match = RX_MD_LINE.match(line)
        if match:
            cleaned_lines.append(match.group(1))
        else:
            cleaned_lines.append(line)

    return s_md('\n'.join(cleaned_lines))


def _flush_buffer(py_buffer: list[str], snips: list[Snippet]) -> None:
    if py_buffer:
        merged = '\n'.join(py_buffer).strip('\n')
        if merged:
            snips.append(s_py(merged))
        py_buffer.clear()


def extract(root: NodeTag) -> dict[str, list[Snippet]]:
    """Extract snippets from given document.

    :param root: Document to extract snippets from.
    :return: Snippet name to snippet contents.
    """
    snippets: dict[str, list[Snippet]] = {}

    # top level pass
    snip_name_to_node: dict[str, NodeTag] = {}
    for node in root.children:
        if isinstance(node, NodeText):
            continue

        if node.tag_name != 'snip' or len(node.args) != 1:
            raise ValueError('Top level tags must be <snip NAME>')

        name = node.args[0]
        if name in snip_name_to_node:
            raise ValueError(f'Duplicate top-level snippet name: {name}')
        snip_name_to_node[name] = node

    # extract pass
    for name, node in snip_name_to_node.items():  # ruff: ignore[too-many-nested-blocks]
        outer_snips: list[Snippet] = []
        outer_py_buffer: list[str] = []

        for child in node.children:
            # outer text
            if isinstance(child, NodeText):
                raw_text = '\n'.join(child.content).strip('\n')
                if raw_text.strip():
                    outer_py_buffer.append(raw_text)
                continue

            # outer md
            if child.tag_name == 'md':
                _flush_buffer(outer_py_buffer, outer_snips)
                md_snippet = _process_md(child)
                if md_snippet:
                    outer_snips.append(md_snippet)
                continue

            # inner snippet
            if child.tag_name == 'snip':
                if len(child.args) != 1:
                    raise ValueError('Snip tags must be <snip NAME>')

                inner_name = child.args[0]
                if inner_name in snippets or inner_name in snip_name_to_node:
                    raise ValueError(
                        f'Duplicate inner snippet name: {inner_name}'
                    )

                inner_snips: list[Snippet] = []
                inner_py_buffer: list[str] = []

                for inner_child in child.children:
                    if isinstance(inner_child, NodeText):
                        raw_text = '\n'.join(inner_child.content).strip('\n')
                        if raw_text.strip():
                            # python text goes both to inner and outer scopes
                            inner_py_buffer.append(raw_text)
                            outer_py_buffer.append(raw_text)

                    elif inner_child.tag_name == 'md':
                        _flush_buffer(inner_py_buffer, inner_snips)
                        md_snippet = _process_md(inner_child)
                        if md_snippet:
                            inner_snips.append(md_snippet)
                        # outer scope doesn't receive md

                    elif inner_child.tag_name == 'snip':
                        raise ValueError(
                            f'Depth limit exceeded in {inner_name}: Snippets '
                            f'can only be nested 1 level deep.'
                        )
                    else:
                        raise NotImplementedError(
                            f'Tag <{inner_child.tag_name}> not implemented.'
                        )

                # save inner snippet
                _flush_buffer(inner_py_buffer, inner_snips)
                snippets[inner_name] = inner_snips

            else:
                raise NotImplementedError(
                    f'Tag <{child.tag_name}> not implemented.'
                )

        # save outer snippet
        _flush_buffer(outer_py_buffer, outer_snips)
        snippets[name] = outer_snips

    return snippets
