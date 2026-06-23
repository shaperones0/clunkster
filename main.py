"""Main pipeline, together with examples."""

import collections
import collections.abc as col
import concurrent.futures
import dataclasses
import fnmatch
import itertools as it
import json
import os
import re
import shutil
import subprocess
import sys
import warnings
from abc import ABC, abstractmethod
from pathlib import Path
from typing import override, Self

import rustworkx as rx
import tqdm
from ahocorasick import Automaton  # ty: ignore[unresolved-import]
from gmcodec import (
    core as gmc_core,
)
from gmcodec import (
    file as gmc_file,
)
from gmcodec import (
    model as gmc_model,
)
from gmcodec import (
    validate as gmc_validate,
)
from PIL import Image

from clunkster import asset as my_asset, lint as my_lint
from clunkster.text import location as my_location, read as my_read
from clunkster.analyze import scan_dep as my_analyze_scan_dep
from clunkster.asset import Asset
from clunkster.text.location import Location
from clunkster.parse import tree as my_parse_tree
from clunkster.project import cache as my_proj_cache
from clunkster.project import ignore as my_proj_ignore
from clunkster.project import (
    processor as my_proj_processor,
)
from clunkster.project import (
    task as my_proj_task,
)

# --- COG_START: TERMINAL_COLORS ---
# terminal color for output
TER_RED = '\033[91m'
TER_GREEN = '\033[92m'
TER_YELLOW = '\033[93m'
TER_CYAN = '\033[96m'
TER_RESET = '\033[0m'
# --- COG_END: TERMINAL_COLORS ---


# --- COG_START: CLS_ASSET_EXT ---
@dataclasses.dataclass(frozen=True, slots=True)
class AssetExtAudio(my_asset.AssetSingleFile, ABC):
    """Generic external audio asset."""


@dataclasses.dataclass(frozen=True, slots=True)
class AssetExtBgm(AssetExtAudio):
    """External background music asset."""

    @override
    @classmethod
    def type_name(cls) -> str:
        return 'DATA_BGM'

    @override
    @classmethod
    def type_globs(cls) -> tuple[str, ...]:
        return '*.ogg', '*.mp3', '*.wav'

    @override
    @classmethod
    def type_get_dir_rel(cls) -> Path:
        return Path('data') / 'music'


@dataclasses.dataclass(frozen=True, slots=True)
class AssetExtSfx(AssetExtAudio):
    """External sound effect asset (kind 0)."""

    @override
    @classmethod
    def type_name(cls) -> str:
        return 'DATA_SFX'

    @override
    @classmethod
    def type_globs(cls) -> col.Iterable[str]:
        return ('*.wav',)

    @override
    @classmethod
    def type_get_dir_rel(cls) -> Path:
        return Path('data') / 'sounds'


@dataclasses.dataclass(frozen=True, slots=True)
class AssetExtSfx3(AssetExtAudio):
    """External sound effect asset (kind 3)."""

    @override
    @classmethod
    def type_name(cls) -> str:
        return 'DATA_SFX3'

    @override
    @classmethod
    def type_globs(cls) -> col.Iterable[str]:
        return '*.ogg', '*.mp3'

    @override
    @classmethod
    def type_get_dir_rel(cls) -> Path:
        return Path('data') / 'sounds'


def asset_scannables(asset: Asset, project_root: Path) -> col.Iterable[Path]:
    if isinstance(asset, my_asset.Object):
        yield asset.get_object_metadata_file(project_root)
        yield asset.get_object_gml_file(project_root)
    elif isinstance(asset, my_asset.Room):
        # easier to rglob
        dir_room = asset.get_room_folder(project_root)
        yield from dir_room.rglob('*.txt')
        yield from dir_room.rglob('*.gml')
    elif isinstance(asset, my_asset.Script):
        yield asset.get_script_gml_file(project_root)
    # add finders for new asset types

def asset_str_linter(asset: Asset) -> str:
    """Descriptive asset repr to be used in linters."""
    if isinstance(asset, my_asset.AssetHasPath):
        return (
            f'[{type(asset).type_name():^10}]: '
            f'{"/".join(asset.tree_path)}'
            f'/{asset.name}'
        )

    return (
        f'[{type(asset).type_name():^10}]: '
        f'{asset.name}'
    )

def asset_sort_key(asset: Asset) -> tuple[str, ...]:
    if isinstance(asset, my_asset.AssetHasPath):
        return type(asset).type_name(), '/'.join(asset.tree_path), asset.name

    return type(asset).type_name(), asset.name


def asset_cluster_raw(asset: my_asset.AssetHasPath) -> str:
    return asset.tree_path[0] if asset.tree_path else 'Common'


def asset_cluster(asset: my_asset.Asset) -> str:
    if isinstance(asset, my_asset.AssetHasPath):
        cluster = asset_cluster_raw(asset)
        alias = ALIAS_INV.get(cluster)
        return cluster if alias is None else alias
    return "Unknown?"


# --- COG_END: CLS_ASSET_EXT ---
# --- COG_START: DEF_TYPE_FILTER ---
def filter_type[TFilter](
    f_type: type[TFilter], items: col.Iterable[object]
) -> col.Iterator[TFilter]:
    """Filter given iterable based on type.

    :param f_type: Type to filter for.
    :param items: The iterable to filter.
    :return: Iterator of items of type ``f_type``.
    """
    return (item for item in items if isinstance(item, f_type))


# --- COG_END: DEF_TYPE_FILTER ---
# --- COG_START: CLUSTERABLE_BUILTINS ---
CLUSTERABLE_BUILTINS: tuple[type[my_asset.AssetHasPath], ...] = (
    my_asset.Sprite,
    my_asset.Background,
    my_asset.Sound,
    my_asset.Path,
    my_asset.Script,
    my_asset.Font,
    my_asset.Object,
    my_asset.Room,
)
# --- COG_END: CLUSTERABLE_BUILTINS ---
# --- COG_START: CLUSTERABLE_ASSETS ---
CLUSTERABLE_ASSETS: tuple[type[my_asset.AssetHasPath], ...] = (
    *CLUSTERABLE_BUILTINS,
    AssetExtBgm,
    AssetExtSfx,
    AssetExtSfx3,
)
# --- COG_END: CLUSTERABLE_ASSETS ---

# --- COG_START: ALIAS ---
ALIAS: dict[str, list[str]] = {
    'StageA': [
        'stage_a',
        'stageA',
        'StageA Music',
        # ...
    ],
    'StageB': [
        'objStageB',
        'rStageB',
        # ...
    ],
    'Common': [
        'Backgrounds',
        'Blocks',
        'Default',
        # ...
    ],
    # ...
}


def alias_invert() -> None:
    global ALIAS_INV
    inv: dict[str, str] = {}
    for name, clusters in ALIAS.items():
        for cluster in clusters:
            if cluster in inv:
                raise ValueError(f'Invalid ALIAS (duplicate: \'{cluster}\')')
            inv[cluster] = name
    ALIAS_INV = inv


ALIAS_INV: dict[str, str]
# --- COG_END: ALIAS ---

# --- COG_START: LINT_RULES_EXPLAIN ---
# MD: To validate the architecture, we must define strict boundary rules.
# MD: For this, we implement this dictionary, which maps "Source Cluster" to
# MD: a set of allowed "Target Clusters".
# MD:
# MD: Default value for clusters is themselves and "Common" cluster.
# --- COG_END: LINT_RULES_EXPLAIN ---
# --- COG_START: LINT_RULES ---
LINT_RULES: dict[str, set[str]] = {
    # common assets cannot borrow from Stage specific folders
    'Common': {'Common'},
    # example of a stage that shares assets with another
    # "StageB": {"StageB", "StageA", "Common"},
}
# --- COG_END: LINT_RULES ---

# --- COG_START: CONTEXT_RULES_EXPLAIN ---
# MD: Global controllers often check conditions (like `if room_is_StageA()`)
# MD: before referencing stage-specific assets. We map those context strings to
# MD: the additional clusters they temporarily grant access to.
# --- COG_END: CONTEXT_RULES_EXPLAIN ---
# --- COG_START: CONTEXT_RULES ---
CONTEXT_RULES: dict[str, set[str]] = {
    'room_is_stageA': {'StageA'},
    'room_is_stageB': {'StageB'},
    'room_is_final': {'StageX', 'StageY', 'StageZ'},
    # ...
}
# --- COG_END: CONTEXT_RULES ---
# --- COG_START: EXTRA_ROOTS_EXPLAIN ---
# MD: Some things exist throughout the entire game, but reachability
# MD: builder will only consider them existing only in the room they were
# MD: spawned in. Which might severe connections defined in World objects.
# MD: You should address such cases below.
# --- COG_END: EXTRA_ROOTS_EXPLAIN ---
# --- COG_START: EXTRA_ROOTS ---
EXTRA_ROOTS: set[str] = {
    'World'
    # ...
}
# --- COG_END: EXTRA_ROOTS ---

# --- COG_START: PROJECT ---
PROJECT = Path('path/to/the/project')
LINT: my_lint.LinterSession


def set_project(project_root: Path) -> None:
    global PROJECT, LINT
    PROJECT = project_root
    my_read.reg_root(PROJECT)
    LINT = my_lint.LinterSession(PROJECT, my_lint.CliConsumer())
# --- COG_END: PROJECT ---


# --- COG_START: CLS_DEPENDENCY ---
@dataclasses.dataclass(frozen=True, slots=True)
class Dependency:
    """Full dependency data to be used in graph building."""

    location: my_location.Location
    source_asset: my_asset.Asset
    target_asset: my_asset.Asset
    contexts: tuple[str, ...]


# --- COG_END: CLS_DEPENDENCY ---
# --- COG_START: CLS_ROOM_GRAPH ---
@dataclasses.dataclass
class RoomGraph:
    """Bundle of room graph data."""

    room: my_asset.Room
    reachable_names: set[str]
    graph: rx.PyDiGraph
    name2index: dict[str, int]


# --- COG_END: CLS_ROOM_GRAPH ---
# --- COG_START: CLS_JUICER_CONFIG ---
@dataclasses.dataclass(frozen=True, slots=True)
class ConfJuicer:
    """Configuration for Project Juicer."""

    # True to use prod build configuration, False for dev build configuration
    is_prod: bool
    # project output dir
    dir_out: Path
    # path to output external assets to, relative to dir_out
    rel_dir_wet: Path
    # dry asset source dir
    dir_dry: Path

    # cache.json file
    file_cache: Path
    # .clunksterignore file
    file_ignore: Path

    # filename of the gm82 project
    fname_gm82: str


JUICER = ConfJuicer(
    # start with dev builds
    is_prod=False,
    # use "_build" folder next to the project
    dir_out=Path('path/to/project/_build'),
    # if you downloaded Clunkster from source, then
    #  such is available in repository's /data/dry folder
    dir_dry=Path(__file__).parent / 'data' / 'dry',
    rel_dir_wet=Path('data') / 'chunks',
    file_cache=Path(__file__).parent / 'cache.json',
    file_ignore=Path('path/to/project/.clunksterignore'),
    fname_gm82='projectidk.gm82',
)
# --- COG_END: CLS_JUICER_CONFIG ---


def main_ex_start() -> None:
    """Let's start with some simple scanning.

    We want to check that assets get detected correctly. We don't really do
    clusters yet - that will be handled a bit later down the line.
    """
    # --- COG_START: MAIN_EX_START ---

    assets: list[Asset] = []

    for asset_type in CLUSTERABLE_ASSETS:
        # check if given asset type exist in the project
        if not asset_type.type_is_used(PROJECT):
            continue

        assets.extend(asset_type.type_discover_all(PROJECT))

    # you should investigate the resulting array for inconsistencies
    print(f'Discovered {len(assets)} total assets.')
    # --- COG_END: MAIN_EX_START ---


class LintTreeDuplicateFolder(my_lint.LinterViolationLocated, my_lint.LinterViolationMessage):

    rule = 'T100'
    severity = my_lint.Severity.ERROR

    def __init__(self, *, node: my_parse_tree.TreeNode, location: my_location.Location):
        self.tree_node = node
        self.loc = location
        super().__init__()

    @override
    @property
    def location(self) -> Location:
        return self.loc

    @override
    @property
    def message(self) -> str:
        thing = "Folder" if self.tree_node.is_folder else "Asset???"
        return f'Duplicate {thing}: \'{self.tree_node.name}\''


