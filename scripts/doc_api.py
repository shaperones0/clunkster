"""Reference scanner and generator."""

import collections.abc as col
import textwrap
from dataclasses import dataclass
from typing import cast

import griffe
import ast

TOC_MAX_LEN = 28


def docstring_get_brief_desc(
    parsed: col.Iterable[griffe.DocstringSection],
) -> tuple[str, str]:
    """Get brief and description from a docstring."""
    for section in parsed:
        if section.kind.value == 'text':
            lines = section.value.splitlines()
            if lines:
                return lines[0].strip(), '\n'.join(lines[1:]).strip()
            break
    return '', ''


def trunk_ellipsis(text: str, max_len: int, end: str = '...') -> str:
    """Truncate a string and add a thing at the end."""
    if len(text) > max_len:
        return text[: max_len - len(end)] + end
    return text


class ApiManager:
    """Manage AST scanning."""

    def __init__(self, library_name: str) -> None:
        """Initialize the manager.

        :param library_name: Library name.
        """
        self.library_name = library_name
        self.manifest: dict[str, str] = {}
        self.cache_rendered: str | None = None

    def render_reference(self) -> str:  # noqa: C901
        """Scan the library and render reference file."""
        if self.cache_rendered is not None:
            return self.cache_rendered

        lib = cast(
            griffe.Module,
            griffe.load(
                self.library_name,
                docstring_parser='sphinx',
            ),
        )
        md_content: list[str] = []

        def process_module(mod: griffe.Module) -> None:
            has_content = any(
                m.kind in (griffe.Kind.CLASS, griffe.Kind.FUNCTION)
                and not m.is_alias
                for m in mod.members.values()
            )

            if has_content:
                # parse docstring for brief and desc
                brief, description = docstring_get_brief_desc(
                    () if mod.docstring is None else mod.docstring.parsed
                )

                str_heading = f'## `{mod.path}`'
                if brief:
                    str_heading += f' - {brief}'
                md_content.append(f'{str_heading}\n')

                if description:
                    md_content.append(f'{description}\n')

                for member_name, member in sorted(mod.members.items()):
                    if member.is_alias:
                        continue
                    assert isinstance(member, griffe.Object)
                    if (
                        member_name.startswith('_')
                        and member_name != '__init__'
                    ):
                        continue

                    if member.kind in (
                        griffe.Kind.CLASS,
                        griffe.Kind.FUNCTION,
                    ):
                        md_content.append(
                            self._build_markdown_for_object(member, level=3)
                        )

                        target_url = f'/reference/#{member.path}'
                        if (
                            self.manifest.get(member.path, target_url)
                            != target_url
                        ):
                            raise KeyError(
                                f'Path {member.path} is already referenced '
                                f'to {self.manifest[member.path]}, it cannot '
                                f'point to {target_url}'
                            )
                        self.manifest[member.path] = target_url

            # recurse
            for child_mod in mod.modules.values():
                process_module(child_mod)

        process_module(lib)
        self.cache_rendered = rendered = '\n'.join(md_content)
        return rendered

    def href(
        self,
        name: str,
        text: str | None = None,
        *,
        is_code: bool = False,
    ) -> str:
        """Resolve API link.

        :raise KeyError: If called before ``render_reference()`` processes the
          required object.
        """
        url = self.manifest[name]
        display_text = text or name

        if is_code:
            # use [[url|text]] syntax for Python-Markdown Preprocessor
            return f'[[{url}|{display_text}]]'

        # md link
        return f'[{display_text}]({url})'

    def _build_markdown_for_object(  # noqa: C901, PLR0912, PLR0915
        self, obj: griffe.Object, level: int, parent_name: str | None = None
    ) -> str:
        md: list[str] = [f'<a id="{obj.path}"></a>']
        prefix = '#' * level

        def ann_to_str(ann: str | griffe.Expr | None) -> str:
            if ann is None:
                return 'Any'
            if isinstance(ann, str):
                return f'"{ann}"'
            return str(ann)

        # parse docstring for brief and desc
        brief, description = docstring_get_brief_desc(
            () if obj.docstring is None else obj.docstring.parsed
        )

        if obj.kind == griffe.Kind.CLASS:
            assert isinstance(obj, griffe.Class)

            # header
            header_text = trunk_ellipsis(
                f'`CLS` `{obj.name}`', TOC_MAX_LEN, '`...'
            )
            md.append(f'{prefix} {header_text}\n')

            # brief
            if brief:
                md.append(f'{brief}\n')

            # description
            if description:
                md.append(f'{description}\n')
        elif obj.kind == griffe.Kind.FUNCTION:
            assert isinstance(obj, griffe.Function)

            # header
            header_text = trunk_ellipsis(
                f'`DEF` `{obj.name}`', TOC_MAX_LEN, '`...'
            )
            md.append(f'{prefix} {header_text}\n')

            # signature
            parent_pref = (
                'def ' if parent_name is None else f'def {parent_name}.'
            )
            cnt_params = sum(
                1 for p in obj.parameters if p.name not in ('self', 'cls')
            )
            if cnt_params > 2:  # noqa: PLR2004
                # block
                md.append('```python')
                md.append(f'{parent_pref}{obj.name}(')
                for p in obj.parameters:
                    if p.name in ('self', 'cls'):
                        md.append(f'    {p.name},')
                    else:
                        md.append(f'    {p.name}: {ann_to_str(p.annotation)},')
                if obj.name == '__init__':
                    md.append('):')
                else:
                    md.append(f') -> {ann_to_str(obj.returns)}:')
                md.append('```\n')

                # brief afterward
                if brief:
                    md.append(f'{brief}\n')
            else:
                # inline
                params_parts: list[str] = []
                for p in obj.parameters:
                    if p.name in ('self', 'cls'):
                        params_parts.append(p.name)
                    else:
                        params_parts.append(
                            f'{p.name}: {ann_to_str(p.annotation)}'
                        )
                params = ', '.join(params_parts)
                if obj.name == '__init__':
                    signature = f'{parent_pref}{obj.name}({params}):'
                else:
                    signature = (
                        f'{parent_pref}{obj.name}({params}) -> '
                        f'{ann_to_str(obj.returns)}:'
                    )

                if brief:
                    md.append(f'`{signature}` {brief}\n')
                else:
                    md.append(f'`{signature}`\n')

            # params
            docstring = obj.docstring
            if docstring is not None:
                for section in docstring.parsed:
                    if section.kind.value == 'parameters':
                        for param in section.value:
                            assert isinstance(param, griffe.DocstringParameter)
                            md.append(
                                f'- `{param.name}: '
                                f'{ann_to_str(param.annotation)}` - '
                                f'{param.description}'
                            )
                        md.append('\n')
                    elif section.kind.value == 'returns':
                        ret = section.value[0]
                        assert isinstance(ret, griffe.DocstringReturn)
                        md.append(
                            f'**Returns:** `{ann_to_str(ret.annotation)}` - '
                            f'{ret.description}\n'
                        )

            # description
            if description:
                md.append(f'{description}\n')

        else:
            raise NotImplementedError

        # view source
        if obj.source:
            is_abstract = 'abstractmethod' in obj.labels

            lines = [line.strip() for line in obj.source.splitlines()]
            is_empty_body = (
                obj.kind == griffe.Kind.FUNCTION
                and len(lines) > 0
                and lines[-1] in ('pass', '...')
            )

            is_abstract_class = False
            if isinstance(obj.parent, griffe.Class):
                for base in obj.parent.bases:
                    # evaluate the base expression to a string
                    if str(base) in ('ABC', 'abc.ABC'):
                        is_abstract_class = True
                        break

            is_empty_abc_init = (
                is_abstract_class and obj.name == '__init__' and is_empty_body
            )

            # show source if it's concrete function with body and
            #  ain't abc __init__
            if not is_abstract and not is_empty_body and not is_empty_abc_init:
                md.append('??? quote "View source"')
                md.append('    ```python')
                md.append(textwrap.indent(obj.source, '    '))
                md.append('    ```\n')

        # recurse
        if obj.members:
            for member_name, member in sorted(obj.members.items()):
                if member.is_alias:
                    continue
                assert isinstance(member, griffe.Object)

                if member_name.startswith('_') and member_name != '__init__':
                    continue
                if member.kind in (griffe.Kind.CLASS, griffe.Kind.FUNCTION):
                    md.append(
                        self._build_markdown_for_object(
                            member, level + 1, parent_name=obj.name
                        )
                    )

        return '\n'.join(md)


