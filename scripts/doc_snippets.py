"""Markdown snippet model."""

from enum import Enum, auto
from dataclasses import dataclass
from typing import Self
import collections.abc as col


class SnippetType(Enum):
    """Snippet type."""

    PYTHON = auto()
    MD = auto()


@dataclass(frozen=True, slots=True)
class Snippet:
    """Snippet struct for easier rendering and distinction."""

    type: SnippetType
    content: str


def s_py(code: str) -> Snippet:
    return Snippet(
        type=SnippetType.PYTHON,
        content=code,
    )

def s_md(code: str) -> Snippet:
    return Snippet(
        type=SnippetType.MD,
        content=code,
    )