class LintTreeDuplicateAsset(my_lint.LinterViolationMessage):

    rule = 'T101'
    severity = my_lint.Severity.ERROR

    def __init__(self, dupes: col.Iterable[str], message_pref: str):
        super().__init__()
        self.dupes = tuple(dupes)
        self.message_pref = message_pref

    @override
    @property
    def message(self) -> str:
        return f"{self.message_pref}: {' '.join(self.dupes)}"


def main_ex_lint_tree() -> None:
    """Now we must check integrity of ``tree.yyd`` files and asset names.

    Asset discovery and clusterization is based on scanning ``tree.yyd``
    files, so we have to ensure that they have no duplicate folders.

    Technically, before doing that you should also check that there are also
    no duplicate asset names via broom icon on IDE toolbar.

    Since any inconsistency will cause big issues in the pipeline, every
    violation will be raised as an error and halt the pipline.
    """

    # --- COG_START: MAIN_EX_LINT_TREE ---
    def asset_lint_tree(asset_cls: type[my_asset.AssetBuiltin]) -> None:
        tree_file = asset_cls.type_get_tree_file(PROJECT)
        line_map = my_read.line_map(tree_file)
        seen_children: dict[str, set[str]] = {}

        for node in my_parse_tree.nodes(my_read.lines(tree_file)):
            # format the tuple into path string (e.g., "/Player/SkinA")
            path_str = '/' + '/'.join(node.parent_path)

            if path_str not in seen_children:
                seen_children[path_str] = set()

            if node.name in seen_children[path_str]:
                loc_line = node.line_num
                loc_column = node.depth     # uses tab characters
                LINT.push(LintTreeDuplicateFolder(
                    node=node,
                    location=my_location.Location(
                        file=tree_file,
                        loc_line=loc_line,
                        loc_column=loc_column,
                        loc_index=line_map.get_abs_index(loc_line, loc_column),
                    )
                ))
            else:
                seen_children[path_str].add(node.name)

    # check that there are no duplicates
    asset_names: set[str] = set()
    for asset_type in CLUSTERABLE_ASSETS:
        # check if given asset type exist in the project
        if not asset_type.type_is_used(PROJECT):
            continue

        # populate namespace
        assets_from_index = list(asset_type.type_discover_names(PROJECT))
        assets_set = set(assets_from_index)
        if len(assets_from_index) != len(assets_set):
            dupes = [
                item
                for item, count in collections.Counter(
                    assets_from_index
                ).items()
                if count > 1
            ]
            LINT.push(LintTreeDuplicateAsset(
                dupes=dupes,
                message_pref='Duplicate assets in one type'
            ))
        inters = asset_names.intersection(assets_set)
        if inters:
            LINT.push(LintTreeDuplicateAsset(
                dupes=inters,
                message_pref='Duplicate assets across multiple types'
            ))
        asset_names.update(assets_set)

        # collect errors before parsing tree.yyd
        LINT.consume()

        # check tree.yyd for builtin assets
        if not issubclass(asset_type, my_asset.AssetBuiltin):
            continue

        # get assets from index, validate uniqueness
        asset_lint_tree(asset_type)

    # collect all errors
    LINT.consume()

    # MD: If you got no duplicates messages in the output then you're all good.
    # --- COG_END: MAIN_EX_LINT_TREE ---


class LintAliasMismatch(my_lint.LinterViolationMessage):

    rule = 'A100'
    severity = my_lint.Severity.WARNING

    def __init__(self, dupes: col.Iterable[str], message_pref: str):
        super().__init__()
        self.dupes = tuple(dupes)
        self.message_pref = message_pref

    @override
    @property
    def message(self) -> str:
        return f"{self.message_pref}: {' '.join(self.dupes)}"


def main_ex_aliases() -> list[Asset]:
    """Generate clusters and fix inconsistencies in cluster map.

    We will autogenerate our clusters by their top level folder name. After
    doing that, you may encounter things like different clusters ``"StageA"``
    and ``"stage_a"`` (project didn't follow strict naming), as well as a
    bunch of things that should belong to Common cluster
    (Backgrounds, Game, etc.).

    Which is easily fixed by a simple alias system for the clusters.
    """
    # --- COG_START: MAIN_EX_ALIASES ---
    assets: list[Asset] = []

    # ALIAS linter: find existing names in ALIAS
    lint_existing_aliases: set[str] = set()
    for name, clusters in ALIAS.items():
        for cluster in clusters:
            lint_existing_aliases.add(cluster)
            lint_existing_aliases.add(name)

    # this will help us generate the table below
    table_type_2_clusters: dict[type[Asset], list[str]] = {}

    # ALIAS linter: find actually used names in ALIAS
    lint_used_aliases: set[str] = set()
    for asset_type in CLUSTERABLE_ASSETS:
        if not asset_type.type_is_used(PROJECT):
            continue

        cluster_set: set[str] = set()
        for asset in asset_type.type_discover_all(PROJECT):
            # add both generated cluster and its alias
            cluster = asset_cluster(asset)
            lint_used_aliases.add(asset_cluster_raw(asset))
            lint_used_aliases.add(cluster)

            cluster_set.add(cluster)

            assets.append(asset)

        table_type_2_clusters[asset_type] = list(cluster_set)

    # generate the table
    clusters_all = sorted(
        {name for clusters in table_type_2_clusters.values() for name in clusters}
    )
    print('All clusters:', *clusters_all)
    for asset_type, clusters in table_type_2_clusters.items():
        cluster_set = set(clusters)
        row = [
            clm if clm in cluster_set else ' ' * len(clm)
            for clm in clusters_all
        ]
        print(f'[{asset_type.type_name():>10}]:', '|'.join(row))

    # lint
    lint_unused_aliases = lint_existing_aliases - lint_used_aliases
    lint_extra_aliases = lint_used_aliases - lint_existing_aliases
    if lint_unused_aliases:
        LINT.push(LintAliasMismatch(
            dupes=lint_unused_aliases,
            message_pref='Unused aliases'
        ))
    if lint_extra_aliases:
        # after the initial project setup, I'd upgrade this to raise
        LINT.push(LintAliasMismatch(
            dupes=lint_extra_aliases,
            message_pref='Extra aliases'
        ))
    LINT.consume()
    LINT.assert_empty()
    # MD: Keep using the table thing until all aliases are gone.
    # --- COG_END: MAIN_EX_ALIASES ---
    return assets


def main_ex_scan_sync(assets: list[Asset]) -> list[Dependency]:
    """Simple scanner.

    Before running dependency builder we need to set up scanning
    for the actual dependencies.

    We compile Aho-Corasick automaton to quickly scan every text
    (script or metadata file) in the project for asset references.

    Found asset references precisely reflect occurences in static code.
    In later steps we will artificially add some unreflected dependencies
    (such as persistent object existing potentially in every room). But
    such manipulations should not be done on resulting dependency list,
    but rather later, by injecting edges inside graph build process.

    Also, for pure data registry scripts (like ``sound_balance``), which,
    technically reference every asset, but don't instantiate them,
    we added a special directive: ``//!clunkster: ignore``. Add it in any
    GML scripts that should be skipped.
    """
    # --- COG_START: MAIN_EX_SCAN_SYNC ---
    automaton = Automaton()
    for asset in assets:
        automaton.add_word(asset.name, asset.name)
    automaton.make_automaton()

    dependencies: list[Dependency] = []

    name2asset = {asset.name: asset for asset in assets}
    total_matches = 0
    scans = tuple(
        (asset, file_path)
        for asset in assets
        for file_path in asset_scannables(asset, PROJECT)
    )
    for asset, file_path in tqdm.tqdm(
            scans, total=len(scans), desc='Scanning'
    ):
        text = my_read.read(file_path)
        line_map = my_read.line_map(file_path)
        matches: list[my_analyze_scan_dep.DependencyMatch] = list(
            my_analyze_scan_dep.scan(
                text,
                automaton.iter(text),
            )
        )

        total_matches += len(matches)
        for match in matches:
            line, column = line_map.get_line_col(match.idx)
            dependencies.append(
                Dependency(
                    location=my_location.Location(
                        file=file_path,
                        loc_index=match.idx,
                        loc_line=line,
                        loc_column=column,
                    ),
                    source_asset=asset,
                    target_asset=name2asset[match.target],
                    contexts=match.contexts,
                )
            )

    print(f'\nDone! Found {total_matches} total dependency references.')
    # --- COG_END: MAIN_EX_SCAN_SYNC2 ---
    return dependencies
    # --- COG_END: MAIN_EX_SCAN_SYNC ---


class LintAssetCluster(my_lint.LinterViolationAsset, ABC):
    """Group linter list output by assets' clusters."""

    @override
    @classmethod
    def format_many(cls, errors: col.Iterable[Self], *, verbose: bool = False) -> str:
        errors = list(errors)
        if not errors:
            return f"=== {cls.rule}: no issues"

        # group by clusters
        cluster_errors: dict[str, list[Self]] = {}
        for err in errors:
            asset = err.asset
            cluster_errors.setdefault(asset_cluster(asset), []).append(err)

        lines = [f"=== {cls.rule}: {len(errors)} issue(s) across {len(cluster_errors)} clusters:"]
        for cluster, errors in sorted(cluster_errors.items()):
            lines.append(f'\n=== {cluster} ===')

            # sort
            errors.sort(key=lambda e: asset_sort_key(e.asset))
            for err in errors:
                if verbose:
                    lines.append(err.format_verbose())
                else:
                    lines.append(f"  {err.format_li()}")

        return "\n".join(lines)


class LintUnused(LintAssetCluster):
    rule = 'U100'
    severity = my_lint.Severity.WARNING

    def __init__(self, asset: Asset) -> None:
        super().__init__()
        self._asset = asset

    @override
    @property
    def asset(self) -> Asset:
        return self._asset


def main_ex_lint_unused(
    dependencies: list[Dependency], assets: list[Asset]
) -> None:
    """Find and report assets that are never referenced by anything.

    Removing unused assets is a quick way to clean up a project.
    We can do this with a simple set difference: Total Assets
    minus Used Assets.

    This will not catch isolated reference loops (e.g., A references B,
    B references A, but neither is used by the main game).

    Also, some things that are indirectly referenced by the engine (like
    with rooms and ``room_goto_next()``) might still get reported.

    Take the output of this with a grain of salt.
    """
    # --- COG_START: MAIN_EX_LINT_UNUSED ---
    all_assets = {asset.name: asset for asset in assets}

    # populate used set from dependencies
    used_asset_names: set[str] = set()
    for dep in dependencies:
        # ignore self-references
        if dep.source_asset.name == dep.target_asset.name:
            continue
        used_asset_names.add(dep.target_asset.name)

    orphan_names = set(all_assets.keys()) - used_asset_names
    for name in orphan_names:
        LINT.push(LintUnused(all_assets[name]))

    # unwrap
    violations_cnt = LINT.consume(LintUnused)
    if violations_cnt:
        print(f"\nFound {violations_cnt} violations.")
    else:
        print("\nSomehow all clear...")
    # --- COG_END: MAIN_EX_LINT_UNUSED ---


class LintCrossref(my_lint.LinterViolationLocated, LintAssetCluster, my_lint.LinterViolationMessage):
    rule = 'C100'
    severity = my_lint.Severity.ERROR

    def __init__(self, dependency: Dependency) -> None:
        super().__init__()
        self._dependency = dependency

    @override
    @property
    def location(self) -> Location:
        return self._dependency.location

    @override
    @property
    def asset(self) -> Asset:
        return self._dependency.source_asset

    @override
    @property
    def message(self) -> str:
        # hack: use message (appended to the end) for dep repr.
        target = self._dependency.target_asset
        ctx = self._dependency.contexts
        ctx_str = f' [Contexts: {", ".join(ctx)}]' if ctx else ''
        return (
            f"{target.name} [{asset_cluster(target)}]"
            f'{ctx_str}'
        )


