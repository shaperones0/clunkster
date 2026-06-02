"""Find function's docstring and convert it from RST to MD."""

import ast
import re
from pathlib import Path


def _format_docstring(docstring: str) -> str:
    """Format give docstring from RST to MD."""
    # rst2md: ``code`` -> `code`
    docstring = re.sub(r'``([^`]+)``', r'`\1`', docstring)
    # rst2md: :class:`MyClass` -> `MyClass`
    return re.sub(r':[a-zA-Z0-9_-]+:`([^`]+)`', r'`\1`', docstring)


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
