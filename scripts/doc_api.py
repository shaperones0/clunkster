"""Reference scanner and generator."""

import ast
import collections.abc as col
import os
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Self, cast

import griffe

from scripts import doc_imports

TOC_MAX_LEN = 28
PATH_BASE = Path(__file__).parent.parent
URL_GH_BASE = 'https://github.com/shaperones0/clunkster/blob/master/'
PATH_DOCS_MD = PATH_BASE / 'docs_md'
PATH_DOCS_REF = PATH_DOCS_MD / 'reference'


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


def gr_filepath_to_gh_link(path: Path | list[Path]) -> str:
    """Convert griffe's module filepath to link to file on GitHub."""
    if isinstance(path, list):
        raise TypeError(f'What {path}')
    rel = path.relative_to(PATH_BASE)
    return URL_GH_BASE + rel.as_posix()


def gr_qn(obj: griffe.Object) -> str:
    """Get qualified name of griffe's object."""
    return obj.path


def gr_ann_to_str(ann: str | griffe.Expr | None) -> str:
    """Convert griffe's annotation to string."""
    if ann is None:
        return 'Any'
    if isinstance(ann, str):
        return f'{ann}'
    return str(ann)


def mod_sub_cnt(mod: griffe.Module) -> int:
    """Module submodule count (no recurse)."""
    return sum(not m.is_alias for m in mod.modules.values())


def mod_sort(*mods: griffe.Module) -> list[griffe.Module]:
    """Sort modules."""
    children: list[griffe.Module] = []
    for child in mods:
        if child.is_alias:
            continue
        assert isinstance(child, griffe.Module)
        children.append(child)

    def _mod_sort_key(module: griffe.Module) -> tuple[bool, str]:
        return mod_sub_cnt(module) > 0, module.name

    children.sort(key=_mod_sort_key)
    return children


def param_to_code(param: griffe.Parameter | griffe.DocstringParameter) -> str:
    """Convert griffe parameter to code."""
    parts: list[str] = []

    is_vararg = False
    if (
        isinstance(param, griffe.Parameter)
        and param.kind == griffe.ParameterKind.var_positional
    ):
        parts.append('*')
        is_vararg = True
    parts.append(f'{param.name}: {gr_ann_to_str(param.annotation)}')
    if param.default and not is_vararg:
        parts.append(f' = {gr_ann_to_str(param.default)}')
    return ''.join(parts)


def rel_path(src: Path, dst: Path) -> Path:
    """Get relative path from source's folder to destination."""
    return Path(os.path.relpath(dst, start=src))


ProcessableTypes = (
    type[griffe.Module] | type[griffe.Function] | type[griffe.Class]
)

ProcessableObject = griffe.Module | griffe.Function | griffe.Class


@dataclass(frozen=True, slots=True)
class _Replacement:
    lineno: int
    col_offset: int
    end_col_offset: int | None
    display: str
    link: str

    def sort_key(self) -> tuple[int, int]:
        return self.lineno, self.col_offset