def main_ex_lint_crossref(dependencies: list[Dependency]) -> None:
    """Validate cluster boundaries.

    Simple check of clusters on both ends of dependency edge will filter
    out the majority of "stageA object referenced stageB asset" cases.

    However, this iteration (and following linters) have a few special rules:

    1. Most clusters are allowed to reference only themselves and Common
    cluster, but some may need to reference certain more localized "common"
    cluster. Such as when one collab maker creates multiple stages, and has
    many common scripts and util objects shared between them, but, technically,
    not between the rest of the collab. Such rules should be defined in
    ``LINT_RULES``.

    2. We allow special context guard scripts in a form of:

    ::

        if room_is_stageA() {
            ...
        }

    Those guards allow references to any foreign cluster inside them. Such
    guards must be defined in ``CONTEXT_RULES``.

    3. References to rooms are severed. Since the only way to meaningfully
    "reference" a room is to go there, for all intents and purposes reference
    whatever references a room doesn't really depend on it.

    Make sure to fill in the ``LINT_RULES`` and ``CONTEXT_RULES`` - they'll
    be used by future linters.
    """
    # --- COG_START: MAIN_EX_LINT_CROSSREF ---
    for dep in dependencies:
        source = dep.source_asset
        target = dep.target_asset

        source_cluster = asset_cluster(source)
        target_cluster = asset_cluster(target)

        # remove deps to room
        if isinstance(target, my_asset.Room):
            continue

        # get permissions from lint rules
        allowed_targets = set(
            LINT_RULES.get(source_cluster, {source_cluster, 'Common'})
        )

        # expand permissions based on script guards
        for ctx in dep.contexts:
            if ctx in CONTEXT_RULES:
                granted_primaries = CONTEXT_RULES[ctx]

                # look up what the primary cluster knows
                for primary in granted_primaries:
                    expanded_permissions = LINT_RULES.get(
                        primary, {primary, 'Common'}
                    )
                    allowed_targets.update(expanded_permissions)

        # check for structural violations
        if target_cluster not in allowed_targets:
            LINT.push(LintCrossref(dep))

    violations_cnt = LINT.consume(LintCrossref)
    if violations_cnt:
        print(f"\nFound {violations_cnt} violations.")
    else:
        print("\nClear!!!")

    # MD: Unlike the unused asset linter (which should be viewed more as
    # MD: "suggester"), the crossref linters are *required* to be happy,
    # MD: before you may start with the actually useful tools.
    # MD:
    # MD: From the following examples, the only useful ones until you
    # MD: clear out the dependency linter, are about trimming
    # MD: more unused assets via dependency graph.
    # --- COG_END: MAIN_EX_LINT_CROSSREF ---


def main_ex_graph(
    assets: list[Asset], dependencies: list[Dependency]
) -> dict[str, RoomGraph]:
    """Build dependency graph.

    Now that we have all dependency edges we may now do more complicated
    tracing via building graphs (for which I use rustworkx). Our main
    application of this graph would be finding a set of used assets in
    each room, to feed into linters.

    There's one limitation, however. Our context guards depend on the current
    room being processed. This means that we would have to modify the edges
    to match each room. To do this cleanly, we group rooms by their cluster
    sets.

    Also notice that World object (which is typically spawned only in
    the first room of the game, but persists for all rooms) might get
    only considered to exist in their spawn room. You should mark such
    ubiquitous assets as ``EXTRA_ROOTS``, so they get artificially added into
    the reachability sets.

    You might also notice that, along with reachability sets, we are saving
    graphs and data to translate graph output. This is only used for
    better output in some of the latter tools, so if such data ever becomes
    a bottleneck (which I HIGHLY doubt) you may omit those and only calculate
    ``reachability_map:dict[str,set[str]]``
    """
    # --- COG_START: MAIN_EX_GRAPH ---

    def build_graph(
        active_clusters: set[str],
    ) -> tuple[rx.PyDiGraph, dict[str, int]]:
        g = rx.PyDiGraph()

        asset_name2index: dict[str, int] = {}

        for asset in assets:
            # add_node() returns the rx's assigned node id
            asset_name2index[asset.name] = g.add_node(asset.name)

        e = 0
        for dep in dependencies:
            source_idx = asset_name2index[dep.source_asset.name]
            target_idx = asset_name2index[dep.target_asset.name]

            # delete references to rooms
            if isinstance(dep.target_asset, my_asset.Room):
                continue

            # context guards (nested guards intersect)
            if dep.contexts:
                edge_can_execute = True

                for raw_ctx in dep.contexts:
                    # get granted clusters for guard

                    # room must satisfy this guard to proceed deeper into
                    #   the nested guards
                    granted_clusters = CONTEXT_RULES.get(raw_ctx)
                    if granted_clusters and not active_clusters.intersection(
                        granted_clusters
                    ):
                        edge_can_execute = False
                        break

                if not edge_can_execute:
                    continue

            e += 1
            g.add_edge(source_idx, target_idx, None)

        return g, asset_name2index

    # group rooms by their allowed clusters
    cluster_groups: dict[frozenset[str], list[my_asset.Room]] = {}

    for asset_room in filter_type(my_asset.Room, assets):
        room_cluster = asset_cluster(asset_room)
        allowed_clusters = LINT_RULES.get(
            room_cluster, {room_cluster, 'Common'}
        )
        cluster_groups.setdefault(frozenset(allowed_clusters), []).append(
            asset_room
        )

    print('Clusterset to rooms:')
    for cluster_set, rooms in cluster_groups.items():
        print(*cluster_set)
        for room in rooms:
            print(' ', room.name)
        print()

    room_graph_data: dict[str, RoomGraph] = {}

    # process clustersets
    print('Building graphs:')
    clusterset_names_len = max(
        len(' '.join(cluster_set)) for cluster_set in cluster_groups
    )
    for cluster_set, rooms in cluster_groups.items():
        graph, name_to_index = build_graph(set(cluster_set))

        # resolve persistent root indices
        persistent_idx = [
            name_to_index[p] for p in EXTRA_ROOTS if p in name_to_index
        ]

        task_name = ' '.join(sorted(cluster_set)).rjust(clusterset_names_len)

        for room in tqdm.tqdm(
            rooms, desc=task_name, leave=True, file=sys.stdout
        ):
            room_name = room.name
            if room_name not in name_to_index:
                continue

            room_idx = name_to_index[room_name]

            # get direct descendants
            reachable_indices = rx.descendants(graph, room_idx)
            # inject persistent stuff
            for p_idx in persistent_idx:
                # add descendants of persistent stuff
                reachable_indices.update(rx.descendants(graph, p_idx))

                # add the thing itself
                reachable_indices.add(p_idx)

            reachable_names = {graph[idx] for idx in reachable_indices}
            room_graph_data[room_name] = RoomGraph(
                room=room,
                reachable_names=reachable_names,
                graph=graph,
                name2index=name_to_index,
            )

    # --- COG_END: MAIN_EX_GRAPH ---

    return room_graph_data


def main_ex_lint_unused_graph(
    assets: list[Asset], room_graph_data: dict[str, RoomGraph]
) -> None:
    """Identify unreachable assets.

    With our newly build reachability map we can indentify which assets are
    never referenced in any room. This would solve closed loops we've
    been skipping over in simpler linter.
    """
    # --- COG_START: MAIN_EX_LINT_UNUSED_GRAPH ---

    # master set
    all_used_names: set[str] = set()

    # extract reachability map
    reachability_map = {
        room_name: data.reachable_names
        for room_name, data in room_graph_data.items()
    }

    # add reachable descendants
    for reachable_set in reachability_map.values():
        all_used_names.update(reachable_set)

    # we must explicitly add the Rooms (edges to them
    #  were severed in the previous step)
    all_used_names.update(
        asset.name for asset in assets if isinstance(asset, my_asset.Room)
    )

    # detect unuseds
    for asset in assets:
        if asset.name in all_used_names:
            continue
        LINT.push(LintUnused(asset))

    violations_cnt = LINT.consume(LintUnused)
    if violations_cnt:
        print(f'\nFound {violations_cnt} unreachable assets.')
    else:
        print("\nClear??? omg")
    # --- COG_END: MAIN_EX_LINT_UNUSED_GRAPH ---


class LintCrossrefGraph(my_lint.LinterViolationAsset):
    rule = 'C101'
    severity = my_lint.Severity.ERROR

    def __init__(self, room: my_asset.Room, room_allowed_clusters: set[str], target_name: str, target_cluster: str, trace: str) -> None:
        super().__init__()
        self.room = room
        self.room_allowed_clusters = room_allowed_clusters
        self.target_name = target_name
        self.target_cluster = target_cluster
        self.trace = trace

    @override
    @property
    def asset(self) -> Asset:
        return self.room

    @override
    @classmethod
    def format_many(cls, errors: col.Iterable[Self], *, verbose: bool = False) -> str:
        errors = list(errors)
        if not errors:
            return f"=== {cls.rule}: no issues"

        # group by clusters
        cluster_errors: dict[str, list[Self]] = {}
        rooms_allowed_clusters: dict[str, set[str]] = {}
        for err in errors:
            room = err.room
            cluster_errors.setdefault(asset_cluster(room), []).append(err)
            if room.name not in rooms_allowed_clusters:
                rooms_allowed_clusters[room.name] = err.room_allowed_clusters

        lines = [f"=== {cls.rule}: {len(errors)} issue(s) across {len(cluster_errors)} clusters:"]
        for cluster, errors in sorted(cluster_errors.items()):
            lines.append(f'\n=== {cluster} ===')
            # sort
            errors.sort(key=lambda e: asset_sort_key(e.room))
            # group by room
            room_errors: dict[str, list[Self]] = {}
            for err in errors:
                room = err.room
                room_errors.setdefault(room.name, []).append(err)
            for room, errors in sorted(room_errors.items()):
                lines.append(f'Violations in Room: {room}')
                lines.append(f'-- Allowed Clusters: {" ".join(rooms_allowed_clusters[room])}')

                # group by target
                target_errors: dict[str, list[Self]] = {}
                for err in errors:
                    target_errors.setdefault(err.target_name, []).append(err)
                for target, errors in sorted(target_errors.items()):
                    lines.append(f'  [{errors[0].target_cluster}] {target}')
                    for err in errors:
                        lines.append(f'    {err.trace}')

        return "\n".join(lines)


def main_ex_lint_crossref_graph(
    assets: list[Asset],
    room_graph_data: dict[str, RoomGraph],
) -> None:
    """Validate room and their dependencies clustering boundaries.

    Final step of linting process before the project would be qualified for
    destructive (and actually useful) tools in validating cluster boundaries
    on rooms as a whole.

    Note 1: this tool is intended to be used only after resolved every
    issue raised by simpler crossref linter.

    Note 2: this tool will output a lot of violations for each offending
    dependency edge, therefore some deduction is required in order to pinpoint
    the exact offenders. Also, I recommend re-running the tool after each fix.
    """

    # --- COG_START: MAIN_EX_LINT_CROSSREF_GRAPH ---

    # asset clusters lookup
    asset_to_cluster: dict[str, str] = {
        asset.name: asset_cluster(asset) for asset in assets
    }
    total_violations = 0

    for rg in room_graph_data.values():
        room_cluster = asset_to_cluster.get(rg.room.name)
        if not room_cluster:
            continue

        allowed_clusters = LINT_RULES.get(
            room_cluster, {room_cluster, 'Common'}
        )

        illegal_assets: list[str] = []
        for reached_name in rg.reachable_names:
            reached_cluster = asset_to_cluster.get(reached_name)
            if reached_cluster and reached_cluster not in allowed_clusters:
                illegal_assets.append(reached_name)

        if not illegal_assets:
            continue

        room_idx = rg.name2index[rg.room.name]
        illegal_assets.sort(key=lambda name: asset_to_cluster.get(name, ''))

        # pre-resolve active persistent root ids
        active_persistent_roots = [
            (p_name, rg.name2index[p_name])
            for p_name in EXTRA_ROOTS
            if p_name in rg.name2index
        ]

        for illegal_name in illegal_assets:
            target_idx = rg.name2index[illegal_name]
            target_cluster = asset_to_cluster.get(illegal_name, 'Unknown')
            total_violations += 1

            path_found = False

            # trace 1 - room contamination
            room_paths = rx.dijkstra_shortest_paths(
                rg.graph, room_idx, target_idx
            )
            if target_idx in room_paths:
                path_names = [rg.graph[idx] for idx in room_paths[target_idx]]
                LINT.push(LintCrossrefGraph(
                    room=rg.room,
                    room_allowed_clusters=allowed_clusters,
                    target_name=illegal_name,
                    target_cluster=target_cluster,
                    trace=f'Traceback via Room Root: {" -> ".join(path_names)}'
                ))
                path_found = True

            # trace 2 - implicit contamination via global controllers
            for p_name, p_idx in active_persistent_roots:
                p_paths = rx.dijkstra_shortest_paths(
                    rg.graph, p_idx, target_idx
                )
                if target_idx in p_paths:
                    path_names = [rg.graph[idx] for idx in p_paths[target_idx]]
                    LINT.push(LintCrossrefGraph(
                        room=rg.room,
                        room_allowed_clusters=allowed_clusters,
                        target_name=illegal_name,
                        target_cluster=target_cluster,
                        trace=f'Traceback via Persistent Root ({p_name}): {" -> ".join(path_names)}'
                    ))

                    path_found = True
                    break

            if not path_found:
                LINT.push(LintCrossrefGraph(
                    room=rg.room,
                    room_allowed_clusters=allowed_clusters,
                    target_name=illegal_name,
                    target_cluster=target_cluster,
                    trace='Traceback: Path unknown (Possibly misconfigured structure)'
                ))

        if total_violations > 1000:  # noqa: PLR2004
            print('\nLinter exceeded 1000 violations, bailing out')
            break
    violations_cnt = LINT.consume(LintCrossrefGraph)
    if violations_cnt:
        print(f'Found {violations_cnt} violations')
    else:
        print('Awesome!')
    # MD: Once you've cleared this one, you may call the game qualified
    # MD: for using the dangerous toys down the line.
    # MD:
    # MD: Congrats on defeating the tutorial boss.
    # --- COG_END: MAIN_EX_LINT_CROSSREF_GRAPH ---


