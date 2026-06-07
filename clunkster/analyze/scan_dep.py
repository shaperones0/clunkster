"""Routines for scanning text files for dependencies."""

import collections.abc as col
from dataclasses import dataclass

import ahocorasick  # ty: ignore[unresolved-import]

import clunkster.analyze.location as my_analyze_location
import clunkster.parse.gml as my_parse_gml


@dataclass(frozen=True, slots=True)
class DependencyMatch:
    """Detected dependency."""

    location: my_analyze_location.Location
    target_asset: str
    contexts: tuple[str, ...]


def scan(
    automaton: ahocorasick.Automaton,
    text: str,
) -> col.Iterator[DependencyMatch]:
    """Scans a single file's text for asset dependencies.

    This routine is used in multiprocessing.
    :param automaton: ahocorasick automaton with all asset names.
    :param text: Text to scan.
    :return: Dependency edges.
    """
    gml_index = my_parse_gml.GmlIndex.from_text(text)
    gml_line_map = my_analyze_location.SourceLineMap.from_text(text)

    for end_idx, target_asset in automaton.iter(text):
        start_idx = end_idx - len(target_asset) + 1

        # detect if this target is explicitly formatted as a string literal
        is_string_ref = target_asset.startswith(('"', "'"))

        # check if whole identifier
        if not is_string_ref:
            if start_idx > 0:
                prev_char = text[start_idx - 1]
                if prev_char.isalnum() or prev_char == '_':
                    # allow the match if it is strictly part of an event header
                    if (prev_char == '_' and text[start_idx - 18:start_idx] ==
                            "#define Collision_"):
                        pass
                    else:
                        continue
            if end_idx + 1 < len(text):
                next_char = text[end_idx + 1]
                if next_char.isalnum() or next_char == '_':
                    continue

        # check if symbol is not inside ignored syntax
        if not is_string_ref and gml_index.is_ignored_at(start_idx):
            continue

        contexts = gml_index.get_contexts_at(start_idx)
        line, column = gml_line_map.get_line_col(start_idx)

        yield DependencyMatch(
            location=my_analyze_location.Location(
                loc_line=line,
                loc_column=column,
                loc_index=start_idx,
            ),
            target_asset=target_asset,
            contexts=contexts,
        )
