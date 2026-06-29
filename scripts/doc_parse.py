"""Parse XML from Python comments."""

import collections.abc as col
import re
import textwrap
from dataclasses import dataclass, field


@dataclass
class NodeText:
    """XML text node."""

    content: list[str] = field(default_factory=list)


@dataclass
class NodeTag:
    """XML tag node."""

    tag_name: str
    args: list[str] = field(default_factory=list)
    kwargs: dict[str, str] = field(default_factory=dict)
    children: list[NodeTag | NodeText] = field(default_factory=list)


def parse(lines: col.Iterable[str]) -> NodeTag:  # noqa: C901, PLR0915
    """Parse XML from Python comments."""
    root = NodeTag(tag_name='root')
    stack: list[NodeTag] = [root]
    all_texts: list[NodeText] = []

    rx_initial_tag = re.compile(
        r'^(.*?)(#\s*<(/?)([A-Za-z0-9_\-]+)([^>]*)>)(.*)$'
    )
    rx_subsequent_tag = re.compile(
        r'^(.*?)<(/?)([A-Za-z0-9_\-]+)([^>]*)>(.*)$'
    )
    rx_tokens = re.compile(r'([a-zA-Z0-9_\-]+)="([^"]*)"|([a-zA-Z0-9_\-]+)')

    def _append_text(text: str) -> None:

        current = stack[-1]
        last_text_node = NodeText()

        is_last_text = False
        if current.children:
            last = current.children[-1]
            if isinstance(last, NodeText):
                is_last_text = True
                last_text_node = last

        if not is_last_text:
            all_texts.append(last_text_node)
            current.children.append(last_text_node)

        last_text_node.content.append(text)

    def _process_tag(is_closing: str, tag_name: str, attr_str: str) -> None:
        # 1. Parse tokens exactly as we do for opening tags
        args, attrs = [], {}
        for match in rx_tokens.finditer(attr_str):
            key, val, pos_arg = match.groups()
            if pos_arg:
                args.append(pos_arg)
            elif key:
                attrs[key] = val

        if is_closing == '/':
            current_node = stack[-1]
            if current_node.tag_name == tag_name:
                # additional validation
                if args and args != current_node.args:
                    raise ValueError(
                        f'Closing tag </{tag_name}> args {args} '
                        f'do not match opening tag args {current_node.args}'
                    )

                if attrs and attrs != current_node.kwargs:
                    raise ValueError(
                        f'Closing tag </{tag_name}> kwargs {attrs} '
                        f'do not match opening tag kwargs '
                        f'{current_node.kwargs}'
                    )

                stack.pop()
            else:
                raise ValueError(
                    f'Mismatched closing tag: </{tag_name}>. Expected '
                    f'</{current_node.tag_name}>'
                )
        else:
            new_node = NodeTag(tag_name=tag_name, args=args, kwargs=attrs)
            stack[-1].children.append(new_node)
            stack.append(new_node)

    for line in lines:
        match = rx_initial_tag.match(line)
        if not match:
            _append_text(line)
            continue

        prefix, _, is_closing, tag_name, attr_str, remainder = match.groups()

        if prefix.strip():
            _append_text(prefix)

        _process_tag(is_closing, tag_name, attr_str)

        if remainder.strip():
            remainder = '# ' + remainder.lstrip()

        while remainder:
            sub_match = rx_subsequent_tag.match(remainder)
            if not sub_match:
                _append_text(remainder)
                break

            text_before, is_closing, tag_name, attr_str, remainder = (
                sub_match.groups()
            )

            if text_before.strip():
                _append_text(text_before)

            _process_tag(is_closing, tag_name, attr_str)

    if len(stack) > 1:
        raise ValueError(
            f'Unclosed tags remaining: {[n.tag_name for n in stack[1:]]}'
        )

    # dedent texts
    for node_text in all_texts:
        txt = '\n'.join(node_text.content)
        node_text.content = textwrap.dedent(txt).splitlines()

    return root