def main_juicer_copy(assets: list[Asset]) -> None:
    """Copy project's folder into build dir.

    Once you get all the cross-cluster linters happy, we can start optimizing
    the project. We will start with Project Juicer, and our first step
    is to copy the project into a build directory, and replace every asset
    from it with dry stubs, save for ones that are in Common cluster.

    The dry stubs that I used for my project are provided in repo's
    ``data/dry`` folder.

    I should note that we will only be "juicing" backgrounds, sprites and
    external audio (from gm82snd). Other assets don't impact RAM enough
    to worry about them.

    Once you run this tool, check that: your project gets successfully coped,
    projects opens in Game Maker, and all the non-Common assets get replaced
    with stubs. If all of these checks out, then you can do the next step.

    Btw, the project will open, but it won't be ready for playing, because
    we deleted all the audio. When you run the game, it will very soon crash
    due to unknown sound. This issue will be solved at the end of the Juicer
    pipeline... for now you'll have to live with it.
    """
    # --- COG_START: MAIN_EX_JUICER_COPY ---
    # clear build folder
    if JUICER.dir_out.exists():
        # check that JUICER's out dir is part of the project just to be safe
        # remove this check if necessary
        # assert PROJECT in JUICER.dir_out.parents
        shutil.rmtree(JUICER.dir_out)

    # exclude Common assets from ignoring audio copy
    paths_unignore: set[Path] = set()
    for asset in assets:
        if asset.cluster != 'Common':
            continue
        # hardcode this for now (we'll fix later)
        if not isinstance(asset, (AssetExtSfx, AssetExtSfx3, AssetExtBgm)):
            continue
        paths_unignore.add(asset.file)

    sfx_dir = AssetExtSfx.type_get_dir(PROJECT)
    sfx3_dir = AssetExtSfx3.type_get_dir(PROJECT)
    bgm_dir = AssetExtBgm.type_get_dir(PROJECT)

    def _ignore_audio(dir_path: str, dir_contents: list[str]) -> list[str]:
        """Callback for copytree to skip copying audio, except Common."""
        path = Path(dir_path)

        if (
            path.is_relative_to(sfx_dir)
            or path.is_relative_to(bgm_dir)
            or path.is_relative_to(sfx3_dir)
        ):
            ignored_items = []

            for content in dir_contents:
                content_path = path / content

                # ignore files outside unignore whitelist
                if (
                    content_path.is_file()
                    and content_path not in paths_unignore
                ):
                    ignored_items.append(content)

            return ignored_items

        # ignore nothing
        return []

    print('Copying project...')
    shutil.copytree(PROJECT, JUICER.dir_out, ignore=_ignore_audio)

    stub_img = JUICER.dir_dry / (
        'img_prod.png' if JUICER.is_prod else 'img_dev.png'
    )

    print('Injecting dry stubs...')
    # inject dry stubs
    for asset in assets:
        if asset.cluster == 'Common':
            continue

        if isinstance(asset, my_asset.Sprite):
            meta = asset.get_sprite_metadata(JUICER.dir_out)
            for image_index in range(meta.frames):
                img = asset.get_sprite_image(JUICER.dir_out, image_index)
                shutil.copyfile(stub_img, img)
        elif isinstance(asset, my_asset.Background):
            meta = asset.get_background_metadata(JUICER.dir_out)
            if not meta.exists:
                raise ValueError('Empty backgrounds are not allowed')
            shutil.copyfile(
                stub_img, asset.get_background_image(JUICER.dir_out)
            )

    # --- COG_END: MAIN_EX_JUICER_COPY ---


# --- COG_START: DEF_OBJ_FIX_MASK ---
def obj_fix_mask(obj: my_asset.Object, gml_path: Path, dir_out: Path) -> None:
    """Fix objects masks not updating when replacing sprites."""
    # exact action blocks, we'll validate against that;
    #  notice that endings are deliberately LF, that's how .gm82 save
    #  format works

    target_event = '#define Other_4'  # Room Start

    # "Execute a piece of code"
    block_603 = (
        '/*"/*\'/**//* YYD ACTION\n'
        'lib_id=1\n'
        'action_id=603\n'
        'applies_to=self\n'
        '*/\n'
    )

    # "Call the parent's event"
    block_604 = (
        '/*"/*\'/**//* YYD ACTION\nlib_id=1\naction_id=604\ninvert=0\n*/\n'
    )
    injection_code = 'mask_index=mask_index\n'

    # objects with no code (like SpikeLeft, SpikeRight and SpikeDown
    #  being just children of SpikeUp with no alterations other than
    #  sprite) should have their code created
    if not gml_path.exists():
        gml_path.touch()

    gml_text = gml_path.read_text(encoding='utf-8')
    # check that the text was properly saved with LFs
    assert '\r\n' not in gml_text

    # check different cases
    if target_event in gml_text:
        # CASE A: Room Start already exists

        # split event at event declaration and its trailing newline
        parts = gml_text.split(target_event + '\n')

        if len(parts) != 2:  # noqa: PLR2004
            # handle edge case where the event is at the very end of
            #  the file with no trailing newline
            if gml_text.endswith(target_event):
                parts = gml_text.split(target_event)
                parts[1] = '\n'
            else:
                raise ValueError(
                    f'Validation Error: Multiple Room Start events or '
                    f"malformed structure found in '{obj.name}.gml'."
                )

        event_body = parts[1]

        if event_body.startswith(block_603):
            # CASE A1: starts with a code block
            offset = len(block_603)
            new_event_body = (
                event_body[:offset] + injection_code + event_body[offset:]
            )
            print(obj.name, '- A1: starts with a code block')

        elif event_body.startswith(block_604 + block_603):
            # CASE A2: starts with call parent, followed by a code block
            offset = len(block_604) + len(block_603)
            new_event_body = (
                event_body[:offset] + injection_code + event_body[offset:]
            )
            print(
                obj.name,
                '- A2: starts with call parent, followed by a code block',
            )

        elif event_body.startswith(block_604):
            # CASE A3: starts with call parent, without any code blocks
            # append a new code block
            offset = len(block_604)
            new_event_body = (
                event_body[:offset]
                + block_603
                + injection_code
                + event_body[offset:]
            )
            print(
                obj.name,
                '- A3: starts with call parent without code block '
                'afterward???',
            )
            warnings.warn(
                f'Object {obj.name} starts with call parent without '
                f'code block??? Investigate.',
                stacklevel=2,
            )
        else:
            # idk
            raise ValueError(
                f'Validation Error: YYD ACTION match '
                f"failed in '{obj.name}.gml'. The block immediately "
                f"following '{target_event}' does not match YYD ACTION "
                f'603 or 604 patterns.'
            )

        # rebuild, maintain LF
        new_text = parts[0] + target_event + '\n' + new_event_body
        gml_path.write_text(new_text, encoding='utf-8', newline='\n')
    else:
        # CASE B: Room Start doesn't exist
        meta = obj.get_object_metadata(dir_out)
        # objects with no parent have this string blank
        has_parent = bool(meta.parent)

        # append the event into the file

        # check newline
        #  since we could've just created the file, it is allowed
        #  to be empty
        if gml_text and not gml_text.endswith('\n'):
            gml_text += '\n'

        new_block = target_event + '\n'
        if has_parent:
            # CASE B1: use the "Call parent event" block
            new_block += block_604
            print(
                obj.name,
                '- B1: no room start + has parent, must add Call parent event',
            )
        else:
            print(obj.name, '- B2: no room start')

        # add the code block and injection
        new_block += block_603 + injection_code
        gml_text += new_block

        gml_path.write_text(gml_text, encoding='utf-8', newline='\n')


# --- COG_END: DEF_OBJ_FIX_MASK ---


def main_juicer_fix_masks(assets: list[Asset]) -> None:
    """Before we continue, we must fix one annoying GameMaker bug.

    If you replace a sprite via ``sprite_replace_sprite``, it will not update
    collision data for objects that use sprite. We'll have to do it manually
    by injecting ``mask_index=mask_index`` into Room Start event of
    every object.

    Now, this fix isn't as trivial, since we have to inject code into objects,
    making sure we solve every configuration preciely, without generating
    unintended cases.

    For this reason, we validate against specific action definitions, and raise
    errors at a sight of any inconsistency. If your project frequently  uses
    some substandard Room Start pattern than the ones we handle in this script,
    feel free to modify it.

    To elaborate on exact cases solved:

    - A. Object already has Room Start event (line "#define Other_4" found)
        - A1. Room Start starts with a code block (block 603)
            - append the injected code after the action signature
        - A2. Room Start starts with "Call parent's event" (block 604),
            followed by a code block
            - inject into the code block (tehcnically, the right
              thing would be to inject it before "Call parent's event",
              but, since this fix is applied to ALL objects, parent's
              Room Start also has the mask fix)
        - A3. Room Start starts with "Call parent's event", but not followed
            by a code block (for whatever reason)
            - create a new code block and inject right there (though I added
              a warning for such cases, and you should investigate them)
    - B. Object has no Room Start event
        - B1. Object has a parent
            - add "Call parent's event" block and a code block with inject
              afterward
        - B2. Object has no parent
            - add just a code blck with inject

    """
    # --- COG_START: MAIN_EX_JUICER_FIX_MASKS ---
    print('Injecting collision mask fixes into objects...')

    objects = filter_type(my_asset.Object, assets)
    for obj in tqdm.tqdm(objects, desc='Injecting fixes into objects...'):
        # use output dir, since that's where we'll be writing
        gml_path = obj.get_object_gml_file(JUICER.dir_out)
        obj_fix_mask(obj, gml_path, JUICER.dir_out)
    # --- COG_END: MAIN_EX_JUICER_FIX_MASKS ---


# --- COG_START: DEF_PTH_GET_WET ---
def pth_get_wet(dir_wet_cluster: Path, asset: my_asset.AssetFile) -> Path:
    """Gen wet file location.

    :param dir_wet_cluster: Wet root directory, including cluster name
      (e.g. data/chunks/StageA/)
    :param asset: Asset to get wet filename of.
    :return: Resulting wet filename.
    """
    if isinstance(asset, AssetExtSfx):
        fname = f'{asset.name[1:-1]}.wav'
    elif isinstance(asset, (AssetExtSfx3, AssetExtBgm)):
        fname = f'{asset.name[1:-1]}.ogg'
    elif isinstance(asset, my_asset.Sprite):
        fname = f'{asset.name}.gmspr'
    elif isinstance(asset, my_asset.Background):
        fname = f'{asset.name}.gmbck'
    else:
        raise NotImplementedError('Asset type not supported')

    wet_type_dir = dir_wet_cluster / type(asset).type_get_dir_rel()
    return wet_type_dir / fname


# --- COG_END: DEF_PTH_GET_WET ---