class ApiManager:
    """Surface view of scannable modules."""

    def __init__(
        self,
        *,
        root_lib_dir: Path,
        root_module: griffe.Module,
        mod_qn_to_module: dict[str, griffe.Module],
        mod_qn_to_sort_key: dict[str, int],
        qn_to_obj: dict[str, griffe.Object],
    ) -> None:
        """Initialize scanned modules collection.

        :param root_lib_dir: Root library directory.
        :param mod_qn_to_module: Module's qualified name to griffe's module
          object.
        """
        self.root_lib_dir = root_lib_dir
        self.root_module = root_module
        self.mod_qn_to_module = mod_qn_to_module
        self.mod_qn_to_sort_key = mod_qn_to_sort_key
        self.qn_to_obj = qn_to_obj

        self.cache_mod_qn_to_local_map: dict[str, dict[str, str]] = {}
        self.cache_qn_to_rendered: dict[str, list[str]] = {}
        self.cache_overview = ''

    @classmethod
    def from_root_lib_name(cls, library_name: str) -> Self:
        """Generate API manager from given root library name.

        :param library_name: Root library name.
        :return: Generated API manager.
        """
        lib = cast(
            griffe.Module,
            griffe.load(
                library_name,
                docstring_parser='sphinx',
            ),
        )

        mod_qn_to_module: dict[str, griffe.Module] = {}
        mod_qn_to_sort_key: dict[str, int] = {}
        lib_dir = lib.filepath
        assert isinstance(lib_dir, Path)
        root_lib_dir = lib_dir
        if root_lib_dir.name == '__init__.py':
            root_lib_dir = root_lib_dir.parent

        def _populate_modules(mod: griffe.Module) -> None:
            has_cool_members = any(
                isinstance(mem, griffe.Function | griffe.Class)
                for mem in mod.members.values()
            )

            mod_path = mod.filepath
            assert isinstance(mod_path, Path)
            qn = gr_qn(mod)
            mod_qn_to_module[qn] = mod

            if has_cool_members:
                if mod_path.name == '__init__.py':
                    raise NotImplementedError(
                        f'__init__.py modules cannot contain functional '
                        f'code. Found in {mod_path}'
                    )

                mod_qn_to_sort_key[qn] = len(mod_qn_to_sort_key)

            # recurse into submodules
            for child in mod_sort(*mod.modules.values()):
                _populate_modules(child)

        _populate_modules(lib)
        qn_to_obj: dict[str, griffe.Object] = {}

        def _populate_manifest(obj: ProcessableObject) -> None:

            # populate members
            for member_name, member in obj.members.items():
                # skip aliases
                if member.is_alias:
                    continue
                assert isinstance(member, griffe.Object)

                # can only process classes and function members
                if member.kind not in (
                    griffe.Kind.CLASS,
                    griffe.Kind.FUNCTION,
                ):
                    continue
                assert isinstance(member, griffe.Class | griffe.Function)

                # skip private members
                if member_name.startswith('_') and member_name != '__init__':
                    continue
                qual_name = gr_qn(member)
                qn_to_obj[qual_name] = member
                _populate_manifest(member)

        for module in mod_qn_to_module.values():
            _populate_manifest(module)

        return cls(
            root_lib_dir=root_lib_dir,
            root_module=lib,
            mod_qn_to_module=mod_qn_to_module,
            mod_qn_to_sort_key=mod_qn_to_sort_key,
            qn_to_obj=qn_to_obj,
        )

    def mod_qn_fname(self, mod_qn: str, suffix: str = '.md') -> str:
        """Convert module's qualified name to resulting MD file name."""
        return f'{self.mod_qn_to_sort_key[mod_qn]:0>2}_' + '.'.join(
            self.mod_qn_path(mod_qn)
            .with_suffix(suffix)
            .relative_to(self.root_lib_dir)
            .parts
        )

    def mod_qn_path(self, mod_qn: str) -> Path:
        """Module's qualified name to module's file path."""
        mod = self.mod_qn_to_module[mod_qn]
        pth = mod.filepath
        assert isinstance(pth, Path)
        return pth

    def mod_qn_locals(self, mod_qn: str) -> dict[str, str]:
        """Module's qualified name to module's local map."""
        if (locs := self.cache_mod_qn_to_local_map.get(mod_qn)) is None:
            self.cache_mod_qn_to_local_map[mod_qn] = locs = (
                self._mod_qn_locals(mod_qn)
            )
        return locs

    def _mod_qn_locals(self, mod_qn: str) -> dict[str, str]:
        mod = self.mod_qn_to_module[mod_qn]
        local_map: dict[str, str] = {}
        for m_name, m_obj in mod.members.items():
            if not m_obj.is_alias:
                assert isinstance(m_obj, griffe.Object)
                local_map[m_name] = gr_qn(m_obj)

        if mod.source:
            imports = doc_imports.ImportsFilter.from_code(mod.source)
            local_map.update(imports.get_import_map())
        return local_map

    def mod_fname(self, mod: griffe.Module, suffix: str = '.md') -> str:
        """Get module's resulting MD file name."""
        return self.mod_qn_fname(gr_qn(mod), suffix=suffix)

    def mod_url(self, mod: griffe.Module, *, cur_md_page: Path) -> str:
        """Get module's reference page URL."""
        pref = rel_path(
            src=cur_md_page.parent / cur_md_page.stem,
            dst=PATH_DOCS_REF / self.mod_fname(mod, suffix=''),
        )
        return f'{pref}#'

    def obj_url(self, obj: griffe.Object, *, cur_md_page: Path) -> str:
        """Get object's reference page URL."""
        return (
            self.mod_url(obj.module, cur_md_page=cur_md_page) + f'{gr_qn(obj)}'
        )

    def render_overview(self, cur_md_page: Path) -> str:
        """Render the reference overview page."""
        if not self.cache_overview:
            self.cache_overview = self._render_overview(
                cur_md_page=cur_md_page
            )

        return self.cache_overview

    def _render_overview(self, cur_md_page: Path) -> str:
        """Render the section index overview page."""
        lines: list[str] = []

        def _render_mod_node(
            mod: griffe.Module, depth: int
        ) -> col.Iterator[str]:
            qn = gr_qn(mod)

            has_page = qn in self.mod_qn_to_sort_key
            indent = '    ' * depth
            brief, description = docstring_get_brief_desc(
                () if mod.docstring is None else mod.docstring.parsed
            )

            if has_page:
                url = self.mod_url(mod, cur_md_page=cur_md_page)
                qn_display = f'[`{qn}`]({url})'
            else:
                qn_display = f'`{qn}`'

            icon = (
                ':lucide-folder:' if mod_sub_cnt(mod) else ':lucide-file-code:'
            )
            bullet = f'{indent}- {icon} {qn_display}'
            if brief:
                bullet += f' - {brief}'
            yield bullet

            if description:
                yield ''
                # check if need block
                ls = description.splitlines()
                num_lines = len(ls)
                if num_lines > 1:
                    # check if first line can be shoved
                    if len(ls[0]) < 80:
                        yield f'{indent}    ??? quote "{ls[0]} ..."'
                        ls.pop(0)
                    else:
                        yield f'{indent}    ??? quote "Description"'
                    for line in ls:
                        if line.strip():
                            yield f'{indent}        {line}'
                        else:
                            yield ''
                else:
                    yield f'{indent}    {description}'
                yield ''

            next_depth = depth + 1

            yield ''
            for child_mod in mod_sort(*mod.modules.values()):
                yield from _render_mod_node(child_mod, next_depth)
            yield ''

        lines.extend(_render_mod_node(self.root_module, 0))
        return '\n'.join(lines)

    def render_module(self, mod: griffe.Module, cur_md_page: Path) -> str:
        """Render given module.

        Caches rendered result using module's qualified name as a key.
        :param mod: Module to render.
        :return: Rendered Markdown string.
        """
        qn = gr_qn(mod)
        if (lines := self.cache_qn_to_rendered.get(qn)) is None:
            self.cache_qn_to_rendered[qn] = lines = self._render_module(
                mod, cur_md_page=cur_md_page
            )

        return '\n'.join(lines)

    def _render_module(
        self, mod: griffe.Module, cur_md_page: Path
    ) -> list[str]:
        qn = gr_qn(mod)
        if (cached := self.cache_qn_to_rendered.get(qn)) is not None:
            return cached
        lines: list[str] = []

        for _ in [None]:
            has_content = any(
                m.kind in (griffe.Kind.CLASS, griffe.Kind.FUNCTION)
                and not m.is_alias
                for m in mod.members.values()
            )

            if not has_content:
                break

            brief, description = docstring_get_brief_desc(
                () if mod.docstring is None else mod.docstring.parsed
            )

            lines.append(f'# `{mod.path}`\n')

            if brief:
                lines.append(f'{brief}\n')

            if description:
                lines.append(f'{description}\n')

            lines.append(
                f'[View on GitHub]({gr_filepath_to_gh_link(mod.filepath)})\n'
            )

            for member_name, member in mod.members.items():
                if member.is_alias:
                    continue
                assert isinstance(member, griffe.Object)
                if member_name.startswith('_') and member_name != '__init__':
                    continue

                if member.kind == griffe.Kind.CLASS:
                    assert isinstance(member, griffe.Class)
                    lines.extend(
                        self._render_class(member, cur_md_page=cur_md_page)
                    )
                elif member.kind == griffe.Kind.FUNCTION:
                    assert isinstance(member, griffe.Function)
                    lines.extend(
                        self._render_function(
                            member, None, cur_md_page=cur_md_page
                        )
                    )

        return lines

    def _render_view_source(
        self, obj: griffe.Object, cur_md_page: Path
    ) -> col.Iterator[str]:
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

        # show source if it's not abstract function, has body and
        #  ain't empty abc __init__
        if not is_abstract and not is_empty_body and not is_empty_abc_init:
            # populate link things
            linked_source = self.inject_code_links(
                code_str=obj.source,
                import_map=self.mod_qn_locals(gr_qn(obj.module)),
                cur_md_page=cur_md_page,
            )

            yield '??? quote "View source"'
            yield '    ```python'
            yield textwrap.indent(linked_source, '    ')
            yield '    ```\n'

    def _render_class(
        self, cl: griffe.Class, cur_md_page: Path
    ) -> col.Iterator[str]:
        yield f'<a id="{cl.path}"></a>'

        # parse docstring for brief and desc
        brief, description = docstring_get_brief_desc(
            () if cl.docstring is None else cl.docstring.parsed
        )

        badge_type = 'dtc' if 'dataclass' in cl.labels else 'cls'
        badge_text = 'DTC' if badge_type == 'dtc' else 'CLS'

        # header
        yield (
            f'## <span class="api-badge api-badge-{badge_type}">'
            f'{badge_text}'
            f'</span> '
            f'`{cl.name}`\n'
        )

        # brief
        if brief:
            yield f'{brief}\n'

        # description
        if description:
            yield f'{description}\n'

        # view source
        if cl.source:
            yield from self._render_view_source(cl, cur_md_page=cur_md_page)

        yield '___'

        # recurse
        for member_name, member in cl.members.items() if cl.members else ():
            if member.is_alias:
                continue
            assert isinstance(member, griffe.Object)

            if member_name.startswith('_') and member_name != '__init__':
                continue
            if member.kind == griffe.Kind.CLASS:
                raise NotImplementedError
            elif member.kind == griffe.Kind.FUNCTION:
                assert isinstance(member, griffe.Function)
                yield from self._render_function(
                    member, cl.name, cur_md_page=cur_md_page
                )

    def _render_function(
        self,
        func: griffe.Function,
        parent_name: str | None,
        cur_md_page: Path,
    ) -> col.Iterator[str]:
        yield f'<a id="{func.path}"></a>'

        # parse docstring for brief and desc
        brief, description = docstring_get_brief_desc(
            () if func.docstring is None else func.docstring.parsed
        )

        # badge
        if parent_name is None:
            b_type, b_text = 'def', 'FN'
        elif 'property' in func.labels:
            b_type, b_text = 'prop', 'PROP'
        elif 'classmethod' in func.labels:
            b_type, b_text = 'cmth', 'CMTH'
        else:
            b_type, b_text = 'mth', 'MTH'

        badges = f'<span class="api-badge api-badge-{b_type}">{b_text}</span>'
        if 'abstractmethod' in func.labels:
            badges += ' <span class="api-badge api-badge-abs">ABC</span>'

        # check for overrides
        is_override = False
        override_url: str | None = None

        if func.decorators:
            # decorator values are ast expressions
            #  safest check is source string
            is_override = any(
                'override' in getattr(d.value, 'source', str(d.value))
                for d in func.decorators
            )

        if is_override and isinstance(func.parent, griffe.Class):
            badges += ' <span class="api-badge api-badge-abs">OVR</span>'
            # scan mro for the base method
            for base_cls in func.parent.mro():
                if not isinstance(base_cls, griffe.Class):
                    continue
                if func.name not in base_cls.members:
                    continue

                base_meth = base_cls.members[func.name]
                assert isinstance(base_meth, griffe.Function)

                override_url = self.obj_url(base_meth, cur_md_page=cur_md_page)
                break

        # header
        m_header_pref = '##' if parent_name is None else '###'
        yield f'{m_header_pref} {badges} `{func.name}`\n'

        # signature
        m_parent_pref = (
            'def ' if parent_name is None else f'def {parent_name}.'
        )

        # block
        block_lines: list[str] = [f'def {func.name}(']
        name_to_param: dict[str, griffe.Parameter] = {}
        for p in func.parameters:
            name_to_param[p.name] = p
            if p.name in ('self', 'cls'):
                block_lines.append(f'    {p.name},')
            else:
                block_lines.append(f'    {param_to_code(p)},')
        if func.name == '__init__':
            block_lines.append('):')
        else:
            block_lines.append(f') -> {gr_ann_to_str(func.returns)}:')
        block_lines.append('    ...')

        # render block
        linked_source = self.inject_code_links(
            code_str='\n'.join(block_lines),
            import_map=self.mod_qn_locals(gr_qn(func.module)),
            cur_md_page=cur_md_page,
        ).replace(f'def {func.name}', f'{m_parent_pref}{func.name}', 1)

        # prepend decorators
        linked_lines = linked_source.splitlines()[:-1]
        if 'classmethod' in func.labels:
            linked_lines.insert(0, '@classmethod')
        if 'property' in func.labels:
            linked_lines.insert(0, '@property')

        if override_url:
            linked_lines.insert(0, f'@__ZEN[{override_url}|override]ZEN__')
        elif is_override:
            linked_lines.insert(0, '@override')

        yield '```python'
        yield '\n'.join(linked_lines)
        yield '```\n'

        # brief afterward
        if brief:
            yield f'{brief}\n'

        # params
        for section in (
            func.docstring.parsed if func.docstring is not None else ()
        ):
            if section.kind.value == 'parameters':
                for param in section.value:
                    assert isinstance(param, griffe.DocstringParameter)
                    true_param = name_to_param[param.name]
                    yield (
                        f'- `{param_to_code(true_param)}` - '
                        f'{param.description}'
                    )
                yield '\n'
            elif section.kind.value == 'returns':
                ret = section.value[0]
                assert isinstance(ret, griffe.DocstringReturn)
                yield (
                    f'**Returns:** `{gr_ann_to_str(ret.annotation)}` - '
                    f'{ret.description}\n'
                )

        # description
        if description:
            yield f'{description}\n'

        # view source
        if func.source:
            yield from self._render_view_source(func, cur_md_page=cur_md_page)

        yield '___'

        # no recurse

    def inject_code_links(
        self,
        code_str: str,
        import_map: dict[str, str],
        *,
        cur_md_page: Path,
    ) -> str:
        """Autogenerate links inside the source code.

        :param code_str: Code to inject links into.
        :param import_map: Map local aliased names to qualified names.
        :param cur_md_page: Current rendered page (needed for link resolve).
        :return: Code with injected links.
        """
        api = self
        tree = ast.parse(code_str)

        replacements: list[_Replacement] = []
        lines = code_str.splitlines()

        # recursive resolver for complex attributes like `clunkster.asset.Room`
        def get_fqn(node: ast.AST) -> str | None:
            if isinstance(node, ast.Name):
                return import_map.get(node.id)
            if isinstance(node, ast.Attribute):
                base = get_fqn(node.value)
                if base:
                    return f'{base}.{node.attr}'
            return None

        class LinkVisitor(ast.NodeVisitor):
            def visit_Import(self, node: ast.Import) -> None:
                pass  # ignore import statements

            def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
                pass

            def visit_Attribute(self, node: ast.Attribute) -> None:
                fqn = get_fqn(node)
                if fqn and fqn in api.qn_to_obj:
                    # extract exact string from source to preserve styling
                    disp = lines[node.lineno - 1][
                        node.col_offset : node.end_col_offset
                    ]
                    replacements.append(
                        _Replacement(
                            lineno=node.lineno,
                            col_offset=node.col_offset,
                            end_col_offset=node.end_col_offset,
                            display=disp,
                            link=api.obj_url(
                                api.qn_to_obj[fqn], cur_md_page=cur_md_page
                            ),
                        )
                    )
                    # stop recursion so we don't link base module separately
                    return
                self.generic_visit(node)

            def visit_Name(self, node: ast.Name) -> None:
                fqn = import_map.get(node.id)
                if fqn and fqn in api.qn_to_obj:
                    replacements.append(
                        _Replacement(
                            lineno=node.lineno,
                            col_offset=node.col_offset,
                            end_col_offset=node.end_col_offset,
                            display=node.id,
                            link=api.obj_url(
                                api.qn_to_obj[fqn], cur_md_page=cur_md_page
                            ),
                        )
                    )
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
                f'{line[: rep.col_offset]}__ZEN[{rep.link}|{rep.display}]ZEN__'
                f'{line[rep.end_col_offset :]}'
            )

        return '\n'.join(lines)
