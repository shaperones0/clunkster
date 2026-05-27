"""Inject examples into readme."""

import ast
import re
import textwrap
from pathlib import Path

import cog  # ty: ignore[unresolved-import]


def example_inject(filename: str) -> None:
    """Inject given file.

    :param filename: Name of the file to inject.
    """
    with Path(filename).open() as f:
        source = f.read()

    tree = ast.parse(source)
    lines = source.splitlines()

    # translate module docstring
    docstring = ast.get_docstring(tree)
    if docstring:
        # rst2md: ``code`` -> `code`
        docstring = re.sub(r'``([^`]+)``', r'`\1`', docstring)
        # rst2md: :class:`MyClass` -> `MyClass`
        docstring = re.sub(r':[a-zA-Z0-9_-]+:`([^`]+)`', r'`\1`', docstring)

        cog.outl(docstring)
        cog.outl()

    # skip module docstring
    doc_end_line = 0
    if (
        tree.body
        and isinstance(tree.body[0], ast.Expr)
        and isinstance(tree.body[0].value, ast.Constant)
    ):
        doc_end_line = tree.body[0].end_lineno

    # find main()
    main_node = next(
        (
            n
            for n in tree.body
            if isinstance(n, ast.FunctionDef) and n.name == 'main'
        ),
        None,
    )

    # make code block
    cog.outl('```python')

    if main_node:
        # extract globals (imports/constants)
        # everything between docstring and main()
        global_lines = lines[doc_end_line : main_node.lineno - 1]
        global_text = '\n'.join(global_lines).strip('\n')

        if global_text:
            cog.outl(global_text)
            cog.outl()  # blank line between globals and main

        # extract main()
        body_start = main_node.body[0].lineno - 1
        body_end = main_node.body[-1].end_lineno
        main_body_text = '\n'.join(lines[body_start:body_end])

        cog.outl(textwrap.dedent(main_body_text))
    else:
        # fallback if no main function exists:
        # output everything after the docstring
        cog.outl('\n'.join(lines[doc_end_line:]).strip('\n'))

    cog.outl('```')
