"""Parse imports and filter to only include used ones."""

import ast
from pathlib import Path
from typing import Self

ImportNode = ast.Import | ast.ImportFrom


def _imported_name(alias: ast.alias) -> str:
    """Get the local namespace identifier for an imported alias."""
    if alias.asname:
        return alias.asname
    # for example in 'import os.path' the local name used in code is 'os'
    return alias.name.split('.')[0]


def _snippet_used_names(code: str) -> set[str]:
    """Find used names in given Python code."""
    used_names = set()
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        raise SyntaxError(
            f'Snippet contains invalid syntax, cannot parse AST: {e}'
        ) from e

    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            used_names.add(node.id)

    return used_names


def _nodes_unparse(nodes: list[ast.stmt]) -> str:
    """Turn given nodes into correct Python syntax.

    :param nodes: Code's nodes.
    :return: Python code.
    """
    if not nodes:
        return ''
    filtered_module = ast.Module(body=nodes, type_ignores=[])
    return ast.unparse(filtered_module)


class ImportsFilter:
    """Filter imports."""

    def __init__(self, import_nodes: list[ImportNode]) -> None:
        """Initialize filter.

        Use from_code and from_file_path constructors preferably.
        :param import_nodes: Master import nodes.
        """
        self.import_nodes = import_nodes

    @classmethod
    def from_code(cls, code: str) -> Self:
        """Initialize filter from given code.

        :param code: Code to parse.
        """
        return cls(
            [
                node
                for node in ast.parse(code).body
                if isinstance(node, (ast.ImportFrom, ast.Import))
            ]
        )

    @classmethod
    def from_file_path(cls, file_path: str) -> Self:
        """Initialize filter from given file path.

        :param file_path: Path of file to parse.
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Source file '{file_path}' not found.")
        return cls.from_code(path.read_text(encoding='utf-8'))

    def filter_used(self, *snippets: str) -> list[ImportNode]:
        """Filter import nodes to only include ones used in the snippet.

        :param snippets: Snippets to look for used imports in.
        :return: Filtered nodes.
        """
        names: set[str] = set()
        for snippet in snippets:
            names.update(_snippet_used_names(snippet))
        kept_nodes: list[ImportNode] = []
        for node in self.import_nodes:
            kept_aliases = [
                a for a in node.names if _imported_name(a) in names
            ]
            if not kept_aliases:
                continue

            if isinstance(node, ast.Import):
                # keep the alias if its local name is referenced in the snippet
                kept_nodes.append(ast.Import(names=kept_aliases))
            elif isinstance(node, ast.ImportFrom):
                # reconstruct the node with only the used aliases
                kept_nodes.append(
                    ast.ImportFrom(
                        module=node.module,
                        names=kept_aliases,
                        level=node.level,
                    )
                )
        return kept_nodes

    def filter_used_unparse(self, *snippets: str) -> str:
        """Filter imports to only include ones used in the snippet.

        :param snippets: Snippet to look for used imports in.
        :return: Imports code with only used imports.
        """
        return _nodes_unparse(self.filter_used(*snippets))  # ty: ignore[invalid-argument-type]
