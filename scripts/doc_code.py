"""Code generation."""

import collections.abc as col
import functools as ft
from typing import Self

from scripts import doc_extract, doc_headers, doc_imports, doc_parse
from scripts.doc_snippets import Snippet, s_py

CodeName = str
SnippetName = str
InputJunk = str | Snippet | col.Iterable[Snippet]


def _none_to_empty_str[**P](
    func: col.Callable[P, None],
) -> col.Callable[P, str]:
    @ft.wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> str:
        func(*args, **kwargs)
        return ''

    return wrapper


def shad(_: object) -> str:
    """Shadow some value operation expecting to return an empty string."""
    return ''


def gen_stub_cls(*names: str) -> str:
    """Generate stub classes.

    :param names: Class names.
    :return: Python code with stub classes.
    """
    return '\n'.join(f'class {name}: ...' for name in names)


def gen_stub_var(*names: str) -> str:
    """Generate stub variables.

    :param names: Variable names (can include type hints).
    :return: Python code with stub variables.
    """
    return '\n'.join(f'{name} = ...' for name in names)


def gen_stub_func(*names: str) -> str:
    """Generate stub variables.

    :param names: Variable names (can include type hints).
    :return: Python code with stub variables.
    """
    return '\n'.join(f'def {name}(): ...' for name in names)


class CodeGenerator:
    """Code generator."""

    def __init__(
        self,
        snippets: dict[str, list[Snippet]],
        imports: doc_imports.ImportsFilter,
        header_manager: doc_headers.HeaderManager,
    ) -> None:
        """Initialize code generator.

        :param snippets: Source snippets.
        :param imports: Source imports.
        :param header_manager: Header generator.
        """
        self.snippets = snippets
        self.imports = imports
        self.head = header_manager

        # code names to headers
        self.code_header: dict[CodeName, doc_headers.Header] = {}
        # snippet names to stubs
        self.snippet_stub: dict[SnippetName, str] = {}
        # snippet names to owner code names
        self.snippet_owner: dict[SnippetName, CodeName] = {}

        self.current_code_name: CodeName = ''

    @classmethod
    def from_text(
        cls, text: str, header_manager: doc_headers.HeaderManager
    ) -> Self:
        """Initialize code generator from text.

        :param text: Text to parse.
        :param header_manager: Header generator.
        """
        lines = text.splitlines()
        return cls(
            snippets=doc_extract.extract(doc_parse.parse(lines)),
            imports=doc_imports.ImportsFilter.from_code(text),
            header_manager=header_manager,
        )

    def file_begin(self, name: str) -> str:
        """Signify beginning (or restart) of a file."""
        self.head.file_begin(name)
        self.current_code_name = ''
        return ''

    def code_begin(self, code_name: CodeName, header_title: str) -> str:
        """Shortcut for starting next code sample.

        :param code_name: Code name.
        :param header_title: Code header title.
        :return: Rendered header.
        """
        self.current_code_name = code_name
        header = self.head.header_next(header_title, key=code_name)
        self.code_header[code_name] = header
        return header.render_header()

    def code_reg_stub_src(
        self, stub_name_to_stub: dict[SnippetName, str]
    ) -> str:
        """Register current code as a source of given stubs.

        :param stub_name_to_stub: Stub name to stub.
        """
        assert self.current_code_name
        for stub_name, stub_code in stub_name_to_stub.items():
            self.reg_stub_src(self.current_code_name, stub_name)
            self.reg_stub_code(stub_name, stub_code)
        return ''

    def stub(self, snippet_name: SnippetName) -> str:
        """Render a stub with a link to its source.

        :param snippet_name: Stub's snippet name.
        :return: Rendered Python code.
        """
        # keep KeyError
        name = self.snippet_owner[snippet_name]
        header = self.code_header[name]
        stub = self.snippet_stub[snippet_name]

        expl = header.header_full.split(' - ')[-1]
        target_url = self.head.header_link(key=name)
        return f'# see [[{target_url}|{header.header_mini} - {expl}]]\n{stub}'

    def href(self, code_name: CodeName, text: str | None = None) -> str:
        """Render a href to given code sample.

        :param code_name: Code name.
        :param text: Text to insert into the link.
        :return: Rendered href.
        """
        return self.head.header_href(key=code_name, text=text)

    def reg_head(
        self, code_name: CodeName, header: doc_headers.Header
    ) -> None:
        """Register a header for given code sample.

        :param code_name: Code name.
        :param header: Header.
        """
        self.code_header[code_name] = header

    def reg_stub_src(
        self, code_name: CodeName, stub_snippet_name: SnippetName
    ) -> None:
        """Register code sample as a source of given stub.

        :param code_name: Code name.
        :param stub_snippet_name: Stub name.
        """
        existing = self.snippet_owner.get(stub_snippet_name)
        if existing is not None and existing != code_name:
            raise KeyError(
                f'Several codes ({self.snippet_owner[stub_snippet_name]}, '
                f'{code_name}) registered as owners of {stub_snippet_name}'
            )
        self.snippet_owner[stub_snippet_name] = code_name

    def reg_stub_code(
        self, stub_snippet_name: SnippetName, stub_code: str
    ) -> None:
        """Register stub source."""
        self.snippet_stub[stub_snippet_name] = stub_code

    def render(
        self,
        seq: col.Iterable[InputJunk],
        *,
        render_imports: bool = True,
        render_code: bool = True,
    ) -> list[Snippet]:
        """Render sequence of inputs with required imports.

        :param seq: Sequence of snippets or other stuff.
        :param render_imports: Whether to render imports.
        :param render_code: Whether to render the code.
        :return: Rendered snippets.
        """
        snips_code, snips = _sep_seq(seq)
        result: list[Snippet] = []
        if render_imports:
            result.append(s_py(self.imports.filter_used_unparse(*snips_code)))
        if render_code:
            result.extend(snips)
        return result


def _sep_seq(seq: col.Iterable[InputJunk]) -> tuple[list[str], list[Snippet]]:
    snips_code: list[str] = []
    snips: list[Snippet] = []
    for thing in seq:
        if isinstance(thing, str):
            snips_code.append(thing)
            snips.append(s_py(thing))
        elif isinstance(thing, Snippet):
            if thing.type.name == 'PYTHON':  # why do you make me do this
                snips_code.append(thing.content)
            snips.append(thing)
        else:
            for snip in thing:
                snips.append(snip)
                if snip.type.name == 'PYTHON':
                    snips_code.append(snip.content)
    return snips_code, snips