# --- COG_START: DEFS_JUICE ---
def juice_sprite(
    sprite: my_asset.Sprite, project_root: Path, out_file: Path
) -> None:
    """Juice a sprite into external ``.gmspr`` file.

    :param sprite: Sprite object.
    :param project_root: Project root directory.
    :param out_file: File to write resulting ``.gmspr`` bytes to.
    """
    # read original metadata
    meta = sprite.get_sprite_metadata(project_root)

    frames_bgra: list[bytes] = []
    width, height = 0, 0

    for image_index in range(meta.frames):
        img_path = sprite.get_sprite_image(project_root, image_index)
        with Image.open(img_path) as img:
            img = img.convert('RGBA')
            if width == 0:
                width, height = img.size
            frames_bgra.append(img.tobytes('raw', 'BGRA'))

    assert meta.frames == len(frames_bgra)

    # map metadata
    gm_meta = gmc_model.GmsprMeta.default()
    # gm_meta.version = 800
    gm_meta.width = width
    gm_meta.height = height
    gm_meta.subimage_count = len(frames_bgra)
    gm_meta.origin_x = meta.origin_x
    gm_meta.origin_y = meta.origin_y

    gm_meta.mask_kind = meta.collision_shape
    gm_meta.mask_tolerance = meta.alpha_tolerance
    gm_meta.separate_masks = meta.per_frame_colliders
    gm_meta.bbox_kind = meta.bbox_type
    gm_meta.bbox_left = meta.bbox_left
    gm_meta.bbox_right = meta.bbox_right
    gm_meta.bbox_bottom = meta.bbox_bottom
    gm_meta.bbox_top = meta.bbox_top

    gmc_validate.gmspr_validate(gm_meta, frames_bgra)
    payload = gmc_core.gmspr_build_payload(gm_meta, frames_bgra)

    out_file.write_bytes(gmc_file.file_pack(payload))


def juice_background(
    bg: my_asset.Background, project_root: Path, out_file: Path
) -> None:
    """Juice a background into external ``.gmbck`` file.

    :param bg: Background object.
    :param project_root: Project root directory.
    :param out_file: File to write resulting ``.gmbck`` bytes to.
    """
    # read the original metadata
    meta = bg.get_background_metadata(project_root)

    # meta.exists == 0 was already filtered out
    img_path = bg.get_background_image(project_root)
    with Image.open(img_path) as img:
        img = img.convert('RGBA')
        width, height = img.size
        pixel_data = img.tobytes('raw', 'BGRA')

    gm_meta = gmc_model.GmbckMeta.default()
    # gm_meta.version = ...
    gm_meta.use_as_tile = meta.tileset
    gm_meta.tile_width = meta.tile_width
    gm_meta.tile_height = meta.tile_height
    gm_meta.tile_h_offset = meta.tile_hoffset
    gm_meta.tile_v_offset = meta.tile_voffset
    gm_meta.tile_h_sep = meta.tile_hsep
    gm_meta.tile_v_sep = meta.tile_vsep
    # gm_meta.image_version = ...
    gm_meta.width = width
    gm_meta.height = height

    gmc_validate.gmbck_validate(gm_meta, pixel_data)
    payload = gmc_core.gmbck_build_payload(gm_meta, pixel_data)

    out_file.write_bytes(gmc_file.file_pack(payload))


