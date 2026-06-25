"""Code generation."""
from typing import Self
import collections.abc as col
from dataclasses import dataclass
import functools as ft

from scripts import doc_imports, doc_parse, doc_extract, doc_headers
from scripts.doc_headers import HeaderGenerator
from scripts.doc_snippets import Snippet, SnippetType, s_py, s_md
from scripts.doc_toc import str_to_anchor

CodeName = str
SnippetName = str
InputJunk = str | Snippet | col.Iterable[Snippet]

def _none_to_empty_str[**P](func: col.Callable[P, None]) -> col.Callable[P, str]:
    @ft.wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> str:
        func(*args, **kwargs)
        return ""
    return wrapper


def shad(_) -> str:
    return ""


class CodeGenerator:
    """Code generator."""

    def __init__(self, snippets: dict[str, list[Snippet]], imports: doc_imports.ImportsFilter, header_generator: doc_headers.HeaderGenerator) -> None:
        self.snippets = snippets
        self.imports = imports
        self.head = header_generator

        # code names to headers
        self.code_header: dict[CodeName, doc_headers.Header] = {}
        # snippet names to stubs
        self.snippet_stub: dict[SnippetName, str] = {}
        # snippet names to owner code names
        self.snippet_owner: dict[SnippetName, CodeName] = {}

        self.current_code_name: CodeName = ""

    @classmethod
    def from_text(cls, text: str, header_generator: doc_headers.HeaderGenerator) -> Self:
        lines = text.splitlines()
        return cls(
            snippets=doc_extract.extract(doc_parse.parse(lines)),
            imports=doc_imports.ImportsFilter.from_code(text),
            header_generator=header_generator
        )

    @_none_to_empty_str
    def reset(self) -> None:
        self.head.reset()

    def code_begin(self, code_name: CodeName, header_title: str) -> str:
        self.current_code_name = code_name
        header = self.head.next_header(header_title)
        self.code_header[code_name] = header
        return header.render_header()

    @_none_to_empty_str
    def code_reg_stub_src(self, *stub_snippet_names: SnippetName) -> None:
        assert self.current_code_name
        for name in stub_snippet_names:
            self.snippet_owner[name] = self.current_code_name

    def rend_stub(self, snippet_name: SnippetName) -> str:
        # keep KeyError
        name = self.snippet_owner[snippet_name]
        header = self.code_header[name]
        stub = self.snippet_stub[snippet_name]
        return f'# see {header.header_mini}\n{stub}'

    def reg_head(self, code_name: CodeName, header: doc_headers.Header) -> None:
        self.code_header[code_name] = header

    def reg_stub_src(self, code_name: CodeName, stub_snippet_name: SnippetName) -> None:
        existing = self.snippet_owner.get(stub_snippet_name)
        if existing is not None and existing != code_name:
            raise KeyError(f'Several codes ({self.snippet_owner[stub_snippet_name]}, {code_name}) registered as owners of {stub_snippet_name}')
        self.snippet_owner[stub_snippet_name] = code_name

    def render(self, seq: col.Iterable[InputJunk], *, render_imports: bool = True, render_code: bool = True) -> list[Snippet]:
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
            if thing.type == SnippetType.PYTHON:
                snips_code.append(thing.content)
            snips.append(thing)
        else:
            for snip in thing:
                snips.append(snip)
                if snip.type == SnippetType.PYTHON:
                    snips_code.append(snip.content)
    return snips_code, snips