@dataclass(frozen=True, slots=True)
class _Replacement:
    lineno: int
    col_offset: int
    end_col_offset: int | None
    display: str
    link: str

    def sort_key(self) -> tuple[int, int]:
        return self.lineno, self.col_offset


def inject_python_code_links(
        *,
        code_str: str,
        api: ApiManager,
        import_map: dict[str, str]
) -> str:
    """Find API usages in source, inject code links."""

    if api.cache_rendered is None:
        raise KeyError("API Reference not yet generated. Deferring snippet linking.")

    tree = ast.parse(code_str)

    replacements: list[_Replacement] = []
    lines = code_str.splitlines()

    # recursive resolver for complex attributes like `clunkster.asset.Room`
    def get_fqn(node: ast.AST) -> str | None:
        if isinstance(node, ast.Name):
            return import_map.get(node.id)
        elif isinstance(node, ast.Attribute):
            base = get_fqn(node.value)
            if base:
                return f"{base}.{node.attr}"
        return None

    class LinkVisitor(ast.NodeVisitor):
        def visit_Import(self, node: ast.Import) -> None:
            pass  # ignore import statements

        def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
            pass

        def visit_Attribute(self, node: ast.Attribute) -> None:
            fqn = get_fqn(node)
            if fqn and fqn in api.manifest:
                # extract exact string from source to preserve styling
                disp = lines[node.lineno - 1][node.col_offset:node.end_col_offset]
                replacements.append(_Replacement(
                    lineno=node.lineno,
                    col_offset=node.col_offset,
                    end_col_offset=node.end_col_offset,
                    display=disp,
                    link=api.manifest[fqn],
                ))
                # stop recursion so we don't link the base module separately
                return
            self.generic_visit(node)

        def visit_Name(self, node: ast.Name) -> None:
            fqn = import_map.get(node.id)
            if fqn and fqn in api.manifest:
                replacements.append(_Replacement(
                    lineno=node.lineno,
                    col_offset=node.col_offset,
                    end_col_offset=node.end_col_offset,
                    display=node.id,
                    link=api.manifest[fqn],
                ))
            self.generic_visit(node)

    LinkVisitor().visit(tree)

    if not replacements:
        return code_str

    # sort bottom-to-top, right-to-left so slicing doesn't shift offsets
    replacements.sort(key=_Replacement.sort_key, reverse=True)

    for rep in replacements:
        idx = rep.lineno - 1
        line = lines[idx]
        lines[idx] = (
            f"{line[:rep.col_offset]}__ZEN[{rep.link}|{rep.display}]ZEN__"
            f"{line[rep.end_col_offset:]}"
        )

    return "\n".join(lines)
