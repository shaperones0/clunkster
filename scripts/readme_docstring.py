"""Find function's docstring and convert it from RST to MD."""

import ast
import re
from pathlib import Path


def _format_docstring(docstring: str) -> str:  # noqa: C901, PLR0915
    """Format given docstring from RST to MD.

    :param docstring: Input RST docstring.
    :return: Output Markdown.
    """
    # inlines
    docstring = re.sub(r'``([^`]+)``', r'`\1`', docstring)
    docstring = re.sub(r':[a-zA-Z0-9_-]+:`([^`]+)`', r'`\1`', docstring)

    lines = docstring.splitlines()
    out_lines: list[str] = []

    in_code_block = False
    code_indent = 0
    code_lang = ''
    code_buffer: list[str] = []

    # blocks
    rx_directive = re.compile(r'^\s*\.\.\s+(code-block|code)::\s*(\w+)?\s*$')
    rx_colon = re.compile(r'(.*?)::$')

    fence = chr(96) * 3

    def flush_code_block() -> None:
        """Helper to trim empty lines and write the buffer to out_lines."""
        while code_buffer and not code_buffer[0].strip():
            code_buffer.pop(0)
        while code_buffer and not code_buffer[-1].strip():
            code_buffer.pop()

        out_lines.append(f'{fence}{code_lang}')
        out_lines.extend(code_buffer)
        out_lines.append(fence)

    i = 0
    while i < len(lines):
        line = lines[i]

        if in_code_block:
            stripped = line.lstrip()

            # buffer blank lines, don't use to measure indent
            if not stripped:
                code_buffer.append(line)
                i += 1
                continue

            current_indent = len(line) - len(stripped)

            if code_indent == 0:
                code_indent = current_indent

            # if indent >= base level, we are in the block
            if current_indent >= code_indent:
                # dedent the code block
                code_buffer.append(line[code_indent:])
                i += 1
                continue
            # indentation broke, close the code fence
            flush_code_block()
            in_code_block = False
            code_indent = 0
            code_buffer.clear()
            code_lang = ''
            # re-evaluate this line as standard Markdown
            continue

        # check PyCharm code block
        directive_match = rx_directive.match(line)
        if directive_match:
            code_lang = directive_match.group(2) or ''
            in_code_block = True
            i += 1
            continue

        # check classic RST double colon
        colon_match = rx_colon.match(line)
        if colon_match:
            prefix = colon_match.group(1)
            # If the line was "Some text::", turn it into "Some text:"
            if prefix.strip():
                out_lines.append(prefix + ':')
            code_lang = ''
            in_code_block = True
            i += 1
            continue

        out_lines.append(line)
        i += 1

    if in_code_block:
        flush_code_block()

    return '\n'.join(out_lines)


class DocstringExtractor(ast.NodeVisitor):
    """Extract functions docstrings from given Python code."""

    def __init__(self) -> None:
        """Extract functions docstrings from given Python code."""
        self.func_to_docstring: dict[str, str] = {}

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Visit FunctionDef node."""
        docstring = ast.get_docstring(node)
        if docstring:
            self.func_to_docstring[node.name] = _format_docstring(docstring)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """Visit AsyncFunctionDef node."""
        docstring = ast.get_docstring(node)
        if docstring:
            self.func_to_docstring[node.name] = _format_docstring(docstring)


def extract(code: str) -> dict[str, str]:
    """Extract all docstrings from given Python code.

    :param code: Python code to extract docstrings from.
    :return: Mapping of functions name -> formatted docstring.
    """
    extractor = DocstringExtractor()
    extractor.visit(ast.parse(code))
    return extractor.func_to_docstring


def extract_file(file_path: str) -> dict[str, str]:
    """Extract docstrings from given Python file.

    :param file_path: Python file path.
    :return: Mapping of functions name -> formatted docstring.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Source file '{file_path}' not found.")
    return extract(path.read_text(encoding='utf-8'))
