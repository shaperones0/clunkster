"""Main pipeline, together with examples."""

import collections
import collections.abc as col
import dataclasses
import itertools as it
import json
import multiprocessing as mp
import shutil
import subprocess
import sys
import time
import warnings
from concurrent import futures
from pathlib import Path

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

from clunkster import asset as my_asset
from clunkster.analyze import location as my_analyze_location
from clunkster.analyze import scan_dep as my_analyze_scan_dep
from clunkster.asset import Asset
from clunkster.parse import tree as my_parse_tree

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
class AssetExtBgm(my_asset.AssetExt):
    """External background music asset."""

    @classmethod
    def _type_name(cls) -> str:
        return 'DATA_BGM'

    @classmethod
    def _type_get_dir_rel(cls) -> Path:
        return Path('data') / 'music'


@dataclasses.dataclass(frozen=True, slots=True)
class AssetExtSfx(my_asset.AssetExt):
    """External sound effect asset."""

    @classmethod
    def _type_name(cls) -> str:
        return 'DATA_SFX'

    @classmethod
    def _type_get_dir_rel(cls) -> Path:
        return Path('data') / 'sounds'


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
CLUSTERABLE_BUILTINS: tuple[type[my_asset.Asset], ...] = (
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
CLUSTERABLE_ASSETS: tuple[type[my_asset.Asset], ...] = (
    *CLUSTERABLE_BUILTINS,
    AssetExtBgm,
    AssetExtSfx,
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
# --- COG_END: PROJECT ---


# --- COG_START: CLS_SCAN_JOB ---
@dataclasses.dataclass(frozen=True, slots=True)
class ScanJob:
    """A lightweight payload sent over IPC to a worker process.

    Uses frozen and slots to speed up transfer across processes.
    """

    asset_name: str
    file_path: Path


@dataclasses.dataclass(frozen=True, slots=True)
class ScanResult:
    """Result of a scan."""

    matches: list[my_analyze_scan_dep.DependencyMatch]
    job: ScanJob


# --- COG_END: CLS_SCAN_JOB ---


# --- COG_START: CLS_DEPENDENCY ---
@dataclasses.dataclass(frozen=True, slots=True)
class Dependency:
    """Full dependency data to be used in graph building."""

    location: my_analyze_location.BoundLocation
    source_asset: my_asset.Asset
    target_asset: my_asset.Asset
    contexts: tuple[str, ...]


# --- COG_END: CLS_DEPENDENCY ---
# --- COG_START: CLS_ROOM_GRAPH ---
@dataclasses.dataclass
class RoomGraph:
    """Bundle of room graph data."""

    room_name: str
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


JUICER = ConfJuicer(
    # start with dev builds
    is_prod=False,
    # use "_build" folder next to the project
    dir_out=Path('path/to/project/_build'),
    # if you downloaded Clunkster from source, then
    #  such is available in repository's /data/dry folder
    dir_dry=Path(__file__).parent / 'data' / 'dry',
    rel_dir_wet=Path('data') / 'chunks',
)
# --- COG_END: CLS_JUICER_CONFIG ---


# --- COG_START: REG_WORKERS_EXPLAIN ---
# we can't send the compiled Aho-Corasick automaton across process boundaries
#  safely; instead, we use a global variable inside the worker process and
#  initialize it once when the process boots up
# --- COG_END: REG_WORKERS_EXPLAIN ---
# --- COG_START: REG_WORKERS ---
_WORKER_AUTOMATON: Automaton | None = None


def _worker_init(asset_names: list[str]) -> None:
    """Initialize a worker process with its own local Aho-Corasick trie."""
    global _WORKER_AUTOMATON
    _WORKER_AUTOMATON = Automaton()
    for name in asset_names:
        _WORKER_AUTOMATON.add_word(name, name)
    _WORKER_AUTOMATON.make_automaton()


def _worker_scan(job: ScanJob) -> ScanResult:
    """Process worker's job."""
    assert _WORKER_AUTOMATON is not None

    text = job.file_path.read_text(encoding='utf-8')

    return ScanResult(
        matches=list(
            my_analyze_scan_dep.scan(
                text,
                _WORKER_AUTOMATON.iter(text),
            )
        ),
        job=job,
    )


# --- COG_END: REG_WORKERS ---


def main_ex_start() -> None:
    """Let's start with some simple scanning.

    We want to check that assets get detected correctly.
    Logic in provided ``clunkster.asset`` module already handles most of
    the discovery of both builtin and external assets, as well as automatic
    cluster assignment. However, it's likely that you'll want assets from
    folders ``sprStageA`` and ``bgStageA`` to end up in a unified cluster
    ``StageA``. This will be done a bit later.
    """
    # --- COG_START: MAIN_EX_START ---

    assets: list[Asset] = []

    for asset_type in CLUSTERABLE_ASSETS:
        # check if given asset type exist in the project
        if not asset_type.type_is_used(PROJECT):
            continue

        assets.extend(asset_type.type_iter(PROJECT))

    # you should investigate the resulting array for inconsistencies
    print(f'Discovered {len(assets)} total assets.')
    # --- COG_END: MAIN_EX_START ---


def main_ex_lint_tree() -> None:
    """Now we must check integrity of ``tree.yyd`` files and asset names.

    Asset discovery and clusterization is based on scanning ``tree.yyd``
    files, so we have to ensure that they have no duplicate folders.

    Technically, before doing that you should also check that there are also
    no duplicate asset names via broom icon on IDE toolbar.

    This code is quite large, however, most of it won't be relevant in later
    steps.
    """

    # --- COG_START: MAIN_EX_LINT_TREE ---
    def lint_tree(tree_lines: col.Iterable[str]) -> None:
        seen_children: dict[str, set[str]] = {}
        total_duplicates = 0

        for node in my_parse_tree.nodes(tree_lines):
            # format the tuple into path string (e.g., "/Player/SkinA")
            path_str = '/' + '/'.join(node.parent_path)

            if path_str not in seen_children:
                seen_children[path_str] = set()

            if node.name in seen_children[path_str]:
                print(
                    f'Duplicate {"Folder" if node.is_folder else "Asset???"}: '
                    f"'{node.name}' in {path_str} (Line {node.line_num})"
                )
                total_duplicates += 1
            else:
                seen_children[path_str].add(node.name)

    # check that there are no duplicates
    asset_names: set[str] = set()
    for asset_type in CLUSTERABLE_ASSETS:
        # check if given asset type exist in the project
        if not asset_type.type_is_used(PROJECT):
            continue

        # populate namespace
        assets_from_index = list(asset_type.type_iter_names(PROJECT))
        assets_set = set(assets_from_index)
        if len(assets_from_index) != len(assets_set):
            dupes = [
                item
                for item, count in collections.Counter(
                    assets_from_index
                ).items()
                if count > 1
            ]
            raise ValueError(
                f'Duplicate assets in one type: {" ".join(dupes)}'
            )
        inters = asset_names.intersection(assets_set)
        if inters:
            raise ValueError(
                f'Duplicate assets across multiple types: {" ".join(inters)}'
            )
        asset_names.update(assets_set)

        # check tree.yyd for builtin assets
        if not issubclass(asset_type, my_asset.AssetBuiltin):
            continue

        # get assets from index, validate uniqueness

        tree_file = asset_type.type_file_tree(PROJECT)
        print(f'Checking {tree_file} ...')
        lint_tree(tree_file.read_text(encoding='utf-8').splitlines())
    # MD: If you got no duplicates messages in the output then you're all good.
    # --- COG_END: MAIN_EX_LINT_TREE ---


def stage_discover_assets() -> list[Asset]:
    """Asset discovery pipeline stage.

    Removed various outputs and other useless shims.

    :return: List of found assets.
    """
    assets: list[Asset] = []

    # --- COG_START: MAIN_EX_ALIAS_GIST_INVERT ---
    # invert ALIAS
    cluster_to_name: dict[str, str] = {}
    for name, clusters in ALIAS.items():
        for cluster in clusters:
            if cluster in cluster_to_name:
                raise ValueError('Invalid ALIAS (duplicate aliases)')
            cluster_to_name[cluster] = name
    # --- COG_END: MAIN_EX_ALIAS_GIST_INVERT ---

    for asset_type in CLUSTERABLE_ASSETS:
        if not asset_type.type_is_used(PROJECT):
            continue

        for asset in asset_type.type_iter(PROJECT):
            # --- COG_START: MAIN_EX_ALIAS_GIST_ALIAS ---
            # MD: Then we apply aliasing in the asset iteration loop.
            alias = cluster_to_name.get(asset.cluster)
            if alias is not None:
                asset = dataclasses.replace(asset, cluster=alias)
            # --- COG_END: MAIN_EX_ALIAS_GIST_ALIAS ---

            assets.append(asset)
    return assets


def main_ex_aliases() -> list[Asset]:
    """Manually fix inconsistencies in cluster map.

    After we did initial scan, you may encounter inconsistencies like different
    clusters ``"StageA"`` and ``"stage_a"`` (project didn't follow strict
    naming), as well as a bunch of things that should belong to Common cluster
    (Backgrounds, Game, etc.).

    Which is easily fixed by a simple alias system for clusters.
    """
    # --- COG_START: MAIN_EX_ALIASES ---
    assets: list[Asset] = []

    # invert ALIAS
    cluster_to_name: dict[str, str] = {}
    existing_aliases: set[str] = set()
    for name, clusters in ALIAS.items():
        for cluster in clusters:
            if cluster in cluster_to_name:
                raise ValueError(
                    f'Invalid ALIAS (duplicate aliases {cluster})'
                )
            cluster_to_name[cluster] = name
            existing_aliases.add(cluster)
            existing_aliases.add(name)

    cluster_map: dict[str, list[str]] = {}
    asset_to_cluster: dict[type[Asset], list[str]] = {}
    used_aliases: set[str] = set()
    asset_name_set: set[str] = set()  # clean asset name issues
    for asset_type in CLUSTERABLE_ASSETS:
        if not asset_type.type_is_used(PROJECT):
            continue

        cluster_set: set[str] = set()
        for asset in asset_type.type_iter(PROJECT):
            alias = cluster_to_name.get(asset.cluster)
            used_aliases.add(asset.cluster)
            if alias is not None:
                asset = dataclasses.replace(asset, cluster=alias)
                used_aliases.add(alias)

            cluster_set.add(asset.cluster)
            cluster_map.setdefault(asset.cluster, []).append(asset.name)

            if asset.name in asset_name_set:
                raise ValueError(f'Duplicate asset name {asset.name}')
            asset_name_set.add(asset.name)

            assets.append(asset)

        asset_to_cluster[asset_type] = list(cluster_set)

    clusters_all = sorted(
        {name for clusters in asset_to_cluster.values() for name in clusters}
    )
    print('All clusters:', *clusters_all)
    for asset_type, clusters in asset_to_cluster.items():
        cluster_set = set(clusters)
        row = [
            clm if clm in cluster_set else ' ' * len(clm)
            for clm in clusters_all
        ]
        print(f'{asset_type.type_to_str_linter()}:', '|'.join(row))

    unused_aliases = existing_aliases - used_aliases
    extra_aliases = used_aliases - existing_aliases
    if unused_aliases:
        warnings.warn(
            f'Unused aliases: {" ".join(unused_aliases)}', stacklevel=2
        )
    if extra_aliases:
        warnings.warn(
            f'Extra aliases: {" ".join(extra_aliases)}', stacklevel=2
        )
    # MD: Keep using the table thing until all aliases are gone.
    # --- COG_END: MAIN_EX_ALIASES ---
    return assets


def main_ex_scan_sync(assets: list[Asset]) -> None:
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
    we added a special directive: ``//!clunkster: ignore``. Add it any
    GML scripts that should be skipped.

    This is a simple synchronous code, but in real projects scanning
    might take up 5-10 seconds.

    Multiprocessing version is available in later examples.
    """
    # --- COG_START: MAIN_EX_SCAN_SYNC ---
    automaton = Automaton()
    for asset in assets:
        automaton.add_word(asset.name, asset.name)
    automaton.make_automaton()

    total_matches = 0
    for asset in assets:
        for file_path in asset.get_scannables(PROJECT):
            text = file_path.read_text(encoding='utf-8')
            matches: list[my_analyze_scan_dep.DependencyMatch] = list(
                my_analyze_scan_dep.scan(
                    text,
                    automaton.iter(text),
                )
            )

            total_matches += len(matches)

            # print the first few matches just to prove it works
            if total_matches > 100:  # noqa: PLR2004
                continue
            for match in matches[:3]:
                loc = match.location
                print(
                    f'[{asset.name}] -> {match.target_asset} '
                    f'({file_path.name}:{loc.loc_line}:{loc.loc_column})'
                )

    print(f'\nDone! Found {total_matches} total dependency references.')
    # --- COG_END: MAIN_EX_SCAN_SYNC ---


def main_ex_scan_sync2(assets: list[Asset]) -> list[Dependency]:
    """Simple scanner with some extra stuff.

    We can add a progress bar + robust struct for storing our dependencies.
    """
    # --- COG_START: MAIN_EX_SCAN_SYNC2 ---
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
        for file_path in asset.get_scannables(PROJECT)
    )
    for asset, file_path in tqdm.tqdm(
        scans, total=len(scans), desc='Scanning'
    ):
        text = file_path.read_text(encoding='utf-8')
        matches: list[my_analyze_scan_dep.DependencyMatch] = list(
            my_analyze_scan_dep.scan(
                text,
                automaton.iter(text),
            )
        )

        total_matches += len(matches)
        for match in matches:
            loc = match.location
            dependencies.append(
                Dependency(
                    location=my_analyze_location.BoundLocation(
                        loc_line=loc.loc_line,
                        loc_column=loc.loc_column,
                        loc_index=loc.loc_index,
                        asset_name=asset.name,
                        file_name=file_path.name,
                    ),
                    source_asset=asset,
                    target_asset=name2asset[match.target_asset],
                    contexts=match.contexts,
                )
            )

    print(f'\nDone! Found {total_matches} total dependency references.')
    # --- COG_END: MAIN_EX_SCAN_SYNC2 ---
    return dependencies


def main_ex_scan_mp(assets: list[Asset]) -> list[Dependency]:
    """Multiprocessing scanner.

    Multiprocessing can speed up scanning (but in practice it didn't - we
    left this sample moreso as a reference). To do this, we can divide
    the scanning tasks across a pool of worker processes.

    For this we must set up few additional methods - worker's "init" and
    worker "work".
    """
    # --- COG_START: MAIN_EX_SCAN_MP ---

    # generate list of atomic jobs
    jobs = [
        ScanJob(asset_name=asset.name, file_path=file_path)
        for asset in assets
        for file_path in asset.get_scannables(PROJECT)
    ]

    name2asset = {asset.name: asset for asset in assets}
    total_matches = 0
    dependencies: list[Dependency] = []

    worker_count = mp.cpu_count()
    print(f'Initializing executor pool with {worker_count} workers')

    with futures.ProcessPoolExecutor(
        max_workers=worker_count,
        initializer=_worker_init,
        initargs=(list(name2asset.keys()),),
    ) as executor:
        submits = {executor.submit(_worker_scan, job): job for job in jobs}

        # feed into mp
        for future in tqdm.tqdm(
            futures.as_completed(submits),
            total=len(jobs),
            desc='Scanning',
        ):
            result: ScanResult = future.result()
            total_matches += len(result.matches)
            # convert results
            for match in result.matches:
                loc = match.location
                dependencies.append(
                    Dependency(
                        location=my_analyze_location.BoundLocation(
                            loc_line=loc.loc_line,
                            loc_column=loc.loc_column,
                            loc_index=loc.loc_index,
                            asset_name=result.job.asset_name,
                            file_name=result.job.file_path.name,
                        ),
                        source_asset=name2asset[result.job.asset_name],
                        target_asset=name2asset[match.target_asset],
                        contexts=match.contexts,
                    )
                )

    # print a few matches to verify the results
    print(f'\nDone! Found {total_matches} total dependency references.')

    for dep in dependencies[:3]:
        loc = dep.location
        print(
            f'[{dep.source_asset.name}] -> {dep.target_asset.name} '
            f'(Line {loc.loc_line}, Col {loc.loc_column})'
        )

    # --- COG_END: MAIN_EX_SCAN_MP ---
    return dependencies


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

    orphans_by_cluster: dict[str, list[Asset]] = {}
    total_orphans = 0

    for name in orphan_names:
        asset = all_assets[name]

        orphans_by_cluster.setdefault(asset.cluster, []).append(asset)
        total_orphans += 1

    if total_orphans == 0:
        print('\nProject is somehow clean - no orphaned assets found')
    else:
        print(
            f'\nFound {total_orphans} orphaned assets across '
            f'{len(orphans_by_cluster)} clusters:'
        )

        for cluster, orphans in sorted(orphans_by_cluster.items()):
            print(f'\n=== {cluster} ===')

            # sort
            orphans.sort(
                key=lambda a: (a.__class__.__name__, a.get_tree_path(), a.name)
            )

            for asset in orphans:
                print(asset.to_str_linter())
    # --- COG_END: MAIN_EX_LINT_UNUSED ---


def main_ex_lint_crossref(dependencies: list[Dependency]) -> bool:
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
    violations: dict[
        str,
        dict[str, list[str]],
    ] = {}
    total_violations = 0

    for dep in dependencies:
        target = dep.target_asset
        source = dep.source_asset

        # remove deps to room
        if isinstance(target, my_asset.Room):
            continue

        # get permissions from lint rules
        allowed_targets = set(
            LINT_RULES.get(source.cluster, {source.cluster, 'Common'})
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
        if target.cluster not in allowed_targets:
            total_violations += 1
            loc = dep.location

            # format the contexts for the error log
            ctx_str = (
                f' [Contexts: {", ".join(dep.contexts)}]'
                if dep.contexts
                else ''
            )
            err_msg = (
                f'{loc.file_name}({loc.loc_line:}:{loc.loc_column:}) -> '
                f"'{target.name}' [{target.cluster}]"
                f'{ctx_str}'
            )

            cluster_errs = violations.setdefault(source.cluster, {})
            asset_errs = cluster_errs.setdefault(source.name, [])
            asset_errs.append(err_msg)

    # output linting report
    if total_violations == 0:
        print('\nClear!!!')
    else:
        print(
            f'\nFound {total_violations} dependency violations '
            f'across {len(violations)} clusters:'
        )

        for cluster, asset_errs in sorted(violations.items()):
            print(f'\n=== {cluster} ===')

            for asset_name, errors in sorted(asset_errs.items()):
                print(f'[{asset_name}]')
                for err in errors:
                    print(f'  |-- {err}')
    # MD: Unlike the unused asset linter (which should be viewed more as a
    # MD: "suggester"), the crossref linters are *required* to be happy,
    # MD: before you may start with the actually useful tools.
    # MD:
    # MD: From the following examples, the only useful ones until you
    # MD: clear out the dependency linter, are about trimming
    # MD: more unused assets via dependency graph.
    # --- COG_END: MAIN_EX_LINT_CROSSREF ---
    return total_violations == 0


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
    cluster_groups: dict[frozenset[str], list[str]] = {}

    for asset_room in filter_type(my_asset.Room, assets):
        allowed_clusters = LINT_RULES.get(
            asset_room.cluster, {asset_room.cluster, 'Common'}
        )
        cluster_groups.setdefault(frozenset(allowed_clusters), []).append(
            asset_room.name
        )

    print('Clusterset to rooms:')
    for cluster_set, rooms in cluster_groups.items():
        print(*cluster_set)
        for room in rooms:
            print(' ', room)
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

        for room_name in tqdm.tqdm(
            rooms, desc=task_name, leave=True, file=sys.stdout
        ):
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
                room_name=room_name,
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

    unused_assets: list[Asset] = [
        asset for asset in assets if asset.name not in all_used_names
    ]

    if not unused_assets:
        print('\nOmg Clear?!!')
    else:
        print(f'Found {len(unused_assets)} unreachable assets!')

        # group by cluster
        grouped_unused: dict[str, list[Asset]] = collections.defaultdict(list)
        for asset in unused_assets:
            grouped_unused[asset.cluster].append(asset)

        for cluster, dead_assets in sorted(grouped_unused.items()):
            print(f'=== {cluster} ===')

            for asset in sorted(
                dead_assets,
                key=lambda a: (
                    a.__class__.__name__,
                    a.get_tree_path(),
                    a.name,
                ),
            ):
                print(asset.to_str_linter())

            print()
    # --- COG_END: MAIN_EX_LINT_UNUSED_GRAPH ---


def main_ex_lint_crossref_graph(
    assets: list[Asset],
    room_graph_data: dict[str, RoomGraph],
) -> bool:
    """Validate room and their dependencies clustering boundaries.

    Final step of linting process before the project would be qualified for
    destructive (and actually useful) tools in validating cluster boundaries
    on rooms as a whole.

    Note 1: this tool is intended to be used only after resolved every
    issue raised by simpler crossref linter.

    Note 2: this tool will output a lot of violations for each offending
    dependency edge, therefore some attention is required in order to pinpoint
    the exact offenders. Also, I recommend re-running the tool after each fix.
    """
    ok = True
    # --- COG_START: MAIN_EX_LINT_CROSSREF_GRAPH ---

    # asset clusters lookup
    asset_to_cluster: dict[str, str] = {
        asset.name: asset.cluster for asset in assets
    }
    total_violations = 0

    for rg in room_graph_data.values():
        room_cluster = asset_to_cluster.get(rg.room_name)
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

        ok = False
        print(f'Boundary Violation in Room: {rg.room_name}')
        print(f'-- Allowed Clusters: {" ".join(allowed_clusters)}')

        room_idx = rg.name2index[rg.room_name]
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

            print(f'  [{target_cluster}] {illegal_name}')
            path_found = False

            # trace 1 - structural contamination from the room
            room_paths = rx.dijkstra_shortest_paths(
                rg.graph, room_idx, target_idx
            )
            if target_idx in room_paths:
                path_names = [rg.graph[idx] for idx in room_paths[target_idx]]
                print(
                    f'    Traceback via Room Root: {" -> ".join(path_names)}'
                )
                path_found = True

            # trace 2 - implicit contamination via global controllers
            for p_name, p_idx in active_persistent_roots:
                p_paths = rx.dijkstra_shortest_paths(
                    rg.graph, p_idx, target_idx
                )
                if target_idx in p_paths:
                    path_names = [rg.graph[idx] for idx in p_paths[target_idx]]
                    print(
                        f'    Traceback via Persistent Root ({p_name}): '
                        f'{" -> ".join(path_names)}'
                    )
                    path_found = True
                    break

            if not path_found:
                print(
                    '    Traceback: Path unknown (Check structural edge '
                    'configurations)'
                )

        if total_violations > 1000:  # noqa: PLR2004
            print('\nLinter exceeded 1000 violations, bailing out')
            break
    # MD: Once you've cleared this one, you may call the game qualified
    # MD: for using the dangerous toys down the line.
    # MD:
    # MD: Congrats on defeating the tutorial boss.
    # --- COG_END: MAIN_EX_LINT_CROSSREF_GRAPH ---
    return ok


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
        if not isinstance(asset, (AssetExtSfx, AssetExtBgm)):
            continue
        paths_unignore.add(asset.file)

    sfx_dir = AssetExtSfx.type_get_dir(PROJECT)
    bgm_dir = AssetExtBgm.type_get_dir(PROJECT)

    def _ignore_audio(dir_path: str, dir_contents: list[str]) -> list[str]:
        """Callback for copytree to skip copying audio, except Common."""
        path = Path(dir_path)

        if path.is_relative_to(sfx_dir) or path.is_relative_to(bgm_dir):
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
            for img in asset.get_sprite_images(JUICER.dir_out, meta.frames):
                shutil.copyfile(stub_img, img)
        elif isinstance(asset, my_asset.Background):
            meta = asset.get_background_metadata(JUICER.dir_out)
            if not meta.exists:
                raise ValueError('Empty backgrounds are not allowed')
            shutil.copyfile(
                stub_img, asset.get_background_image(JUICER.dir_out)
            )

    # --- COG_END: MAIN_EX_JUICER_COPY ---


def main_juicer_fix_masks(assets: list[Asset]) -> None:  # noqa: PLR0915
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
    target_event = '#define Other_4'

    # exact action blocks, we'll validate against that;
    #  notice that endings are deliberately LF, that's how .gm82 save
    #  format works

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

    objects = filter_type(my_asset.Object, assets)
    for obj in tqdm.tqdm(objects, desc='Injecting fixes into objects...'):
        # use output dir, since that's where we'll be writing
        gml_path = obj.get_object_gml(JUICER.dir_out)

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
            meta = obj.get_object_metadata(JUICER.dir_out)
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
                    '- B1: no room start + has parent, '
                    'must add Call parent event',
                )
            else:
                print(obj.name, '- B2: no room start')

            # add the code block and injection
            new_block += block_603 + injection_code
            gml_text += new_block

            gml_path.write_text(gml_text, encoding='utf-8', newline='\n')
    # --- COG_END: MAIN_EX_JUICER_FIX_MASKS ---


def main_juicer_gen_wet(assets: list[Asset]) -> None:  # noqa: PLR0915
    """Copying works, time to extract wet assets.

    For this process we'll convert sprites and backgrounds into
    ``.gmspr`` and ``.gmbck`` files for easier loading on game maker side,
    music and sounds will be compressed. Refer to [Dehydration](#dehydration)
    for more info.

    Encoding images into the Game Maker's formats was done via my awesome
    library [gmcodec](https://github.com/shaperones0/gmcodec).

    Compressing audio was done via FFmpeg. Normally I'd postpone any
    optimization passes until the pipeline is done, but the audio compression
    one was too easy to insert for me to miss out on it.

    As an unfortunate side effect, the process now takes around a minute
    to finish... We'll address that once we are done with v1 of the pipeline.
    Until then - suffer.
    """

    # --- COG_START: MAIN_EX_JUICER_GEN_WET ---
    def dehydrate_sprite(sprite: my_asset.Sprite, out_dir: Path) -> None:
        # read original metadata
        meta = sprite.get_sprite_metadata(PROJECT)

        frames_bgra: list[bytes] = []
        width, height = 0, 0

        for img_path in sprite.get_sprite_images(PROJECT, meta.frames):
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

        out_file = out_dir / f'{sprite.name}.gmspr'
        out_file.write_bytes(gmc_file.file_pack(payload))

    def dehydrate_background(bg: my_asset.Background, out_dir: Path) -> None:
        # read the original metadata
        meta = bg.get_background_metadata(PROJECT)

        # meta.exists == 0 was already filtered out
        img_path = bg.get_background_image(PROJECT)
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

        out_file = out_dir / f'{bg.name}.gmbck'
        out_file.write_bytes(gmc_file.file_pack(payload))

    def dehydrate_audio(audio: my_asset.AssetExt, out_dir: Path) -> None:
        # remember when we added those " to names yeah
        clean_name = audio.name[1:-1]

        if (
            isinstance(audio, AssetExtSfx)
            and audio.file.suffix.lower() == '.wav'
        ):
            # FMOD kind 0 (RAM): compress to MS ADPCM 22050Hz
            out_file = out_dir / f'{clean_name}.wav'
            subprocess.run(  # noqa: S603
                [  # noqa: S607
                    'ffmpeg',
                    '-i',
                    str(audio.file),
                    '-y',
                    '-c:a',
                    'adpcm_ms',
                    '-ar',
                    '22050',
                    str(out_file),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            # FMOD kind 1/3 (Stream): compress to low-bitrate Ogg Vorbis
            out_file = out_dir / f'{clean_name}.ogg'
            subprocess.run(  # noqa: S603
                [  # noqa: S607
                    'ffmpeg',
                    '-i',
                    str(audio.file),
                    '-y',
                    '-map_metadata',
                    '-1',
                    '-c:a',
                    'libvorbis',
                    '-q:a',
                    '2',
                    str(out_file),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

    dir_wet = JUICER.dir_out / JUICER.rel_dir_wet
    if dir_wet.exists():
        shutil.rmtree(dir_wet)

    print('Generating wet assets (compression & encoding)...')

    for asset in tqdm.tqdm(
        list(filter_type(my_asset.Sprite, assets)),
        desc='Encoding sprites...',
    ):
        dir_out = dir_wet / asset.cluster / type(asset).type_get_dir_rel()
        dir_out.mkdir(parents=True, exist_ok=True)
        dehydrate_sprite(asset, dir_out)

    for asset in tqdm.tqdm(
        list(filter_type(my_asset.Background, assets)),
        desc='Encoding backgrounds...',
    ):
        dir_out = dir_wet / asset.cluster / type(asset).type_get_dir_rel()
        dir_out.mkdir(parents=True, exist_ok=True)
        dehydrate_background(asset, dir_out)

    for asset in tqdm.tqdm(
        list(filter_type(AssetExtSfx, assets))
        + list(filter_type(AssetExtBgm, assets)),
        desc='Compressing audio...',
    ):
        dir_out = dir_wet / asset.cluster / type(asset).type_get_dir_rel()
        dir_out.mkdir(parents=True, exist_ok=True)
        dehydrate_audio(asset, dir_out)

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

        # get wet file location
        dir_wet = JUICER.dir_out / JUICER.rel_dir_wet / asset.cluster

        # populate specific array
        if isinstance(asset, AssetExtBgm):
            assets_bgm.append(asset)
            clean_name = asset.name[1:-1]
            pth_wet = (
                dir_wet / type(asset).type_get_dir_rel() / f'{clean_name}.ogg'
            )
        elif isinstance(asset, AssetExtSfx):
            assets_sfx.append(asset)
            clean_name = asset.name[1:-1]
            if asset.file.suffix == '.wav':
                pth_wet = (
                    dir_wet
                    / type(asset).type_get_dir_rel()
                    / f'{clean_name}.wav'
                )
            else:
                pth_wet = (
                    dir_wet
                    / type(asset).type_get_dir_rel()
                    / f'{clean_name}.ogg'
                )
        elif isinstance(asset, my_asset.Sprite):
            assets_spr.append(asset)
            pth_wet = (
                dir_wet
                / type(asset).type_get_dir_rel()
                / f'{asset.name}.gmspr'
            )
        elif isinstance(asset, my_asset.Background):
            assets_bg.append(asset)
            pth_wet = (
                dir_wet
                / type(asset).type_get_dir_rel()
                / f'{asset.name}.gmbck'
            )
        elif isinstance(asset, my_asset.Room):
            assets_rooms.append(asset)
            continue
        else:
            continue

        asset_name_to_file_wet[asset.name] = pth_wet.relative_to(
            JUICER.dir_out
        ).as_posix()

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

    for room in assets_rooms:
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

    for asset in assets_bgm + assets_sfx:
        clean_name = asset.name[1:-1]
        ext_orig = asset.file.suffix.lower()

        if isinstance(asset, AssetExtBgm):
            stub_var = '_p_bgm'
            kind = 1
            streamed = 1
            preload = 1
        elif ext_orig == '.wav':
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

    # --- COG_END: MAIN_EX_JUICER_GEN_GML ---


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

    PROJECT = config_dir.parent / 'source'
    JUICER = ConfJuicer(
        is_prod=False,
        dir_out=config_dir.parent / '_build',
        dir_dry=JUICER.dir_dry,  # og dir
        rel_dir_wet=JUICER.rel_dir_wet,
    )

    _file_private_alias = config_dir / 'alias.json'
    ALIAS = json.loads(_file_private_alias.read_text(encoding='utf-8'))

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
    if len(sys.argv) > 2 and sys.argv[2] == '--test':  # noqa: PLR2004
        is_test = True

    if is_test:
        _run_tutorials()
    else:
        main_ex_lint_tree()

        # flush cause progressbars can be iffy
        print(flush=True)

        assets = main_ex_aliases()

        time.sleep(0.5)

        # flush cause progressbars can be iffy
        print(flush=True)

        deps = main_ex_scan_sync2(assets)

        # main_ex_lint_unused(deps, assets)
        ok = main_ex_lint_crossref(deps)
        if not ok:
            print('Linting errors found - bailing out')
            return

        room_data = main_ex_graph(assets, deps)

        # main_ex_lint_unused_graph(assets, room_data)
        ok = main_ex_lint_crossref_graph(assets, room_data)
        if not ok:
            print('Linting errors found - bailing out')
            return

        main_juicer_copy(assets)
        main_juicer_fix_masks(assets)
        main_juicer_gen_wet(assets)
        main_juicer_gen_gml(assets)


if __name__ == '__main__':
    main()
