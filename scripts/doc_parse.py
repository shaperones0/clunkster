"""Parse XML from Python comments."""

import re
from dataclasses import dataclass, field
import collections.abc as col

@dataclass
class NodeText:
    content: list[str] = field(default_factory=list)

@dataclass
class NodeTag:
    tag_name: str
    args: list[str] = field(default_factory=list)
    kwargs: dict[str, str] = field(default_factory=dict)
    children: list[NodeTag | NodeText] = field(default_factory=list)


def parse(lines: col.Iterable[str]) -> NodeTag:
    root = NodeTag(tag_name='root')
    stack: list[NodeTag] = []

    rx_open_tag = re.compile(r'^\s*#\s*<([A-Za-z0-9_\-]+)(.*?)>\s*$')
    rx_close_tag = re.compile(r'^\s*#\s*</([A-Za-z0-9_\-]+)>\s*$')

    # key="value" or positional_arg
    rx_tokens = re.compile(r'([a-zA-Z0-9_\-]+)="([^"]*)"|([a-zA-Z0-9_\-]+)')

    for line in lines:
        close_match = rx_close_tag.match(line)
        if close_match:
            tag_name = close_match.group(1)
            if stack[-1].tag_name != tag_name:
                raise ValueError(f"Mismatched closing tag: </{tag_name}>. Expected </{stack[-1].tag_name}>")
            stack.pop()
            continue

        open_match = rx_open_tag.match(line)
        if open_match:
            tag_name = open_match.group(1)
            attr_string = open_match.group(2)

            args = []
            attrs = {}

            for match in rx_tokens.finditer(attr_string):
                key, val, pos_arg = match.groups()
                if pos_arg:
                    args.append(pos_arg)
                elif key:
                    attrs[key] = val

            new_node = NodeTag(tag_name=tag_name, args=args, kwargs=attrs)
            stack[-1].children.append(new_node)
            stack.append(new_node)
            continue

        current_node = stack[-1]
        if not current_node.children or isinstance(current_node.children[-1], NodeTag):
            current_node.children.append(NodeText())

        current_node.children[-1].content.append(line)

    if len(stack) > 1:
        raise ValueError(f"Unclosed tags remaining: {[n.tag_name for n in stack[1:]]}")

    return root

