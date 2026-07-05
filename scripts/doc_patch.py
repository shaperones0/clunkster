"""Dumb Document system - the f-string hijack edition."""

import ast
import functools as ft
import inspect
import textwrap
import types
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from enum import Enum, auto
from typing import Self, cast

from scripts.doc_render import render
from scripts.doc_snippets import Snippet, s_md, s_py


@dataclass(slots=True)
class FstringPartCode:
    """Fstring part code."""

    code_str: str
    compiled: types.CodeType
    result: list[Snippet] | None
    err: Exception | None


class FuncParser[**P]:
    def __init__(
            self,
            *,
            func: Callable[P, str],
            setup_code: types.CodeType,
            parts: list[str | FstringPartCode]
    ):
        self.func = func
        self.setup_code = setup_code
        self.parts = parts

    @classmethod
    def from_func(cls, func: Callable[P, str]) -> Self:
        # parse and compile func's AST
        source = textwrap.dedent(inspect.getsource(func))
        tree = ast.parse(source)
        func_body = tree.body[0].body  # ty: ignore[unresolved-attribute]

        setup_statements = func_body[:-1]
        return_statement = func_body[-1]

        if not isinstance(return_statement, ast.Return) or not isinstance(
                return_statement.value, ast.JoinedStr
        ):
            raise TypeError(
                "Template must end with a single `return f'...'` statement."
            )

        # compile setup code
        setup_code = compile(
            ast.Module(body=setup_statements, type_ignores=[]),
            filename='<template_setup>',
            mode='exec',
        )

        # compile f string parts individually
        fstring_parts: list[str | FstringPartCode] = []
        for node in return_statement.value.values:
            if isinstance(node, ast.Constant):
                assert isinstance(node.value, str)
                fstring_parts.append(str(node.value))
            elif isinstance(node, ast.FormattedValue):
                raw_code = ast.unparse(node.value)
                compiled_node = compile(
                    ast.Expression(node.value),
                    filename='<template_node>',
                    mode='eval',
                )
                fstring_parts.append(
                    FstringPartCode(
                        code_str=raw_code,
                        compiled=compiled_node,
                        result=None,
                        err=None,
                    )
                )
        return cls(
            func=func,
            setup_code=setup_code,
            parts=fstring_parts
        )

    def execute(self, *args: P.args, **kwargs: P.kwargs) -> None:
        # bind arguments to local params
        fn = cast(types.FunctionType, self.func)    # i swear
        sig = inspect.signature(fn)
        bound_args = sig.bind(*args, **kwargs)
        bound_args.apply_defaults()

        # execution environment
        local_scope: dict[str, object] = dict(bound_args.arguments)
        global_scope: dict[str, object] = fn.__globals__  # ty: ignore[unresolved-attribute]

        exec(self.setup_code, global_scope, local_scope)  # noqa: S102

        # relaunching is now responsibility of the caller

        for i, part in enumerate(self.parts):
            if isinstance(part, str):
                # outside text is markdown, rendering handled in render
                continue

            try:
                # evaluate the snippet
                result = eval(part.compiled, global_scope, local_scope)  # noqa: S307
            except Exception as e:
                part.err = e
                if part.result is not None:
                    # this part used to be resolved
                    raise RuntimeError(
                        f'State Violation in snippet '
                        f'`{{{part.code_str}}}`.\n'
                        f'It succeeded on a previous pass but failed '
                        f'on current iteration.\n'
                        f'Ensure your template functions do not have '
                        f'unsafe side effects.'
                    ) from e
            else:
                snippets: list[Snippet] = []
                if result is None:
                    # don't do anything
                    pass
                elif isinstance(result, str):
                    snippets.append(s_md(result))
                else:
                    snippets.extend(result)
                part.result = snippets

    def is_resolved(self) -> bool:
        for i, part in enumerate(self.parts):
            if isinstance(part, str):
                # text needs no evaluating
                continue
            if part.result is None:
                return False
        return True

    def render_snippets(self) -> Iterator[Snippet]:
        for i, part in enumerate(self.parts):
            if isinstance(part, str):
                # bark down
                yield s_md(part)
                continue
            if part.result is None:
                raise ValueError(f"Attempted rendering unresolved snippet '{{{part.code_str}}}'")
            yield from part.result

    def render_str(self) -> str:
        return render(self.render_snippets()).strip('\n') + '\n'


