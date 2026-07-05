"""Headings manager."""

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import override


def str_to_anchor(text: str) -> str:
    """Convert string to Markdown anchor.

    :param text: Text to convert.
    :return: Safe anchor.
    """
    return re.sub(
        r'[^\w\-]',
        '',
        re.sub(r'[\s]+', '-', re.sub(r'^[\s#]*', '', text).strip().lower()),
    )


class Header(ABC):
    """Abstract header."""

    @property
    @abstractmethod
    def header_full(self) -> str:
        """Full header."""

    @property
    @abstractmethod
    def header_mini(self) -> str:
        """Minified header."""

    @property
    @abstractmethod
    def level(self) -> int:
        """Header's level."""

    def render_header(self) -> str:
        """Render Markdown header with correct numbering.

        :return: Generated Markdown string.
        """
        return f'{"#" * self.level} {self.header_full}'

    def render_href(self, text: str | None = None) -> str:
        """Render a link to this header.

        :param text: Text to insert into the link.
        :return: Rendered header.
        """
        if text is None:
            text = self.header_mini
        return f'[{text}](#{str_to_anchor(self.header_full)})'


class HeaderSimple(Header):
    """Simplified header with constant property values."""

    def __init__(
        self, level: int, header: str, header_mini: str | None = None
    ) -> None:
        """Initialize simple header.

        :param level: Heading level.
        :param header: Heading title.
        :param header_mini: Minified heading.
        """
        self._level = level
        self._header = header
        if header_mini is None:
            self._header_mini = header
        else:
            self._header_mini = header_mini

    @override
    @property
    def header_full(self) -> str:
        return self._header

    @override
    @property
    def header_mini(self) -> str:
        return self._header_mini

    @override
    @property
    def level(self) -> int:
        return self._level


@dataclass(frozen=True, slots=True)
class ExampleHeader(Header):
    """Header of an example."""

    @override
    @property
    def level(self) -> int:
        return 3

    header: str
    idx: int | tuple[int, ...] | None = None

    def header_num(self) -> str:
        """Get header number string."""
        if self.idx is None:
            return ''
        if isinstance(self.idx, int):
            return str(self.idx)
        return '.'.join(map(str, self.idx))

    @override
    @property
    def header_full(self) -> str:
        """Generate example's full title.

        :return: Example's title.
        """
        num = self.header_num()
        return f'Example {(num + " - ") if num else ""}{self.header}'

    @override
    @property
    def header_mini(self) -> str:
        """Generate example's minified title.

        :return: Example's minified title.
        """
        return f'ex{self.header_num()}'


class HeaderManager(ABC):
    """Abstract header generator."""

    @abstractmethod
    def file_begin(self, name: str) -> None:
        """Signify beginning (or restart) of a file."""

    @abstractmethod
    def header_next(self, title: str, key: str) -> Header:
        """Generate next header.

        Header should be associated with current file.
        """

    @abstractmethod
    def header_href(self, key: str, text: str | None = None) -> str:
        """Generate href (potentially cross-document)."""


class ExampleHeaderManager(HeaderManager):
    """Example header generator."""

    def __init__(
        self, *, idx_major_start: int = 0, idx_minor_start: int = 0
    ) -> None:
        """Initialize example header generator."""
        self.idx_major_start = idx_major_start
        self.idx_minor_start = idx_minor_start
        self.current_idx_major = idx_major_start
        self.current_idx_minor = idx_minor_start

        self.key_to_header: dict[str, Header] = {}
        self.key_to_file: dict[str, str] = {}
        self.file_current = ""

    @override
    def file_begin(self, name: str) -> None:
        """Signify beginning (or restart) of a file."""
        self.current_idx_major = self.idx_major_start
        self.current_idx_minor = self.idx_minor_start

        # delete all stateful storage with this file
        self.file_current = name

    def section_next(self, title: str, key: str | None = None) -> HeaderSimple:
        """Generate next section header."""
        self.current_idx_major += 1
        self.current_idx_minor = self.idx_minor_start
        header = HeaderSimple(
            level=2,
            header=f'{self.current_idx_major} - {title}',
        )

        if key is not None:
            self.header_add(key, header)

        return header

    @override
    def header_next(self, title: str, key: str) -> ExampleHeader:
        self.current_idx_minor += 1
        header = ExampleHeader(
            header=title,
            idx=(self.current_idx_major, self.current_idx_minor),
        )

        self.header_add(key, header)

        return header

    def header_add(self, key: str, header: Header) -> None:
        assert self.file_current, "File wasn't initialized."

        self.key_to_header[key] = header
        self.key_to_file[key] = self.file_current

    def header_parse(self, header_str: str, key: str, header_mini: str | None = None) -> str:
        """Account for given header."""

        hashtag_cnt = 0
        for char in header_str:
            if char != '#':
                break
            hashtag_cnt += 1
        assert hashtag_cnt > 0, "Given string wasn't Markdown heading"

        self.header_add(key, HeaderSimple(
            level=hashtag_cnt,
            header=header_str[hashtag_cnt:].strip(),
            header_mini=header_mini,
        ))

        return header_str

    @override
    def header_href(self, key: str, text: str | None = None) -> str:
        file = self.key_to_file[key]
        header = self.key_to_header[key]
        if file == self.file_current:
            return header.render_href(text=text)
        else:
            if text is None:
                text = header.header_mini
            return f'[{text}]({file}#{str_to_anchor(header.header_full)})'
