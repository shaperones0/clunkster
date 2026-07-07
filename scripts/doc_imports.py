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


def _grouped_nodes_unparse(grouped_nodes: list[tuple[int, ImportNode]]) -> str:
    """Turn grouped nodes into correct Python syntax with blank lines.

    :param grouped_nodes: List of tuples containing (group_id, node).
    :return: Python code with groups separated by double newlines.
    """
    if not grouped_nodes:
        return ''

    # group nodes by visually separated block (isort)
    groups: dict[int, list[ast.stmt]] = {}
    for group_id, node in grouped_nodes:
        groups.setdefault(group_id, []).append(node)

    group_strings: list[str] = []
    for gid in sorted(groups.keys()):
        # unparse each isort block as its own module
        mod = ast.Module(body=groups[gid], type_ignores=[])
        group_strings.append(ast.unparse(mod))

    return '\n\n'.join(group_strings)


class ImportsFilter:
    """Filter imports."""

    def __init__(self, import_nodes: list[tuple[int, ImportNode]]) -> None:
        """Initialize filter.

        Use from_code and from_file_path constructors preferably.
        :param import_nodes: Master import nodes paired with their
          block group ID.
        """
        self.import_nodes = import_nodes

    @classmethod
    def from_code(cls, code: str) -> Self:
        """Initialize filter from given code.

        :param code: Code to parse.
        """
        tree = ast.parse(code)
        nodes: list[tuple[int, ImportNode]] = []

        current_group = 0
        last_end = -1

        for node in tree.body:
            if isinstance(node, (ast.ImportFrom, ast.Import)):
                # if gap >1 line - new block
                if last_end != -1 and node.lineno > last_end + 1:
                    current_group += 1

                nodes.append((current_group, node))
                last_end = getattr(node, 'end_lineno', node.lineno)

        return cls(nodes)

    @classmethod
    def from_file_path(cls, file_path: str) -> Self:
        """Initialize filter from given file path.

        :param file_path: Path of file to parse.
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Source file '{file_path}' not found.")
        return cls.from_code(path.read_text(encoding='utf-8'))

    def filter_used(self, *snippets: str) -> list[tuple[int, ImportNode]]:
        """Filter import nodes to only include ones used in the snippet.

        :param snippets: Snippets to look for used imports in.
        :return: Filtered grouped nodes.
        """
        names: set[str] = set()
        for snippet in snippets:
            names.update(_snippet_used_names(snippet))

        kept_nodes: list[tuple[int, ImportNode]] = []
        for group_id, node in self.import_nodes:
            kept_aliases = [
                a for a in node.names if _imported_name(a) in names
            ]
            if not kept_aliases:
                continue

            if isinstance(node, ast.Import):
                # keep the alias if its local name is referenced in the snippet
                kept_nodes.append((group_id, ast.Import(names=kept_aliases)))
            elif isinstance(node, ast.ImportFrom):
                # reconstruct the node with only the used aliases
                kept_nodes.append(
                    (
                        group_id,
                        ast.ImportFrom(
                            module=node.module,
                            names=kept_aliases,
                            level=node.level,
                        ),
                    )
                )
        return kept_nodes

    def filter_used_unparse(self, *snippets: str) -> str:
        """Filter imports to only include ones used in the snippet.

        :param snippets: Snippet to look for used imports in.
        :return: Imports code with only used imports, preserving block spacing.
        """
        return _grouped_nodes_unparse(self.filter_used(*snippets))

    def get_import_map(self) -> dict[str, str]:
        """Extract a mapping of local names to fully qualified names."""
        mapping: dict[str, str] = {}
        for _group_id, node in self.import_nodes:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    # import clunkster.lint as my_lint ->
                    #  local: 'my_lint'
                    #  fqn: 'clunkster.lint'
                    local = _imported_name(alias)
                    mapping[local] = alias.name
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    for alias in node.names:
                        # from clunkster.asset import Asset as MyAsset
                        local = alias.asname or alias.name
                        mapping[local] = f"{node.module}.{alias.name}"
        return mapping
