"""Routines for scanning text files for dependencies."""

import collections.abc as col

import ahocorasick  # ty: ignore[unresolved-import]

import clunkster.analyze.model as my_analyze_model
import clunkster.parse.gml as my_parse_gml


def build_automaton(asset_names: col.Iterable[str]) -> ahocorasick.Automaton:
    """Build an automaton from a list of asset names.

    :param asset_names: Asset names to include.
    :return: Automaton.
    """
    automaton = ahocorasick.Automaton()
    for name in asset_names:
        automaton.add_word(name, name)
    automaton.make_automaton()
    return automaton


def scan_text_for_dependencies(
    task: my_analyze_model.ScanTask, automaton: ahocorasick.Automaton
) -> list[my_analyze_model.DependencyEdge]:
    """Scans a single file's text for asset dependencies.

    This routine is used in multiprocessing.
    :param task: Scan task, containing necessary information.
    :param automaton: Aho-Corasick automaton with all asset names.
    :return: Dependency edges.
    """
    text = task.gml_text
    gml_index = my_parse_gml.GmlIndex.from_text(text)
    edges: set[my_analyze_model.DependencyEdge] = set()

    for end_idx, target_asset in automaton.iter(text):
        start_idx = end_idx - len(target_asset) + 1

        # prevent self loops
        if target_asset == task.asset_name:
            continue

        # check if whole identifier
        if start_idx > 0:
            prev_char = text[start_idx - 1]
            if prev_char.isalnum() or prev_char == '_':
                continue
        if end_idx + 1 < len(text):
            next_char = text[end_idx + 1]
            if next_char.isalnum() or next_char == '_':
                continue

        # check if symbol is inside gml code
        if gml_index.is_ignored_at(start_idx):
            continue

        contexts = gml_index.get_contexts_at(start_idx)
        edges.add(
            my_analyze_model.DependencyEdge(
                source_asset=task.asset_name,
                target_asset=target_asset,
                contexts=contexts,
            )
        )

    return list(edges)
