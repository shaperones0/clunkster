"""Compile parsed DOM into useful data."""

import re
from scripts.doc_parse import NodeTag, NodeText
from scripts.doc_snippets import Snippet, SnippetType, s_md, s_py


def extract(root: NodeTag) -> dict[str, list[Snippet]]:
    snippets: dict[str, list[Snippet]] = {}
    rx_md_line = re.compile(r'^\s*# ?(.*)')

    snip_name_to_node: dict[str, NodeTag] = {}
    for node in root.children:
        # not in a snippet yet
        if isinstance(node, NodeText):
            # ok
            continue

        if node.tag_name != 'snip' or len(node.args) != 1:
            raise ValueError("Top level tags must be <snip NAME>")
        if node.args[0] in snip_name_to_node:
            raise ValueError("Duplicate snippet name")
        snip_name_to_node[node.args[0]] = node
    for name, node in snip_name_to_node.items():
        snips: list[Snippet] = []
        for child in node.children:
            if isinstance(child, NodeText):
                # add code smartly
                raw_text = "\n".join(child.content).strip("\n")
                if raw_text.strip():
                    snips.append(s_py(raw_text))
                continue

            if child.tag_name == 'snip':
                raise ValueError("Nested snippets are not allowed")
            if child.tag_name != 'md':
                raise NotImplementedError()

            # get text nodes inside this md
            if any(isinstance(c, NodeTag) for c in child.children):
                raise ValueError("Encountered tags inside md tag")
            if len(child.children) != 1:
                raise ValueError("Encountered either empty md tag or malformed md tag with multiple text nodes")
            md_text_node = child.children[0]
            assert isinstance(md_text_node, NodeText)
            raw_text = "\n".join(md_text_node.content).strip("\n")
            if not raw_text.strip():
                continue

            # clean lines
            cleaned_lines = []
            for line in raw_text.splitlines():
                if not line.strip():
                    cleaned_lines.append("")
                    continue
                match = rx_md_line.match(line)
                cleaned_lines.append(match.group(1) if match else line)
            snips.append(s_md("\n".join(cleaned_lines)))
        snippets[name] = snips
    return snippets
