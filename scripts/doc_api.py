"""Reference scanner and generator."""

import griffe
import textwrap
import collections.abc as col

from typing import cast


TOC_MAX_LEN = 28


def docstring_get_brief_desc(parsed: col.Iterable[griffe.DocstringSection]) -> tuple[str, str]:
    for section in parsed:
        if section.kind.value == "text":
            lines = section.value.splitlines()
            if lines:
                return lines[0].strip(), "\n".join(lines[1:]).strip()
            break
    return '', ''


def trunk_ellipsis(text: str, max_len: int, end: str = '...') -> str:
    if len(text) > max_len:
        return text[:max_len - len(end)] + end
    return text


class ApiManager:
    """Manage AST scanning."""

    def __init__(self, library_name: str) -> None:
        """Initialize the manager.

        :param library_name: Library name.
        """

        self.library_name = library_name
        self.manifest: dict[str, str] = {}
        self._rendered_cache: str | None = None

    def render_reference(self) -> str:
        """Scan the library and render reference file."""

        if self._rendered_cache is not None:
            return self._rendered_cache

        lib = cast(griffe.Module, griffe.load(
            self.library_name,
            docstring_parser='sphinx',
        ))
        md_content: list[str] = []

        def process_module(mod: griffe.Module):
            has_content = any(
                m.kind in (griffe.Kind.CLASS, griffe.Kind.FUNCTION)
                and not m.is_alias
                for m in mod.members.values()
            )

            if has_content:
                # parse docstring for brief and desc
                brief, description = docstring_get_brief_desc(() if mod.docstring is None else mod.docstring.parsed)

                str_heading = f'## `{mod.path}`'
                if brief:
                    str_heading += f" - {brief}"
                md_content.append(f"{str_heading}\n")

                if description:
                    md_content.append(f"{description}\n")

                for member_name, member in sorted(mod.members.items()):
                    if member.is_alias:
                        continue
                    assert isinstance(member, griffe.Object)
                    if member_name.startswith("_") and member_name != "__init__":
                        continue

                    if member.kind in (griffe.Kind.CLASS, griffe.Kind.FUNCTION):
                        md_content.append(self._build_markdown_for_object(
                            member,
                            level=3
                        ))

                        target_url = f"reference.md#{member.path}"
                        if self.manifest.get(member.path, target_url) != target_url:
                            raise KeyError(f'Path {member.path} is already referenced to {self.manifest[member.path]}, it cannot point to {target_url}')
                        self.manifest[member.path] = target_url

            # recurse
            for child_mod in mod.modules.values():
                process_module(child_mod)

        process_module(lib)
        self._rendered_cache = rendered = "\n".join(md_content)
        return rendered

    def href(self, name: str, text: str | None = None, is_code: bool = False) -> str:
        """Resolve API link.

        :raise KeyError: If called before ``render_reference()`` processes the
          required object.
        """

        url = self.manifest[name]
        display_text = text if text else name

        if is_code:
            # use [[url|text]] syntax for Python-Markdown Preprocessor
            return f"[[{url}|{display_text}]]"

        # md link
        return f"[{display_text}]({url})"

    def _build_markdown_for_object(self, obj: griffe.Object, level: int, parent_name: str | None = None) -> str:
        md: list[str] = [f'<a id="{obj.path}"></a>']
        prefix = "#" * level

        def ann_to_str(ann: str | griffe.Expr | None) -> str:
            if ann is None:
                return 'Any'
            elif isinstance(ann, str):
                return f'"{ann}"'
            else:
                return str(ann)

        # parse docstring for brief and desc
        brief, description = docstring_get_brief_desc(() if obj.docstring is None else obj.docstring.parsed)

        if obj.kind == griffe.Kind.CLASS:
            assert isinstance(obj, griffe.Class)

            # header
            header_text = trunk_ellipsis(f"`CLS` `{obj.name}`", TOC_MAX_LEN, '`...')
            md.append(f"{prefix} {header_text}\n")

            # brief
            if brief:
                md.append(f'{brief}\n')

            # description
            if description:
                md.append(f'{description}\n')
        elif obj.kind == griffe.Kind.FUNCTION:
            assert isinstance(obj, griffe.Function)

            # header
            header_text = trunk_ellipsis(f"`DEF` `{obj.name}`", TOC_MAX_LEN, '`...')
            md.append(f"{prefix} {header_text}\n")

            # signature
            parent_pref = 'def ' if parent_name is None else f'def {parent_name}.'
            cnt_params = sum(1 for p in obj.parameters if p.name not in ('self', 'cls'))
            if cnt_params > 2:
                # block
                md.append("```python")
                md.append(f"{parent_pref}{obj.name}(")
                for p in obj.parameters:
                    if p.name in ('self', 'cls'):
                        md.append(f"    {p.name},")
                    else:
                        md.append(f"    {p.name}: {ann_to_str(p.annotation)},")
                if obj.name == '__init__':
                    md.append(f"):")
                else:
                    md.append(f") -> {ann_to_str(obj.returns)}:")
                md.append("```\n")

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
                        params_parts.append(f"{p.name}: {ann_to_str(p.annotation)}")
                params = ", ".join(params_parts)
                if obj.name == '__init__':
                    signature = f"{parent_pref}{obj.name}({params}):"
                else:
                    signature = f"{parent_pref}{obj.name}({params}) -> {ann_to_str(obj.returns)}:"

                if brief:
                    md.append(f"`{signature}` {brief}\n")
                else:
                    md.append(f"`{signature}`\n")

            # params
            docstring = obj.docstring
            if docstring is not None:
                for section in docstring.parsed:
                    if section.kind.value == "parameters":
                        for param in section.value:
                            assert isinstance(param, griffe.DocstringParameter)
                            md.append(f"- `{param.name}: {ann_to_str(param.annotation)}` - {param.description}")
                        md.append("\n")
                    elif section.kind.value == "returns":
                        ret = section.value[0]
                        assert isinstance(ret, griffe.DocstringReturn)
                        md.append(f"**Returns:** `{ann_to_str(ret.annotation)}` - {ret.description}\n")

            # description
            if description:
                md.append(f"{description}\n")

        else:
            raise NotImplementedError()

        # view source
        if obj.source:
            is_abstract = 'abstractmethod' in obj.labels

            lines = [line.strip() for line in obj.source.splitlines()]
            is_empty_body = obj.kind == griffe.Kind.FUNCTION and len(lines) > 0 and lines[-1] in ("pass", "...")

            is_abstract_class = False
            if isinstance(obj.parent, griffe.Class):
                for base in obj.parent.bases:
                    # evaluate the base expression to a string
                    if str(base) in ("ABC", "abc.ABC"):
                        is_abstract_class = True
                        break

            is_empty_abc_init = is_abstract_class and obj.name == "__init__" and is_empty_body

            # show source if it's concrete function with body and ain't abc __init__
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

                if member_name.startswith("_") and member_name != "__init__":
                    continue
                if member.kind in (griffe.Kind.CLASS, griffe.Kind.FUNCTION):
                    md.append(self._build_markdown_for_object(member, level + 1, parent_name=obj.name))

        return "\n".join(md)
