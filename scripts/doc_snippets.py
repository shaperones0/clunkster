"""Markdown snippet model."""

from dataclasses import dataclass
from enum import Enum, auto


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
    """Shortcut for quick Python snippet."""
    return Snippet(
        type=SnippetType.PYTHON,
        content=code,
    )


def s_md(code: str) -> Snippet:
    """Shortcut for quick Markdown snippet."""
    return Snippet(
        type=SnippetType.MD,
        content=code,
    )