def juice_audio(audio: AssetExtAudio, out_file: Path) -> None:
    """Juice audio into a compressed format.

    :param audio: External audio.
    :param out_file: File to write result to.
    """
    if isinstance(audio, AssetExtSfx):
        # FMOD kind 0 (RAM): compress to MS ADPCM 22050Hz
        subprocess.run(  # noqa: S603
            [  # noqa: S607
                'ffmpeg',
                '-i',
                str(audio.file),
                '-y',
                '-c:a',
                'pcm_s16le',
                '-ar',
                '44100',
                str(out_file),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        # FMOD kind 1/3 (Stream): compress to low-bitrate Ogg Vorbis
        subprocess.run(  # noqa: S603
            [  # noqa: S607
                'ffmpeg',
                '-i',
                str(audio.file),
                '-y',
                # kill anything that isn't first audio stream from input 0
                '-map',
                '0:a:0',
                # kill any cover art just in case
                '-vn',
                '-map_metadata',
                '-1',
                '-c:a',
                'libvorbis',
                '-q:a',
                '3',
                str(out_file),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


# --- COG_END: DEFS_JUICE ---


def main_juicer_gen_wet(assets: list[Asset]) -> None:
    """Copying works, time to extract wet assets.

    For this process we'll convert sprites and backgrounds into
    ``.gmspr`` and ``.gmbck`` files for easier loading on game maker side,
    music and sounds will be compressed. Refer to [Dehydration](#dehydration)
    for more info.

    Encoding images into the Game Maker's formats was done via my awesome
    library [gmcodec](https://github.com/shaperones0/gmcodec).

    Compressing audio was done via FFmpeg. Normally I'd postpone any
    optimization passes until the pipeline is done, but the audio compression
    one was too easy to insert for me to miss out.

    As an unfortunate side effect, the process now takes around a minute
    to finish... We'll address that once we are done with v1 of the pipeline.
    Until then - suffer.
    """
    # --- COG_START: MAIN_EX_JUICER_GEN_WET ---
    dir_wet = JUICER.dir_out / JUICER.rel_dir_wet
    if dir_wet.exists():
        shutil.rmtree(dir_wet)

    print('Generating wet assets (compression & encoding)...')

    for asset in tqdm.tqdm(
        list(filter_type(my_asset.Sprite, assets)),
        desc='Encoding sprites...',
    ):
        wet_file = pth_get_wet(dir_wet / asset.cluster, asset)
        wet_file.parent.mkdir(parents=True, exist_ok=True)
        juice_sprite(asset, PROJECT, wet_file)

    for asset in tqdm.tqdm(
        list(filter_type(my_asset.Background, assets)),
        desc='Encoding backgrounds...',
    ):
        wet_file = pth_get_wet(dir_wet / asset.cluster, asset)
        wet_file.parent.mkdir(parents=True, exist_ok=True)
        juice_background(asset, PROJECT, wet_file)

    for asset in tqdm.tqdm(
        list(filter_type(AssetExtSfx, assets))
        + list(filter_type(AssetExtSfx3, assets))
        + list(filter_type(AssetExtBgm, assets)),
        desc='Compressing audio...',
    ):
        wet_file = pth_get_wet(dir_wet / asset.cluster, asset)
        wet_file.parent.mkdir(parents=True, exist_ok=True)
        juice_audio(asset, wet_file)

    # --- COG_END: MAIN_EX_JUICER_GEN_WET ---


def main_juicer_gen_gml(assets: list[Asset]) -> None:  # noqa: PLR0915
    """It is time to finally integrate Clunkster into the project.

    Here's the static scripts that you'll have to add:

    - ``clunkster_init()``: Initialized Clunkster's variables.
    - ``clunkster_room_start()``: Clunkster's Room Start event, cleans up
      all unused assets.
    - ``clunkster_room_goto(target_room)``: A ``room_goto`` replacement
      that ensures all assets are loaded for target room.
    - ``clunkster_registry_begin()``: Toggles registry mode on.
    - ``clunkster_is_reg()``: Returns registry mode status.
    - ``clunkster_registry_end()``: Toggles registry mode off.

    And the following scripts will be autogenerated in this step. You should
    still add them - we'll be filling them in this step, instead of
    creating. In raw project those are usually empty.

    - ``clunkster_gen_type()``: Returns ``"dev"`` or ``"prod"`` in a built
      project. Returns ``""`` in the raw source project.
    - ``clunkster_gen_init_audio()``: Initializes audio stubs.
    - ``clunkster_gen_get_room_clusters(target_room)``: Populates the required
      cluster map.
    - ``clunkster_gen_hydrate_cluster(cluster_name)``: Loads assets.
    - ``clunkster_gen_dehydrate_cluster(cluster_name)``: Unloads assets
      (replaces them with ``dry`` stubs to reduce RAM).

    Following describes the base implementation of those scripts, as well
    as some tips on where they should be called.

    1. ``clunkster_init()`` - Initializes Clunkster logic

    .. code-block:: gml

        ///clunkster_init()
        //Initialize Clunkster globals

        global.__clunk_reg_mode=0
        global.__clunk_active_clusters=ds_map_create()
        global.__clunk_req_clusters=ds_map_create()

    See example of proper Game Start logic below.

    2. ``clunkster_room_start()`` - System's Room Start event, responsible
      for cleaning up unloaded assets.

    .. code-block:: gml

        ///clunkster_room_start()
        //Clunkster's Room Start event
        //Cleanup cluster no longer needed for this room

        var _key,_next;
        _key=ds_map_find_first(global.__clunk_active_clusters)

        while is_string(_key) {
            _next=ds_map_find_next(global.__clunk_active_clusters,_key)
            if not ds_map_exists(global.__clunk_req_clusters,_key) {
                //this cluster is no longer needed
                clunkster_gen_dehydrate_cluster(_key)
                ds_map_delete(global.__clunk_active_clusters,_key)
            }
            _key=_next
        }

    Put it at Room Start, in some ``World``-like object.

    3. ``clunkster_room_goto(target_room)`` - Interceptor of ``room_goto``
      calls, which is responsible for loading any asset required by target
      room.

    .. code-block:: gml

        ///clunkster_room_goto(room)
        //Intercept room_goto and load necessary clusters

        ds_map_clear(global.__clunk_req_clusters)
        clunkster_gen_get_room_clusters(argument0)

        var _key;
        _key=ds_map_find_first(global.__clunk_req_clusters)
        repeat ds_map_size(global.__clunk_req_clusters) {
            if !ds_map_exists(global.__clunk_active_clusters,_key) {
                //must be loaded
                clunkster_gen_hydrate_cluster(_key)
                ds_map_add(global.__clunk_active_clusters,_key,1)
            }
            _key=ds_map_find_next(global.__clunk_req_clusters,_key)
        }

        room_goto(argument0)

    Notice that you'll have to replace every ``room_goto`` call with this
      function, and never use any other methods of room change.

    Next are registry-related functions.

    4. ``clunkster_registry_begin()`` - Switch registry mode ON.

    .. code-block:: gml

        ///clunkster_registry_begin()

        global.__clunk_reg_mode=1

    5. ``clunkster_registry_end()`` - Switch registry mode OFF.

    .. code-block:: gml

        ///clunkster_registry_end()

        global.__clunk_reg_mode=0

    6. ``clunkster_is_reg()`` - Check whether in registry mode.

    .. code-block:: gml

        ///clunkster_is_reg()
        //Check whether in registry mode

        return global.__clunk_reg_mode

    And finally, the autogenerated scripts. In raw project they can remain
    empty.

    7. ``clunkster_gen_type()``

    .. code-block:: gml

        ///clunkster_gen_type()
        //Returns the type of project.
        //Expect "dev" for builds with no dynamic asset loading
        //Expect "prod" for builds with dynamic asset loading
        //Expect "" for raw projects

        //This script is autogenerated by Clunkster.

        return ""

    8. ``clunkster_gen_init_audio()``

    .. code-block:: gml

        ///clunkster_gen_init_audio()
        //Initialize audio sources with stubs
        //sound_add_ext("null.wav",kind,streamed,"snd_actual")

        //This script is autogenerated by Clunkster.

    9. ``clunkster_gen_get_room_clusters(target_room)``

    .. code-block:: gml

        ///clunkster_gen_get_room_clusters(target_room)
        //Get clusters that must be loaded for given room
        //Populates global.__clunk_req_clusters

        //This script is autogenerated by Clunkster.

    10. ``clunkster_gen_hydrate_cluster(cluster_name)``

    .. code-block:: gml

        ///clunkster_gen_hydrate_cluster(cluster_name)
        //Loads data from specified cluster in one block

        //This script is autogenerated by Clunkster.

    11. ``clunkster_gen_dehydrate_cluster(cluster_name)``

    .. code-block:: gml

        ///clunkster_gen_dehydrate_cluster(cluster_name)
        //Unloads data from specified cluster in one block

        //This script is autogenerated by Clunkster.

    What are the registries? Basically, if you wanna have some values
    associated with a externalized resource, that should be applied whenever
    its loaded, you can simply put such data in a ``dsmap`` and add some
    logic for loading and applying those values

    For example, if you have some values associated with audio source (like
    volume balancing, original sample rate, loops), you can create a
    registry, like this ``sndreg``:

    ``sndreg_init``:

    .. code-block:: gml

        ///sndreg_init()
        //Initialize sound registry

        global._sndreg=ds_map_create()
        global._sndlist=ds_list_create()

    ``sndreg_ext`` - Fills in all data of an audio at once:

    .. code-block:: gml

        ///sndreg_ext(snd,og_samplerate=44100,vol=1,[loopstart,loopend=-1])
        //Fill in all params at once

        //reg
        if !ds_map_exists(global._sndreg,argument0+":REG") {
            ds_list_add(global._sndlist,argument0)
            dsmap(global._sndreg,argument0+":REG",1)
        }

        //rate
        var _rate;if argument_count>1 _rate=argument[1] else _rate=44100
        dsmap(global._sndreg,argument0+":RATE",_rate)

        //vol
        var _vol;if argument_count>2 _vol=argument[2] else _vol=1
        dsmap(global._sndreg,argument0+":VOL",_vol)

        //loop
        if argument_count>3 {
            dsmap(global._sndreg,argument0+":LA",argument[3])
            var _le;
            if argument_count>4 _le=argument[4] else _le=-1
            dsmap(global._sndreg,argument0+":LB",_le)
        }

    ``sndreg_populate`` - This is where you define all those values:

    .. code-block:: gml

        ///sndreg_populate()
        //Populate sound registry with necessary sound data

        sndreg_ext("block_break",44100)
        sndreg_ext("block_change",44100,0.8)
        sndreg_ext("boss_hit",44100,0.8)
        sndreg_ext("cherry_trap",44100,0.6)
        sndreg_ext("get_item",44100)
        sndreg_ext("glass",44100)

        if room_is_ice_stage() {
            sndreg_ext("ice_melt",44100)
        }

    ``sndreg_apply`` - Apply registry values to a sound:

    .. code-block:: gml

        ///sndreg_apply(snd)
        if sound_exists(argument0) {
            //volume
            var _vol;_vol=dsmap(global._sndreg,argument0+":VOL")
            if is_undefined(_vol) _vol=1
            sound_volume(argument0,_vol)

            //loop
            var _ls;_ls=dsmap(global._sndreg,argument0+":LA")
            if not is_undefined(_ls) {
                var _le;_le=dsmap(global._sndreg,argument0+":LB")
                if is_undefined(_le) _le=-1

                //scale samplerate to accound for compression
                var _scaled_start,_scaled_end;
                _scaled_start=sndreg_scale_sample(argument0,_ls)

                if _le==-1 {
                    _scaled_end=sound_get_length(argument0,unit_samples)
                }
                else {
                    _scaled_end=sndreg_scale_sample(argument0,_le)
                }
                sound_set_loop(
                    argument0,
                    _scaled_start,_scaled_end,unit_samples
                )
            }
        }
        else {
            show_error(str_ins(
                "sndreg_apply: Sound '%' doesn't exist",argument0
            ),0)
        }

    ``sndreg_apply_all`` - Apply registry values to all registered sounds; this
      one should be used right after registry population, if project type
      is raw.

    .. code-block:: gml

        ///sndreg_apply_all()
        //Apply audio stuff to all sounds

        var _i,_ac,_snd;
        _ac=ds_list_size(global._sndlist)
        for (_i=0;_i<_ac;_i+=1) {
            _snd=ds_list_find_value(global._sndlist,_i)
            sndreg_apply(_snd)
        }

    This allows us to write a clean Game Start logic:

    .. code-block:: gml

        clunkster_registry_begin()
        sndreg_populate()
        clunkster_registry_end()
        if clunkster_gen_type() == "" {
            //all audio is internal and loaded, run audio balance
            sndreg_apply_all()
        }
        else {
            //we are in 'dev' or 'prod' build, generate stubs
            clunkster_gen_init_audio()
        }

    With that out of the way we may start on the autogenerating GML scripts.
    Now - this is the part where most of the project variability would kick in.
    Things like:

    1. What kinds of routines should be called on each loaded assets
    2. How do you register external assets
    3. What way of dehydration in runtime works best for you

    etc.

    You'll have to look at the code and edit those moments in manually.

    In this particular project, the dehydration was implemented according to
    [the respective section of this readme](#dehydration).

    Also, notice that in this implementation we load everything
    synchronously in one block, resulting in 1-5 second stutters during
    loads. I don't think such low loading time create a need for things like
    loading screens.

    Notice the humongous number of functions. That's a secret tool that will
    come in handy later.
    """
    # --- COG_START: MAIN_EX_JUICER_GEN_GML ---
    print('Generating Clunkster scripts...')

    dir_scripts = my_asset.Script.type_get_dir(JUICER.dir_out)

    scr_gen_type = dir_scripts / 'clunkster_gen_type.gml'
    scr_gen_init_audio = dir_scripts / 'clunkster_gen_init_audio.gml'
    scr_gen_get_room_clusters = (
        dir_scripts / 'clunkster_gen_get_room_clusters.gml'
    )
    scr_gen_hydrate_cluster = dir_scripts / 'clunkster_gen_hydrate_cluster.gml'
    scr_gen_dehydrate_cluster = (
        dir_scripts / 'clunkster_gen_dehydrate_cluster.gml'
    )
    scr_gen_validate_ctx = dir_scripts / 'clunkster_gen_validate_ctx.gml'

    assert all(
        scr.exists()
        for scr in [
            scr_gen_type,
            scr_gen_init_audio,
            scr_gen_get_room_clusters,
            scr_gen_hydrate_cluster,
            scr_gen_dehydrate_cluster,
        ]
    ), "One of the generated scripts wasn't found"

    # filter clusterable assets
    assets_bgm: list[AssetExtBgm] = []
    assets_sfx: list[AssetExtSfx] = []
    assets_sfx3: list[AssetExtSfx3] = []
    assets_spr: list[my_asset.Sprite] = []
    assets_bg: list[my_asset.Background] = []
    assets_rooms: list[my_asset.Room] = []  # needed for scripts

    asset_name_to_file_wet: dict[str, str] = {}
    dehydrated_clusters: set[str] = set()
    for asset in assets:
        if asset.cluster == 'Common':
            # skip common assets
            continue

        dehydrated_clusters.add(asset.cluster)

        # populate specific array
        if isinstance(asset, AssetExtBgm):
            assets_bgm.append(asset)
        elif isinstance(asset, AssetExtSfx):
            assets_sfx.append(asset)
        elif isinstance(asset, AssetExtSfx3):
            assets_sfx3.append(asset)
        elif isinstance(asset, my_asset.Sprite):
            assets_spr.append(asset)
        elif isinstance(asset, my_asset.Background):
            assets_bg.append(asset)
        elif isinstance(asset, my_asset.Room):
            assets_rooms.append(asset)
            continue
        else:
            continue

        # get wet file location
        dir_wet = JUICER.dir_out / JUICER.rel_dir_wet / asset.cluster
        asset_name_to_file_wet[asset.name] = str(
            pth_get_wet(dir_wet, asset).relative_to(JUICER.dir_out)
        )

    # common params for writing anything related to game maker
    text_params = {'encoding': 'utf-8', 'newline': '\n'}

    # write the clunkster_gen_type

    # technically, Project Juicer is in prod configuration, as far as the
    #  game is concerned, even if we use dev stubs instead of prod stubs
    scr_gen_type.write_text('return "prod"', **text_params)

    # write the clunkster_gen_get_room_clusters
    gml_deps = [
        '///clunkster_gen_get_room_clusters(target_room)',
        '// AUTOGENERATED BY CLUNKSTER JUICER',
        'switch (argument0) {',
    ]

    cluster_to_rooms: dict[str, list[str]] = {}
    for room in assets_rooms:
        cluster_to_rooms.setdefault(room.cluster, []).append(room.name)

        needed_clusters = set(
            LINT_RULES.get(room.cluster, {room.cluster, 'Common'})
        )
        needed_clusters.discard('Common')

        gml_deps.extend(
            it.chain(
                (f'case {room.name}:',),
                (
                    f'    ds_map_add(global.__clunk_req_clusters,"{cl}",1)'
                    for cl in sorted(needed_clusters)
                ),
                ('    break',),
            )
        )

    gml_deps.append('}')
    scr_gen_get_room_clusters.write_text('\n'.join(gml_deps), **text_params)

    # write clunkster_gen_validate_ctx

    gml_validate = [
        '///clunkster_gen_validate_ctx()',
        '// AUTOGENERATED BY CLUNKSTER JUICER',
        'var _violations;_violations=""',
    ]

    for context_guard, allowed_clusters in CONTEXT_RULES.items():
        for clusters in allowed_clusters:
            gml_validate.extend(
                f'if not {context_guard}({room}) _violations+="Failed ctx '
                f'check on {room} and {context_guard}"+lf'
                for room in cluster_to_rooms.get(clusters, ())
            )
    gml_validate.append('if _violations!="" show_error(_violations,1)')

    scr_gen_validate_ctx.write_text('\n'.join(gml_validate), **text_params)

    # write the clunkster_gen_init_audio, prepare the code for music/sound

    stub_sfx = (
        f'data/dry/{"snd_prod.wav" if JUICER.is_prod else "snd_dev.wav"}'
    )
    stub_sfx3 = (
        f'data/dry/{"snd3_prod.ogg" if JUICER.is_prod else "snd3_dev.ogg"}'
    )
    stub_bgm = (
        f'data/dry/{"mus_prod.ogg" if JUICER.is_prod else "mus_dev.ogg"}'
    )
    stub_bg = (
        f'data/dry/{"bg_prod.gmbck" if JUICER.is_prod else "bg_dev.gmbck"}'
    )
    stub_spr = (
        f'data/dry/{"spr_prod.gmspr" if JUICER.is_prod else "spr_dev.gmspr"}'
    )

    gml_gen_init_audio = [
        '///clunkster_gen_init_audio()',
        '// AUTOGENERATED BY CLUNKSTER JUICER',
        f'var _p_sfx;_p_sfx="{stub_sfx}"',
        f'var _p_sfx3;_p_sfx3="{stub_sfx3}"',
        f'var _p_bgm;_p_bgm="{stub_bgm}"',
    ]

    cluster_load_code: dict[str, list[str]] = {}
    cluster_unload_code: dict[str, list[str]] = {}

    for asset in assets_bgm + assets_sfx + assets_sfx3:
        clean_name = asset.name[1:-1]

        if isinstance(asset, AssetExtBgm):
            stub_var = '_p_bgm'
            kind = 1
            streamed = 1
            preload = 1
        elif isinstance(asset, AssetExtSfx):
            stub_var = '_p_sfx'
            kind = 0
            streamed = 0
            preload = 1
        else:
            stub_var = '_p_sfx3'
            kind = 3
            preload = 2
            streamed = 1

        # populate init code
        gml_gen_init_audio.append(
            f'sound_add_ext({stub_var},{kind},{streamed},"{clean_name}")'
        )

        # populate load code
        pth_wet = asset_name_to_file_wet[asset.name]
        cluster_load_code.setdefault(asset.cluster, []).append(
            f'    sound_replace({asset.name},"{pth_wet}",{kind},{preload}) '
            f'sndreg_apply({asset.name})'
        )
        # populate unload code
        cluster_unload_code.setdefault(asset.cluster, []).append(
            f'    sound_replace({asset.name},{stub_var},{kind},{preload})'
        )

    scr_gen_init_audio.write_text('\n'.join(gml_gen_init_audio), **text_params)

    # prepare the code for sprites/backgrounds

    for asset in assets_spr:
        # no need for any init code
        pth_wet = asset_name_to_file_wet[asset.name]
        cluster_load_code.setdefault(asset.cluster, []).append(
            f'    sprite_replace_sprite({asset.name},"{pth_wet}")'
        )
        cluster_unload_code.setdefault(asset.cluster, []).append(
            f'    sprite_replace_sprite({asset.name},_p_spr)'
        )

    for asset in assets_bg:
        # no need for any init code
        pth_wet = asset_name_to_file_wet[asset.name]
        cluster_load_code.setdefault(asset.cluster, []).append(
            f'    background_replace_background({asset.name},"{pth_wet}")'
        )
        cluster_unload_code.setdefault(asset.cluster, []).append(
            f'    background_replace_background({asset.name},_p_bg)'
        )

    gml_hydrate = [
        '///clunkster_gen_hydrate_cluster(cluster_name)',
        '// AUTOGENERATED BY CLUNKSTER JUICER',
        'switch (argument0) {',
    ]
    gml_dehydrate = [
        '///clunkster_gen_dehydrate_cluster(cluster_name)',
        '// AUTOGENERATED BY CLUNKSTER JUICER',
        f'var _p_sfx;_p_sfx="{stub_sfx}"',
        f'var _p_sfx3;_p_sfx3="{stub_sfx3}"',
        f'var _p_bgm;_p_bgm="{stub_bgm}"',
        f'var _p_spr;_p_spr="{stub_spr}"',
        f'var _p_bg;_p_bg="{stub_bg}"',
        'switch (argument0) {',
    ]

    for cluster in sorted(dehydrated_clusters):
        gml_hydrate.append(f'case "{cluster}":')
        gml_dehydrate.append(f'case "{cluster}":')

        gml_hydrate.extend(cluster_load_code.get(cluster, []))
        gml_dehydrate.extend(cluster_unload_code.get(cluster, []))

        gml_hydrate.append('    break')
        gml_dehydrate.append('    break')

    gml_hydrate.append('}')
    gml_dehydrate.append('}')

    scr_gen_hydrate_cluster.write_text('\n'.join(gml_hydrate), **text_params)
    scr_gen_dehydrate_cluster.write_text(
        '\n'.join(gml_dehydrate), **text_params
    )

    # MD: Once the GML files are generated and integrated, the project
    # MD: should become launchable and playable. Once you verify that, you
    # MD: continue onto the improved version of Project Juicer below.
    # --- COG_END: MAIN_EX_JUICER_GEN_GML ---


# --- COG_START: CLS_TASKS ---
class TaskAsset[TAsset: my_asset.AssetFile](my_proj_task.Task, ABC):
    """Generic asset-based task."""

    @abstractmethod
    def _get_asset(self) -> my_asset.AssetFile:
        """Get the asset that this tasks processes."""

    def get_asset(self) -> my_asset.AssetFile:
        """Get the asset that this tasks processes."""
        return self._get_asset()


class TaskEncodeBackground(TaskAsset[my_asset.Background]):
    """Encode background task."""

    def __init__(
        self,
        background: my_asset.Background,
        project_root: Path,
        dir_project_out: Path,
        dir_wet_cluster: Path,
        file_dry: Path,
    ) -> None:
        """Create the task from existing asset."""
        self.background = background
        self.project_root = project_root
        self.project_out = dir_project_out
        self.file_dry = file_dry

        # destination image (dry or as-is if Common)
        self.file_meta = background.get_background_metadata_file(project_root)
        self.out_img = background.get_background_image(dir_project_out)

        # add png into required outputs
        outputs = [self.out_img, self.file_meta]

        # add gmbck only if not common (commons won't be generating those)
        self.file_gmbck_output = pth_get_wet(dir_wet_cluster, background)
        if background.cluster != 'Common':
            outputs.append(self.file_gmbck_output)

        super().__init__(
            task_id=f'encode_bg_{background.name}',
            inputs=(
                background.get_background_metadata_file(project_root),
                background.get_background_image(project_root),
            ),
            outputs=outputs,
        )

    def _get_asset(self) -> my_asset.AssetFile:
        return self.background

    def execute(self) -> None:
        """Execute the task."""
        if self.background.cluster == 'Common':
            # raw copy
            src = self.background.get_background_image(self.project_root)
            dest = self.out_img
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
        else:
            # juice
            juice_background(
                self.background, self.project_root, self.file_gmbck_output
            )
            # stub
            dest = self.out_img
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(self.file_dry, dest)

        # always copy the metadata
        dest = self.project_out / self.file_meta.relative_to(self.project_root)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(
            self.file_meta,
            dest,
        )


class TaskEncodeSprite(TaskAsset[my_asset.Sprite]):
    """Encode sprite task."""

    def __init__(
        self,
        sprite: my_asset.Sprite,
        project_root: Path,
        dir_project_out: Path,
        dir_wet_cluster: Path,
        file_dry: Path,
    ) -> None:
        """Create the task from existing asset."""
        self.sprite = sprite
        self.project_root = project_root
        self.project_out = dir_project_out
        self.file_dry = file_dry

        self.file_meta = sprite.get_sprite_metadata_file(project_root)
        meta = sprite.get_sprite_metadata(project_root)

        # map destination images (dry or as-is if Common)
        self.out_imgs = [
            sprite.get_sprite_image(dir_project_out, i)
            for i in range(meta.frames)
        ]

        # add pngs into required outputs
        outputs = [*self.out_imgs, self.file_meta]

        # add gmspr only if not common (commons won't be generating those)
        self.file_gmspr_output = pth_get_wet(dir_wet_cluster, sprite)
        if sprite.cluster != 'Common':
            outputs.append(self.file_gmspr_output)

        super().__init__(
            task_id=f'encode_spr_{sprite.name}',
            inputs=(
                sprite.get_sprite_metadata_file(project_root),
                *(
                    sprite.get_sprite_image(project_root, i)
                    for i in range(meta.frames)
                ),
            ),
            outputs=outputs,
        )

    def _get_asset(self) -> my_asset.AssetFile:
        return self.sprite

    def execute(self) -> None:
        """Execute the task."""
        meta = self.sprite.get_sprite_metadata(self.project_root)
        if self.sprite.cluster == 'Common':
            # raw copy
            for i in range(meta.frames):
                src = self.sprite.get_sprite_image(self.project_root, i)
                dest = self.out_imgs[i]
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
        else:
            # juice
            juice_sprite(
                self.sprite, self.project_root, self.file_gmspr_output
            )
            # stub
            for dest in self.out_imgs:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(self.file_dry, dest)

        # always copy the metadata
        dest = self.project_out / self.file_meta.relative_to(self.project_root)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(
            self.file_meta,
            dest,
        )


class TaskCompressAudio(TaskAsset[AssetExtAudio]):
    """Compress audio task."""

    def __init__(
        self,
        audio: AssetExtAudio,
        project_root: Path,
        dir_project_out: Path,
        dir_wet_cluster: Path,
        _: Path,
    ) -> None:
        """Create the task from existing asset."""
        self.audio = audio
        self.project_root = project_root
        self.project_out = dir_project_out
        # there's no dry file for audio

        # Commons compress into data/music folder,
        #  non-Commons into data/chunks/whatever
        self.file_out_chunked = pth_get_wet(dir_wet_cluster, audio)
        self.file_out_raw = (
            dir_project_out
            / self.file_out_chunked.relative_to(dir_wet_cluster)
        )

        if audio.cluster == 'Common':
            self.file_output = self.file_out_raw
        else:
            self.file_output = self.file_out_chunked
        super().__init__(
            task_id=f'compress_{audio.name[1:-1]}',
            inputs=(audio.file,),
            outputs=(self.file_output,),
        )

    def _get_asset(self) -> my_asset.AssetFile:
        return self.audio

    def execute(self) -> None:
        """Execute the task."""
        # it might sound tempting to compress the Common audio as well,
        #  but you don't really wanna hear it
        if self.audio.cluster == 'Common':
            src = self.audio.file
            dest = self.file_output
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dest)
        else:
            juice_audio(self.audio, self.file_output)


class TaskFixMaskObjects(TaskAsset[my_asset.Object]):
    """Inject ``mask_index=mask_index`` on objects room start."""

    def __init__(
        self,
        obj: my_asset.Object,
        project_root: Path,
        dir_project_out: Path,
        dir_wet_cluster: Path,
        _: Path,
    ) -> None:
        """Mask fixer."""
        self.obj = obj
        self.project_root = project_root
        self.project_out = dir_project_out

        self.in_file_meta = obj.get_object_metadata_file(project_root)
        self.in_file_gml = obj.get_object_gml_file(project_root)

        self.out_file_meta = dir_project_out / self.in_file_meta.relative_to(
            self.project_root
        )
        self.out_file_gml = dir_project_out / self.in_file_gml.relative_to(
            self.project_root
        )

        super().__init__(
            task_id=f'fixmasks_{obj.name}',
            inputs=(self.in_file_meta, self.in_file_gml),
            outputs=(self.out_file_meta, self.out_file_gml),
        )

    def _get_asset(self) -> my_asset.AssetFile:
        return self.obj

    def execute(self) -> None:
        """Execute the task."""
        # inject the code into every object, regardless of common or not

        # feed project root into dir_out because idk that's the source FIXME
        obj_fix_mask(self.obj, self.out_file_gml, self.project_root)


class TaskFixBgStretchRooms(TaskAsset[my_asset.Room]):
    """Inject background stretch logic into room's ``code.gml``."""

    def __init__(
        self,
        room: my_asset.Room,
        project_root: Path,
        dir_project_out: Path,
        dir_wet_cluster: Path,
        _: Path,
    ) -> None:
        """Initialize room background stretch fixer."""
        self.room = room
        self.project_root = project_root
        self.project_out = dir_project_out

        self.in_file_meta = room.get_room_metadata_file(project_root)
        self.in_file_gml = room.get_room_gml_file(project_root)

        self.out_file_meta = dir_project_out / self.in_file_meta.relative_to(
            project_root
        )
        self.out_file_gml = dir_project_out / self.in_file_gml.relative_to(
            project_root
        )

        # all files and fields are guaranteed to exist
        meta = room.get_room_metadata(project_root)
        self.idx_stretch: list[int] = [
            i for i in range(8) if getattr(meta, f'bg_stretch{i}')
        ]
        self.gml_src = self.in_file_gml.read_text(encoding='utf-8')

        super().__init__(
            task_id=f'rm_fixstretch_{room.name}',
            inputs=(self.in_file_meta, self.in_file_gml),
            outputs=(self.out_file_meta, self.out_file_gml),
        )

    def _get_asset(self) -> my_asset.AssetFile:
        return self.room

    def execute(self) -> None:
        """Execute task."""
        code = self.gml_src
        if self.idx_stretch:
            lines = [
                '\n// --- CLUNKSTER BG STRETCH FIX ---',
                *(
                    f"""
if background_width[{i}]>0 && background_height[{i}]>0 {{
    background_xscale[{i}]=room_width/background_width[{i}]
    background_yscale[{i}]=room_height/background_height[{i}]
}}"""
                    for i in self.idx_stretch
                ),
            ]
            code = '\n'.join(lines) + '\n' + self.gml_src
        self.out_file_gml.write_text(code, encoding='utf-8')


class ProcessorGeneric[TAsset: my_asset.AssetFile](
    my_proj_processor.Processor
):
    """Generic asset type processor, processes all assets of the given type.

    Puts type's directory into ignore, expects task constructor
    signature to be (``asset``, ``project_root``, ``dir_wet_cluster``).
    """

    def __init__(
        self,
        cls_asset: type[TAsset],
        # bruuuuuuuuuuuuuuuuh
        cls_task: col.Callable[
            [TAsset, Path, Path, Path, Path], TaskAsset[TAsset]
        ],
        dir_wet: Path,
        file_dry: Path,
    ) -> None:
        """Initialize generic asset processor.

        :param cls_task: Class with a constructor signature of (``asset``,
          ``path_project_root``, ``path_project_out``, ``path_wet_cluster``,
          ``file_ry``)
        :param dir_wet: Exported assets directory, like ``data/chunks``.
        """
        self.cls_asset = cls_asset
        self.cls_task = cls_task
        self.dir_wet = dir_wet
        self.file_dry = file_dry

    def get_ignored_source_patterns(
        self, project_root: Path
    ) -> col.Iterable[str]:
        """Ignores entire directory of this asset type.

        :param project_root:
        :return:
        """
        # not a single day without hax
        dir_posix = self.cls_asset.type_get_dir_rel().as_posix()
        for ext_glob in self.cls_asset.type_globs():
            yield f'{dir_posix}/**/{ext_glob}'

    def generate_tasks(
        self, assets: col.Iterable[Asset], project_root: Path, dir_out: Path
    ) -> col.Iterable[my_proj_task.Task]:
        """Generate tasks for converting all assets of this type."""
        for asset in filter_type(self.cls_asset, assets):
            yield self.cls_task(
                asset,
                project_root,
                dir_out,
                self.dir_wet / asset.cluster,
                self.file_dry,
            )


class ProcessorRoomsPatch(my_proj_processor.Processor):
    """Processes rooms to fix background scaling."""

    def __init__(
        self,
        dir_wet: Path,
        file_dry: Path,
    ) -> None:
        """Initialize generic asset processor.

        :param dir_wet: Exported assets directory, like ``data/chunks``.
        """
        self.dir_wet = dir_wet
        self.file_dry = file_dry

    def get_ignored_source_patterns(
        self, project_root: Path
    ) -> col.Iterable[str]:
        """Get ignored patters.

        Don't hijack anything.
        """
        return []

    def generate_tasks(
        self, assets: col.Iterable[Asset], project_root: Path, dir_out: Path
    ) -> col.Iterable[my_proj_task.Task]:
        """Generate room fix tasks."""
        for room in filter_type(my_asset.Room, assets):
            yield TaskFixBgStretchRooms(
                room,
                project_root,
                dir_out,
                self.dir_wet / room.cluster,
                self.file_dry,
            )


# --- COG_END: CLS_TASKS ---


def main_juicer2_cls() -> tuple[
    my_proj_cache.FileBuildCache,
    my_proj_ignore.FileIgnore,
    tuple[my_proj_processor.Processor, ...],
]:
    """Let's upgrade the Juicer.

    Now that we've verified our project generation, we can optimize the
    two lengthiest parts of the pipeline: project copying and asset
    processing. We want to lower our build times down to 5-10 seconds on
    regular builds, which we'll do with the help of caching and
    multiprocessing.

    Now, caching and multiprocessing also means that we'll have to convert
    our code into atomic "tasks", that can be fed into a process pool executor
    and do their stuff from here. But this presents a bit of a challenge on its
    own - sending stuff between Python processes takes some effort. Python has
    to picke objects on one side, send it, and then unpickle on the other (_god
    i wish there was an easier way to do this lol_). So some cheap operations
    (like copying the bulk of the file count, ahem, rooms, ahem) can be done
    synchronously in-place (or via Python's threading). So that's why we'll
    split this pipeline into, again, copying the (bulk of the) project, and
    then the actual expensive tasks would be sent to ``ProcessPoolExecutor``.

    It's a good thing that Clunkster provides several utilities for such
    project conversions, one of them is a system of "tasks" (atomic conversion
    of one asset) and "processors" (factories, that walk through the
    asset/dependency lists and generate tasks).

    So let's write those processors and tasks. We'll reuse our logic from
    earlier examples. Notice that we have a bunch of separate logic for
    Common and non-Common assets. It is how it is.
    """
    # --- COG_START: MAIN_EX_JUICER2_CLS ---
    # setup build cache and ignore file while we're at it
    cl_cache = my_proj_cache.FileBuildCache(JUICER.file_cache)
    cl_ignore = my_proj_ignore.FileIgnore.from_file(JUICER.file_ignore)
    dir_wet = JUICER.dir_out / JUICER.rel_dir_wet
    cl_processors = (
        ProcessorGeneric(
            my_asset.Background,
            TaskEncodeBackground,
            dir_wet,
            JUICER.dir_dry
            / f'{"img_prod.png" if JUICER.is_prod else "img_dev.png"}',
        ),
        ProcessorGeneric(
            my_asset.Sprite,
            TaskEncodeSprite,
            dir_wet,
            JUICER.dir_dry
            / f'{"img_prod.png" if JUICER.is_prod else "img_dev.png"}',
        ),
        ProcessorGeneric(
            AssetExtBgm,
            TaskCompressAudio,
            dir_wet,
            Path(),  # dummy
        ),
        ProcessorGeneric(AssetExtSfx, TaskCompressAudio, dir_wet, Path()),
        ProcessorGeneric(AssetExtSfx3, TaskCompressAudio, dir_wet, Path()),
        ProcessorGeneric(my_asset.Object, TaskFixMaskObjects, dir_wet, Path()),
        ProcessorRoomsPatch(dir_wet, Path()),
    )
    # --- COG_END: MAIN_EX_JUICER2_CLS ---
    return cl_cache, cl_ignore, cl_processors


def main_juicer2_copy(
    cl_cache: my_proj_cache.FileBuildCache,
    cl_ignore: my_proj_ignore.FileIgnore,
    cl_processors: col.Iterable[my_proj_processor.Processor],
) -> None:
    """Let's address the copying problem first.

    We can make a makeshift "copy tasks" by constructing cache entries by hand.
    This does make the first copy a bit slower than our initial version,
    but this time we get to skip over most of the assets on subsequent builds.

    This results in around 5-10 seconds on first launch and 1-2 seconds on
    subsequent ones (we still do calculate hashes of every file duh).

    Also don't forget to preserve Common assets as is.
    """
    # --- COG_START: MAIN_EX_JUICER2_COPY ---
    print('Syncing project files...')

    # processor ignores
    proc_ignore_patterns: list[str] = []
    for proc in cl_processors:
        proc_ignore_patterns.extend(proc.get_ignored_source_patterns(PROJECT))
    procs_rex = [
        re.compile(fnmatch.translate(pat)) for pat in proc_ignore_patterns
    ]

    stat_copied = 0
    stat_skipped = 0

    all_files = [p for p in PROJECT.rglob('*') if p.is_file()]
    for src_path in tqdm.tqdm(all_files, desc='Copying project files'):
        rel_path = src_path.relative_to(PROJECT)
        rel_posix = rel_path.as_posix()

        # skip paths claimed by processors
        #  append / to ensure it matches dirs
        if any(
            pat.match(rel_posix) or pat.match(src_path.name)
            for pat in procs_rex
        ):
            continue

        # check clunksterignore
        if cl_ignore.is_ignored(rel_posix):
            continue

        # check cache
        dest_path = JUICER.dir_out / rel_path
        task_id = f'copy_{rel_posix}'
        current_hash = my_proj_cache.file_hash(src_path)
        if cl_cache.is_fresh(
            task_id=task_id,
            current_hash=current_hash,
            outputs=(dest_path,),
        ):
            stat_skipped += 1
            continue

        # copy and update cache
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_path, dest_path)
        cl_cache.update(task_id, current_hash)
        stat_copied += 1

    # don't save yet - wait until the next stage
    # cl_cache.save()
    print(f'Project synced: {stat_copied} updated, {stat_skipped} cached')
    # --- COG_END: MAIN_EX_JUICER2_COPY ---


def main_juicer2_mp(
    assets: list[Asset],
    cl_cache: my_proj_cache.FileBuildCache,
    cl_processors: col.Iterable[my_proj_processor.Processor],
) -> None:
    """This is it Luigi."""
    # --- COG_START: MAIN_EX_JUICER2_MP ---
    print('Generating tasks...')

    tasks: list[my_proj_task.Task] = []
    stat_cached = 0

    for proc in cl_processors:
        # 3rd param is unused doh
        for task in proc.generate_tasks(assets, PROJECT, JUICER.dir_out):
            current_hash = task.get_input_hash()

            if cl_cache.is_fresh(
                task_id=task.task_id,
                current_hash=current_hash,
                outputs=task.outputs,
            ):
                stat_cached += 1
            else:
                tasks.append(task)

    if not tasks:
        print(f'All assets are up to date! ({stat_cached} cached)')
    else:
        print(f'Processing {len(tasks)} assets')

        stat_success = 0
        stat_failed = 0

        with concurrent.futures.ProcessPoolExecutor() as executor:
            # submit to wrapper
            futures = [
                executor.submit(my_proj_task.worker_exec_task, task)
                for task in tasks
            ]

            future_iter = tqdm.tqdm(
                concurrent.futures.as_completed(futures),
                total=len(futures),
                desc='Juicing assets',
            )

            for future in future_iter:
                result = future.result()

                if result.success:
                    # cache update on success
                    cl_cache.update(result.task_id, result.new_hash)
                    stat_success += 1
                else:
                    print(
                        f'\n[FUCK] Task {result.task_id} failed:'
                        f'\n{result.error}'
                    )
                    stat_failed += 1

        cl_cache.save()
        print(f'Done: {stat_success} succeeded, {stat_failed} failed')

        if stat_failed > 0:
            raise RuntimeError('Pipeline halted due to aids')
    # MD: Don't forget to run our old GML generator after doing this step.
    # MD: Could also run Game Maker's CLI compile with `subprocess.Popen`
    # --- COG_END: MAIN_EX_JUICER2_MP ---


def main_juicer2_gm_compile() -> None:
    r"""One last step is automatic compile.

    Game Maker's CLI for compiling is:

    ::

        GameMaker.exe [project.gm82] --build [exe]

    And Game Maker's exe is usually at:

    ::

        C:\Users\user\AppData\Roaming\GameMaker8.2\GameMaker.exe

    but I also added a new environment variable ``GM82_PATH`` just for that
    one guy.
    """
    # --- COG_START: MAIN_EX_JUICER2_GM_COMPILE ---
    print('Jostling Game Maker 8.2 compiler...')

    project_file = JUICER.dir_out / JUICER.fname_gm82
    output_exe = JUICER.dir_out / 'game.exe'

    custom_path = os.getenv('GM82_PATH')
    if custom_path:
        gm_exe = Path(custom_path)
    else:
        appdata_str = os.getenv('APPDATA')
        if not appdata_str:
            raise RuntimeError(
                'Could not resolve APPDATA environment variable.'
            )

        appdata_path = Path(appdata_str)

        gm_exe = appdata_path / 'GameMaker8.2' / 'GameMaker.exe'

    if not gm_exe.exists():
        raise FileNotFoundError(
            f'GameMaker 8.2 compiler not found at:\n{gm_exe}\n'
            "If you have a custom installation, set the 'GM82_PATH' "
            'environment variable.'
        )

    print(f'Compiling {output_exe.name}...')

    try:
        subprocess.run(  # noqa: S603
            [str(gm_exe), str(project_file), '--build', str(output_exe)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
        )
        print('Build completely successfully!')
        subprocess.run(str(output_exe), cwd=JUICER.dir_out)  # noqa: S603

    except subprocess.CalledProcessError as e:
        raise RuntimeError(
            f'GameMaker 8.2 compilation failed with exit code {e.returncode}'
        ) from e
    # --- COG_END: MAIN_EX_JUICER2_GM_COMPILE ---


def _run_tutorials() -> None:
    main_ex_start()
    main_ex_aliases()

    assets = stage_discover_assets()
    main_ex_scan_sync(assets)


def test_tutorials() -> None:
    """Ensure the tutorial snippets don't rot."""
    global PROJECT
    dummy_proj = Path(__file__).parent / 'tests' / 'dummy_project'
    if not dummy_proj.exists():
        return  # skip if dummy project isn't set up yet
    PROJECT = dummy_proj

    # TODO dummy project and config

    _run_tutorials()


def _load_private(config_dir: Path) -> None:
    global PROJECT, ALIAS, LINT_RULES, CONTEXT_RULES, JUICER

    _file_private_config = config_dir / 'config.json'
    if not _file_private_config.exists():
        raise FileNotFoundError(
            f'Config file not found: {_file_private_config}'
        )

    _config = json.loads(_file_private_config.read_text())

    set_project(config_dir.parent / 'source')
    JUICER = ConfJuicer(
        is_prod=False,
        dir_out=config_dir.parent / '_build',
        dir_dry=JUICER.dir_dry,  # og dir
        rel_dir_wet=JUICER.rel_dir_wet,
        file_cache=config_dir.parent / 'clunkster_cache.json',
        file_ignore=config_dir.parent / '.clunksterignore',
        fname_gm82=_config['fname_gm82'],
    )

    _file_private_alias = config_dir / 'alias.json'
    ALIAS = json.loads(_file_private_alias.read_text(encoding='utf-8'))
    alias_invert()

    _file_private_lint_rules = config_dir / 'lint_rules.json'
    rules = json.loads(_file_private_lint_rules.read_text(encoding='utf-8'))
    LINT_RULES = {
        cluster: set(allowed_clusters)
        for cluster, allowed_clusters in rules.items()
    }

    _file_private_context_rules = config_dir / 'context_rules.json'
    rules = json.loads(_file_private_context_rules.read_text(encoding='utf-8'))
    CONTEXT_RULES = {
        cluster: set(allowed_clusters)
        for cluster, allowed_clusters in rules.items()
    }


def main() -> None:
    """Pipeline private entrypoint."""
    import sys

    _load_private(Path(sys.argv[1]))

    # allow testing tutorials on private data as well
    is_test = False
    is_check = True
    if len(sys.argv) > 2:  # noqa: PLR2004
        if sys.argv[2] == 'test':
            is_test = True
        elif sys.argv[2] == 'check':
            is_check = True

    if is_test:
        _run_tutorials()
        return

    main_ex_lint_tree()
    assets = main_ex_aliases()

    if is_check:
        deps = main_ex_scan_sync(assets)

        # main_ex_lint_unused(deps, assets)
        main_ex_lint_crossref(deps)

        room_data = main_ex_graph(assets, deps)

        # main_ex_lint_unused_graph(assets, room_data)
        main_ex_lint_crossref_graph(assets, room_data)

        print('All ok, exiting regardless :D')
        return

    cl_cache, cl_ignore, cl_processors = main_juicer2_cls()
    main_juicer2_copy(cl_cache, cl_ignore, cl_processors)
    main_juicer2_mp(assets, cl_cache, cl_processors)
    main_juicer_gen_gml(assets)
    main_juicer2_gm_compile()


if __name__ == '__main__':
    main()
