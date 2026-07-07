"""Markdown extension for supporting links right in the code."""

import re
from typing import override

import markdown
from markdown.extensions import Extension
from markdown.postprocessors import Postprocessor
from markdown.preprocessors import Preprocessor

# Matches our custom syntax: [[target_url|Display Text]]
LINK_REGEX = re.compile(r'\[\[(.*?)\|(.*?)\]\]')


class InjectorPreprocessor(Preprocessor):
    """Convert code links into valid python identifiers.

    Allows storing links while making highlighter happy.
    """

    def __init__(self, md: markdown.Markdown, tracker: dict[str, str]) -> None:
        """Initialize the preprocessor.

        :param md: Markdown instance.
        :param tracker: Shared tracker dictionary.
        """
        super().__init__(md)
        self.tracker = tracker
        self.counter = 0

    @override
    def run(self, lines: list[str]) -> list[str]:
        new_lines = []
        for line in lines:
            while True:
                match = LINK_REGEX.search(line)
                if not match:
                    break

                url, text = match.groups()
                # identifier placeholder
                placeholder = f'__ZEN_LINK_{self.counter}__'

                # store html
                self.tracker[placeholder] = (
                    f'<a href="{url}" class="interactive-note-link">{text}</a>'
                )

                # swap syntax
                line = (
                    line[: match.start()] + placeholder + line[match.end() :]
                )
                self.counter += 1

            new_lines.append(line)
        return new_lines


class InjectorPostprocessor(Postprocessor):
    """Replace previously made identifiers with actual HTML links."""

    def __init__(self, md: markdown.Markdown, tracker: dict[str, str]) -> None:
        """Initialize the postprocessor.

        :param md: Markdown instance.
        :param tracker: Shared tracker dictionary.
        """
        super().__init__(md)
        self.tracker = tracker

    @override
    def run(self, text: str) -> str:
        for placeholder, html in self.tracker.items():
            text = text.replace(placeholder, html)
        return text


class CodeLinkExtension(Extension):
    """Code links extension."""

    @override
    def extendMarkdown(self, md: markdown.Markdown) -> None:
        """Add processors to Markdown instance."""
        tracker: dict[str, str] = {}
        # priority 100 runs before syntax highlighters and block parsers
        md.preprocessors.register(
            InjectorPreprocessor(md, tracker), 'code_link_pre', 100
        )
        # priority 10 runs after HTML is generated
        md.postprocessors.register(
            InjectorPostprocessor(md, tracker), 'code_link_post', 10
        )


def makeExtension(**kwargs: object) -> Extension:  # noqa: N802
    """Extension finder entrypoint."""
    return CodeLinkExtension(**kwargs)
