"""Dumb Document system - the f-string hijack edition."""
import ast
from collections.abc import Callable
import functools as ft
import textwrap
import inspect
from dataclasses import dataclass
import types
from enum import Enum, auto

from doc_render import render
from doc_snippets import Snippet, s_md, s_py


@dataclass(frozen=True, slots=True)
class FstringPartCode:
    code_str: str
    compiled: types.CodeType


class SnippetState(Enum):
    PENDING = auto()
    RESOLVED = auto()


def template[**P](max_iterations: int = 10) -> Callable[[Callable[P, str]], Callable[P, str]]:
    """Wrap template-like function with smart f string logic.

    Function can have arbitrary code in it, but must end with

    ::

        return f" ... "

    (the f string may be multiline with triple quotes).

    Though it nukes debugging.
    :param max_iterations: Maximum number of iterations.
    :return: Decorator for wrapping the function.
    """

    def decorator(func: Callable[P, str]) -> Callable[P, str]:


        # parse and compile func's AST
        source = textwrap.dedent(inspect.getsource(func))
        tree = ast.parse(source)
        func_body = tree.body[0].body

        setup_statements = func_body[:-1]
        return_statement = func_body[-1]

        if not isinstance(return_statement, ast.Return) or not isinstance(return_statement.value, ast.JoinedStr):
            raise ValueError("Template must end with a single `return f'...'` statement.")

        # compile setup code
        setup_code = compile(
            ast.Module(body=setup_statements, type_ignores=[]),
            filename="<template_setup>",
            mode="exec"
        )

        # compile f string parts individually
        fstring_parts: list[str | FstringPartCode] = []
        for node in return_statement.value.values:
            if isinstance(node, ast.Constant):
                assert isinstance(node.value, str)
                fstring_parts.append(str(node.value))
            elif isinstance(node, ast.FormattedValue):
                raw_code = ast.unparse(node.value)
                compiled_node = compile(ast.Expression(node.value), filename="<template_node>", mode="eval")
                fstring_parts.append(
                    FstringPartCode(
                        code_str=raw_code,
                        compiled=compiled_node
                    )
                )

        @ft.wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> str:
            # bind arguments to local params
            sig = inspect.signature(func)
            bound_args = sig.bind(*args, **kwargs)
            bound_args.apply_defaults()

            # execution environment
            local_scope: dict[str, object] = dict(bound_args.arguments)
            global_scope: dict[str, object] = func.__globals__

            snippet_states: dict[int, SnippetState] = {
                i: SnippetState.PENDING
                for i, part in enumerate(fstring_parts)
                if isinstance(part, FstringPartCode)}
            last_exceptions: dict[int, Exception] = {}

            iterations = 0
            while iterations < max_iterations:
                iterations += 1
                needs_another_pass = False
                resolved_snippets: list[Snippet] = []  # resulting string parts

                # probably reset the local scope here
                exec(setup_code, global_scope, local_scope)

                for i, part in enumerate(fstring_parts):
                    if isinstance(part, str):
                        # assume text is markdown
                        resolved_snippets.append(s_md(part))
                        continue

                    try:
                        # evaluate the snippet
                        result = eval(part.compiled, global_scope, local_scope)
                    except Exception as e:
                        if snippet_states[i] == SnippetState.RESOLVED:
                            raise RuntimeError(
                                f"State Violation in snippet `{{{part.code_str}}}`.\n"
                                f"It succeeded on a previous pass but failed on iteration {iterations}.\n"
                                f"Ensure your template functions do not have unsafe side effects."
                            ) from e

                        snippet_states[i] = SnippetState.PENDING
                        last_exceptions[i] = e
                        needs_another_pass = True

                        # temp blank string
                        resolved_snippets.append(s_py("???"))
                    else:
                        snippets: list[Snippet] = []
                        for element in result:
                            # assert isinstance(element, Snippet)
                            snippets.append(element)
                        resolved_snippets.extend(result)
                        snippet_states[i] = SnippetState.RESOLVED
                        last_exceptions.pop(i, None)
                if not needs_another_pass:
                    # TODO smart merge
                    return render(resolved_snippets)

            # If we exit the while loop, we hit max_iterations
            error_msg = f"Template failed to resolve after {max_iterations} passes. Unresolved snippets:\n"
            for i, exc in last_exceptions.items():
                part = fstring_parts[i]
                if not isinstance(part, FstringPartCode):
                    continue
                error_msg += f"\n- {{{part.code_str}}} failed with {type(exc).__name__}: {exc}"

            raise RuntimeError(error_msg)

        return wrapper
    return decorator
