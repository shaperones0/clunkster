"""Main pipeline, together with examples."""

import collections
import collections.abc as col
import concurrent.futures
import contextlib
import dataclasses
import functools as ft
import hashlib
import itertools as it
import json
import logging
import os
import queue
import re
import secrets
import shutil
import subprocess  # ruff: ignore[suspicious-subprocess-import]
import sys
import threading
import time
import warnings
import zipfile
from abc import ABC
from pathlib import Path
from pprint import pprint
from typing import override

import numpy as np
import rpack
import rustworkx as rx
import watchfiles
from ahocorasick import Automaton  # ty: ignore[unresolved-import]
from gmcodec import core as gmc_core
from gmcodec import file as gmc_file
from gmcodec import model as gmc_model
from gmcodec import validate as gmc_validate
from PIL import Image
from rich import console as r_console
from rich import live as r_live
from rich import progress as r_progress
from rich import progress_bar as r_progress_bar
from rich import table as r_table
from rich import text as r_text
from rich.logging import RichHandler

from clunkster import asset as my_asset
from clunkster import atlas as my_atlas
from clunkster import lint as my_lint
from clunkster import model as my_model
from clunkster import project as my_proj
from clunkster import tiles as my_tiles
from clunkster.analyze import scan_cache as my_scan_cache
from clunkster.analyze import scan_dep as my_scan_dep
from clunkster.asset import Asset
from clunkster.parse import png as my_parse_png
from clunkster.parse import tree as my_parse_tree
from clunkster.pipeline import cache as my_cache
from clunkster.pipeline import run as my_run
from clunkster.pipeline import task as my_task
from clunkster.text import location as my_location
from clunkster.text.line import LineMap


# <snip PROJECT>
@dataclasses.dataclass(frozen=True, slots=True)
class Config:
    """Pipeline configuration, passed into every pipeline step."""

    # source project (root, where game's .gm82 file is stored + file reads)
    project: my_proj.Project
    # cluster name -> top level folders merged into it (see ALIAS)
    alias: dict[str, list[str]]
    # cluster -> clusters it may reference (see LINT_RULES)
    lint_rules: dict[str, set[str]]
    # guard script -> clusters it grants (see CONTEXT_RULES)
    context_rules: dict[str, set[str]]
    # persistent objects present in every room (see EXTRA_ROOTS)
    extra_roots: set[str]
    # Game Juicer settings (see JUICER)
    juicer: ConfJuicer
    # reference scan cache file
    scan_cache: Path
    # RAM budget (MB) for assets moved to Common because of cluster violations
    common_budget_mb: float = 500
    # terms that shouldn't be used anymore (assets, scripts, functions) ->
    #  why, see main_ex_lint_blacklist
    blacklist: dict[str, str] = dataclasses.field(default_factory=dict)
    # assets moved to Common because of cluster violations, derived by the
    #  cluster checks (see main_ex_promote_refs)
    promoted: frozenset[str] = frozenset()
    # lean builds: assets kept in the executable, derived by main_ex_lean
    #  (None: Common assets are)
    resident: frozenset[str] | None = None
    # top level folder -> cluster name, derived from alias
    alias_inv: dict[str, str] = dataclasses.field(init=False)

    def __post_init__(self) -> None:
        """Derive ``alias_inv`` from ``alias``."""
        alias_inv: dict[str, str] = {}
        for name, clusters in self.alias.items():
            for cluster in clusters:
                if cluster in alias_inv:
                    raise ValueError(f"Invalid alias (duplicate: '{cluster}')")
                alias_inv[cluster] = name
        object.__setattr__(self, 'alias_inv', alias_inv)


# </snip PROJECT>


def main_ex_setup_main() -> Config:
    """Set up the configuration.

    There's no global state: every pipeline step receives ``Config`` as its
    first argument. It holds:

    - ``project``: source project root (where game's ``.gm82`` file is
      stored), also caches file reads
    - ``alias``, ``lint_rules``, ``context_rules``, ``extra_roots``: cluster
      setup, explained in the examples that use them
    - ``juicer``: Game Juicer settings
    """
    # <snip MAIN_EX_SETUP_MAIN>
    cfg = Config(
        # project root must be absolute
        project=my_proj.Project(Path('path/to/the/project').resolve()),
        alias=ALIAS,
        lint_rules=LINT_RULES,
        context_rules=CONTEXT_RULES,
        extra_roots=EXTRA_ROOTS,
        juicer=JUICER,
        scan_cache=Path(__file__).parent / 'scan_cache.json',
    )
    # <md>
    # Values for the rest of the fields are introduced in the examples that
    # need them.
    # </md>
    # </snip MAIN_EX_SETUP_MAIN>
    return cfg  # ruff: ignore[unnecessary-assign]


# <snip OUTPUT>
# rich falls back to 80 columns when not printing into a terminal (IDE
#  consoles, logs), which is too narrow for some tables
CONSOLE = r_console.Console(width=None if sys.stdout.isatty() else 160)
log = logging.getLogger('clunkster')


def setup_output() -> None:
    """Route logging and warnings through the console."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(message)s',
        handlers=[
            RichHandler(
                console=CONSOLE,
                show_time=False,
                show_level=False,
                show_path=False,
            )
        ],
    )
    logging.captureWarnings(capture=True)


def step[**P, R](
    name: str,
) -> col.Callable[[col.Callable[P, R]], col.Callable[P, R]]:
    """Pipeline step decorator: prints a header and how long the step took."""

    def decorator(func: col.Callable[P, R]) -> col.Callable[P, R]:
        @ft.wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            CONSOLE.rule(name)
            start = time.perf_counter()
            result = func(*args, **kwargs)
            log.info('%s: done in %.2fs', name, time.perf_counter() - start)
            return result

        return wrapper

    return decorator


def progress[T](
    seq: col.Sequence[T], description: str = 'Working'
) -> col.Iterator[T]:
    """Iterate over a sequence while showing a progress bar."""
    # updating the bar is not free, so do it at most ~1000 times
    update_every = max(1, len(seq) // 1000)
    with r_progress.Progress(console=CONSOLE, transient=True) as bar:
        bar_task = bar.add_task(description, total=len(seq))
        for idx, item in enumerate(seq, start=1):
            yield item
            if idx % update_every == 0:
                bar.update(bar_task, completed=idx)


def render_table(
    table: col.Sequence[col.Sequence[str]], *, title: str | None = None
) -> None:
    """Print a 2D sequence of strings, ``table[0]`` contains the headers."""
    if len(table) < 2:
        return
    headers = table[0]
    rich_table = r_table.Table(
        f'[bold]{headers[0]}[/bold]', *headers[1:], title=title, padding=0
    )
    for row in table[1:]:
        rich_table.add_row(*row)
    CONSOLE.print(rich_table)


# </snip OUTPUT>


def main_ex_setup_output() -> None:
    """Set up the output.

    Pipeline steps don't print directly: status messages go through
    ``logging``, sequences get progress bars via ``progress``, and the
    ``step`` decorator marks where a step starts and how long it took.
    All of it goes through [rich](https://github.com/textualize/rich), which
    falls back to plain text when the output isn't a terminal.
    """
    # <snip MAIN_EX_SETUP_OUTPUT>
    setup_output()
    # </snip MAIN_EX_SETUP_OUTPUT>


# <snip DEF_EXAMPLE>
@step('Example step')
def main_example() -> None:
    """Example pipeline step."""
    log.info('Good weather up there')
    time.sleep(1)
    log.info('Makes me forget about my job: counting to 10')
    for number in progress(range(10), 'Counting'):
        time.sleep(0.5)
        log.info('Number %d', number)
    log.info('Clear?!! No way')


# </snip DEF_EXAMPLE>


# <snip CLS_ASSET_EXT>
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


# </snip CLS_ASSET_EXT>


# <snip DEF_ASSET_SCANNABLES>
def asset_scannables(asset: Asset, project_root: Path) -> col.Iterable[Path]:
    """Get asset's scannable code files."""
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


# </snip DEF_ASSET_SCANNABLES>


# <snip DEF_ASSET_CLUSTERS>
def asset_cluster_raw(asset: my_asset.AssetHasPath) -> str:
    """Get asset's initial cluster before aliasing."""
    return asset.tree_path[0] if asset.tree_path else 'Common'


def asset_cluster(cfg: Config, asset: my_asset.Asset) -> str:
    """Get asset's cluster."""
    if asset.name in cfg.promoted:
        return 'Common'
    if isinstance(asset, my_asset.AssetHasPath):
        cluster = asset_cluster_raw(asset)
        alias = cfg.alias_inv.get(cluster)
        return cluster if alias is None else alias
    return 'Unknown?'


# </snip DEF_ASSET_CLUSTERS>


# <snip DEF_ASSET_RESIDENT>
def asset_resident(cfg: Config, asset: my_asset.Asset) -> bool:
    """Check whether an asset stays in the executable (isn't dehydrated).

    Common assets do, or, in lean builds, the ones ``main_ex_lean`` picked.
    """
    if cfg.resident is not None:
        return asset.name in cfg.resident
    return asset_cluster(cfg, asset) == 'Common'


# </snip DEF_ASSET_RESIDENT>


# <snip DEF_ASSET_WET_FNAME>
def asset_wet_fname(cfg: Config, asset: my_asset.Asset) -> str:
    """Get asset's wet file name."""
    if isinstance(asset, AssetExtAudio) and not cfg.juicer.encode_audio:
        # copied as is
        return f'{asset.name_clean}{asset.file.suffix}'
    if isinstance(asset, AssetExtSfx):
        return f'{asset.name_clean}.wav'
    if isinstance(asset, (AssetExtSfx3, AssetExtBgm)):
        return f'{asset.name_clean}.ogg'
    if isinstance(asset, my_asset.Sprite):
        return f'{asset.name}.gmspr'
    if isinstance(asset, my_asset.Background):
        return f'{asset.name}.gmbck'
    raise NotImplementedError('Asset type not supported')


def asset_wet_path(cfg: Config, asset: my_asset.AssetHasDir) -> Path:
    """Get asset's wet file path, relative to the build dir.

    Normally ``<wet dir>/<cluster>/<asset type dir>/<file name>``. With
    ``hash_names``, files go flat into the wet dir, named by salted hashes
    of asset names, without extensions (except for audio).
    """
    juicer = cfg.juicer
    fname = asset_wet_fname(cfg, asset)
    if juicer.hash_names:
        digest = hashlib.blake2b(
            f'{type(asset).type_name()}/{asset.name}'.encode(),
            key=juicer.name_salt.encode(),
            digest_size=12,
        ).hexdigest()
        # loading uses exact file names, so extensions can go too, except
        #  for audio: gm82snd checks them
        suffix = Path(fname).suffix if isinstance(asset, AssetExtAudio) else ''
        return juicer.rel_dir_wet / f'{digest}{suffix}'
    return (
        juicer.rel_dir_wet
        / asset_cluster(cfg, asset)
        / type(asset).type_get_dir_rel()
        / fname
    )


# </snip DEF_ASSET_WET_FNAME>

# <snip CLUSTERABLE_ASSETS>
CLUSTERABLE_ASSETS: tuple[type[my_asset.AssetHasPath], ...] = (
    my_asset.Sprite,
    my_asset.Background,
    my_asset.Sound,
    my_asset.Path,
    my_asset.Script,
    my_asset.Font,
    my_asset.Object,
    my_asset.Room,
    AssetExtBgm,
    AssetExtSfx,
    AssetExtSfx3,
)
# </snip>

# <snip ALIAS>
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
# </snip ALIAS>

# <snip LINT_RULES>
LINT_RULES: dict[str, set[str]] = {
    # common assets cannot borrow from Stage specific folders
    'Common': {'Common'},
    # example of a stage that shares assets with another
    # "StageB": {"StageB", "StageA", "Common"},
}


def allowed_clusters(cfg: Config, cluster: str) -> set[str]:
    """Get clusters that assets of the given cluster may reference.

    Defaults to the cluster itself and Common.
    """
    return set(cfg.lint_rules.get(cluster, {cluster, 'Common'}))


# </snip LINT_RULES>

# <snip CONTEXT_RULES>
CONTEXT_RULES: dict[str, set[str]] = {
    'room_is_stageA': {'StageA'},
    'room_is_stageB': {'StageB'},
    'room_is_final': {'StageX', 'StageY', 'StageZ'},
    # ...
}
# </snip CONTEXT_RULES>

# <snip EXTRA_ROOTS>
EXTRA_ROOTS: set[str] = {
    'World'
    # ...
}
# </snip EXTRA_ROOTS>


# <snip CLS_DEPENDENCY>
@dataclasses.dataclass(frozen=True, slots=True)
class Dependency:
    """Full dependency data to be used in graph building."""

    location: my_location.Location
    source_asset: my_asset.Asset
    target_asset: my_asset.Asset
    contexts: tuple[str, ...]


# </snip CLS_DEPENDENCY>


# <snip CLS_ROOM_GRAPH>
@dataclasses.dataclass
class RoomGraph:
    """Bundle of room graph data."""

    room: my_asset.Room
    reachable_names: set[str]
    graph: rx.PyDiGraph
    name2index: dict[str, int]


# </snip CLS_ROOM_GRAPH>


# <snip CLS_JUICER_CONFIG>
@dataclasses.dataclass(frozen=True, slots=True)
class ConfJuicer:
    """Configuration for Game Juicer."""

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

    # filename of the gm82 project
    fname_gm82: str

    # encode audio, otherwise original files are copied as is (faster)
    encode_audio: bool = True
    # store wet assets flat in the wet dir under salted hashes of their
    #  names, so that the build doesn't spoil asset names and structure
    hash_names: bool = False
    # salt for hashed names
    name_salt: str = ''
    # pack the game exe and data folder into a zip
    package: bool = False
    # launch the game after building
    launch: bool = True
    # pack backgrounds used only by room tiles into atlases (main_ex_atlas)
    atlas: bool = False
    # rooms load exactly the assets they use instead of clusters
    #  (main_ex_lean), needs hash_names (no cluster folders)
    lean: bool = False
    # room changes an asset stays loaded for after its last room
    keep_rooms: int = 1
    # also write atlas pages into atlas_dump in the build, for inspection
    dump_atlas: bool = False
    # scramble names of baked models, otherwise they name room and depth
    scramble_models: bool = True
    # crop transparent edges of tiles that runtime code finds by position
    #  (they stay whole tiles, and must still cover that position)
    crop_found_tiles: bool = False


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
    fname_gm82='projectidk.gm82',
)
# </snip CLS_JUICER_CONFIG>


def main_ex_start(cfg: Config) -> None:
    """Let's start with some simple scanning.

    Clunkster already provides utils for scanning builtin assets and
    single-file external assets (such as audio for ``gm82snd``). However,
    registering those external assets is left as a task for the user.
    """
    # <snip MAIN_EX_START>

    assets: list[Asset] = []

    for asset_type in CLUSTERABLE_ASSETS:
        # check if given asset type exist in the project
        if not asset_type.type_is_used(cfg.project.root):
            continue

        # type_discover_all handles the discovery of all assets per
        #  asset type.
        assets.extend(asset_type.type_discover_all(cfg.project.root))

    print(f'Discovered {len(assets)} total assets.')
    # <md>
    # I recommend checking the resulting `assets` array for any weirdness in
    # debug before going further.
    # </md>
    # </snip MAIN_EX_START>


# <snip DEF_LINT_REPORT>
def lint_report(
    cfg: Config, violations: col.Sequence[my_lint.Violation]
) -> None:
    """Print violations, raise if any of them is an error."""
    if not violations:
        return
    CONSOLE.print(
        my_lint.format_report(violations, cfg.project),
        markup=False,
        highlight=False,
        soft_wrap=True,
    )
    errors = [
        v for v in violations if v.rule.severity == my_lint.Severity.ERROR
    ]
    if errors:
        raise my_lint.LinterFoundError(
            f'Linter found {len(errors)} error(s)', errors
        )


# </snip DEF_LINT_REPORT>


# <snip RULES_TREE>
RULE_TREE_DUPLICATE_FOLDER = my_lint.Rule(
    'T100', 'duplicate tree.yyd folder', my_lint.Severity.ERROR
)
RULE_TREE_DUPLICATE_ASSET = my_lint.Rule(
    'T101', 'duplicate asset name', my_lint.Severity.ERROR
)
# </snip RULES_TREE>


@step('Lint: tree.yyd files')
def main_ex_lint_tree(cfg: Config) -> None:
    """Now we must check integrity of ``tree.yyd`` files and asset names.

    Asset discovery and clusterization is based on scanning ``tree.yyd``
    files, so we have to ensure that they have no duplicate folders.

    This example also serves as an introduction to Clunkster's linter system.
    Each check is a ``Rule`` (code like ``T100``, title and severity), and
    each problem found is a ``Violation`` of a rule. Violations optionally
    carry a message, a location in a file, an asset, a group (used to group
    the report, e.g. by cluster) and extra detail lines. Steps collect them
    into a list and pass it to ``lint_report``, which prints the report
    (grouped by rule, sorted by asset and location) and raises if any of the
    violations is an error.

    For linting ``tree.yyd`` files we want to check that:

    1. all asset names are unique (``T101``): not bound to a specific file,
      since duplicate assets can exist across multiple types.
    2. no duplicate folders in tree (``T100``): checked within same asset
      type and bound to a location in specific ``tree.yyd`` file.

    Since any inconsistency in asset structure will cause big issues in the
    pipeline, both rules are errors.
    """
    # <snip MAIN_EX_LINT_TREE>
    # check that there are no duplicates
    violations: list[my_lint.Violation] = []
    asset_names: set[str] = set()
    for asset_type in CLUSTERABLE_ASSETS:
        # check if given asset type exist in the project
        if not asset_type.type_is_used(cfg.project.root):
            continue

        # populate namespace
        assets_from_index = list(
            asset_type.type_discover_names(cfg.project.root)
        )
        assets_set = set(assets_from_index)
        dupes = [
            item
            for item, count in collections.Counter(assets_from_index).items()
            if count > 1
        ]
        if dupes:
            violations.append(
                my_lint.Violation(
                    RULE_TREE_DUPLICATE_ASSET,
                    f'Duplicate assets in one type: {" ".join(dupes)}',
                )
            )
        inters = asset_names.intersection(assets_set)
        if inters:
            violations.append(
                my_lint.Violation(
                    RULE_TREE_DUPLICATE_ASSET,
                    'Duplicate assets across multiple types: '
                    + ' '.join(sorted(inters)),
                )
            )
        asset_names.update(assets_set)

    # report before parsing tree.yyd
    lint_report(cfg, violations)

    # check tree.yyd files of builtin assets
    violations = []
    for asset_type in CLUSTERABLE_ASSETS:
        if not issubclass(asset_type, my_asset.AssetBuiltin):
            continue
        if not asset_type.type_is_used(cfg.project.root):
            continue

        tree_file = asset_type.type_get_tree_file(cfg.project.root)
        line_map = cfg.project.line_map(tree_file)
        seen_children: dict[str, set[str]] = {}

        for node in my_parse_tree.nodes(cfg.project.lines(tree_file)):
            # format the tuple into path string (e.g., "/Player/SkinA")
            path_str = '/' + '/'.join(node.parent_path)
            seen = seen_children.setdefault(path_str, set())

            if node.name not in seen:
                seen.add(node.name)
                continue

            loc_line = node.line_num
            loc_column = node.depth + 1  # uses tab characters
            thing = 'Folder' if node.is_folder else 'Asset???'
            violations.append(
                my_lint.Violation(
                    RULE_TREE_DUPLICATE_FOLDER,
                    f"Duplicate {thing}: '{node.name}'",
                    location=my_location.Location(
                        file=tree_file,
                        loc_line=loc_line,
                        loc_column=loc_column,
                        loc_index=line_map.get_abs_index(loc_line, loc_column),
                    ),
                )
            )

    lint_report(cfg, violations)
    # </snip MAIN_EX_LINT_TREE>


# <snip RULES_ALIAS>
RULE_ALIAS_MISMATCH = my_lint.Rule(
    'A100', 'alias mismatch', my_lint.Severity.WARNING
)
# </snip RULES_ALIAS>


@step('Clusters')
def main_ex_aliases(cfg: Config) -> list[Asset]:
    """Generate clusters.

    Once we validated assets and trees, we can do cluster generation. We'll
    look at the top level folder name. In order to merge things like
    ``"StageA"`` and ``"stage_a"`` into single cluster ``"StageA"``, we'll
    use the alias system.

    Now, the alias dictionary can become quite large, so I added additional
    validation. Now we detect unused or extra names.

    Also, this script has a neat table output for clusters per asset type,
    It can be useful to discern where exactly any extra names are located.
    """
    # <snip MAIN_EX_ALIASES>
    assets: list[Asset] = []

    # ALIAS linter: find existing names in ALIAS
    lint_existing_aliases: set[str] = set()
    for name, clusters in cfg.alias.items():
        for cluster in clusters:
            lint_existing_aliases.add(cluster)
            lint_existing_aliases.add(name)

    # this will help us generate the table below
    table_type_to_clusters: dict[type[Asset], list[str]] = {}

    # ALIAS linter: find actually used names in ALIAS
    lint_used_aliases: set[str] = set()
    for asset_type in CLUSTERABLE_ASSETS:
        if not asset_type.type_is_used(cfg.project.root):
            continue

        cluster_set: set[str] = set()
        for asset in asset_type.type_discover_all(cfg.project.root):
            # add both generated cluster and its alias
            cluster = asset_cluster(cfg, asset)
            lint_used_aliases.add(asset_cluster_raw(asset))
            lint_used_aliases.add(cluster)

            cluster_set.add(cluster)

            assets.append(asset)

        table_type_to_clusters[asset_type] = list(cluster_set)

    # generate the table
    clusters_all = {
        name
        for clusters in table_type_to_clusters.values()
        for name in clusters
    }
    clusters_all_sorted = sorted(clusters_all)
    asset_types = list(table_type_to_clusters.keys())
    table: list[list[str]] = [
        ['Cluster', *(at.type_name() for at in asset_types)]
    ]

    # 3. Add rows: One row per cluster
    for cluster_name in clusters_all_sorted:
        row = [cluster_name]

        for asset_type in asset_types:
            if cluster_name in table_type_to_clusters[asset_type]:
                row.append(asset_type.type_name())
            else:
                row.append('')

        table.append(row)

    render_table(table, title='Clusters')

    # lint
    lint_unused_aliases = lint_existing_aliases - lint_used_aliases
    lint_extra_aliases = lint_used_aliases - lint_existing_aliases
    violations: list[my_lint.Violation] = []
    if lint_unused_aliases:
        violations.append(
            my_lint.Violation(
                RULE_ALIAS_MISMATCH,
                f'Unused aliases: {" ".join(sorted(lint_unused_aliases))}',
            )
        )
    if lint_extra_aliases:
        # after the initial project setup, I'd upgrade this to raise
        violations.append(
            my_lint.Violation(
                RULE_ALIAS_MISMATCH,
                f'Extra aliases: {" ".join(sorted(lint_extra_aliases))}',
            )
        )
    lint_report(cfg, violations)
    # <md>
    # Keep using the table thing until all aliases are gone.
    # </md>
    # </snip MAIN_EX_ALIASES>
    return assets


# <snip DEFS_SCAN_FILES>
# scanning more files than this is done in a process pool
SCAN_POOL_MIN_FILES = 500

# automaton of the scanning process, see _scan_init
_SCAN_AUTOMATON: Automaton | None = None


def _scan_init(names: col.Iterable[str]) -> None:
    """Build the automaton for searching names (once per process)."""
    global _SCAN_AUTOMATON
    _SCAN_AUTOMATON = Automaton()
    for name in names:
        _SCAN_AUTOMATON.add_word(name, name)
    _SCAN_AUTOMATON.make_automaton()


def _scan_file(file: Path) -> tuple[my_scan_cache.FileMatch, ...]:
    """Find references in a file."""
    assert _SCAN_AUTOMATON is not None, 'call _scan_init first'
    text = file.read_text(encoding='utf-8')
    line_map = LineMap.from_text(text)
    return tuple(
        my_scan_cache.FileMatch(
            match.idx,
            *line_map.get_line_col(match.idx),
            match.target,
            match.contexts,
        )
        for match in my_scan_dep.scan(text, _SCAN_AUTOMATON.iter(text))
    )


def scan_files(
    names: col.Sequence[str], files: col.Sequence[Path]
) -> list[tuple[my_scan_cache.FileMatch, ...]]:
    """Find references to given names in files, return matches per file."""
    if len(files) < SCAN_POOL_MIN_FILES:
        _scan_init(names)
        return [_scan_file(file) for file in progress(files, 'Scanning')]
    with concurrent.futures.ProcessPoolExecutor(
        initializer=_scan_init, initargs=(names,)
    ) as pool:
        return list(pool.map(_scan_file, files, chunksize=64))


# </snip DEFS_SCAN_FILES>


# <snip CLS_TERM_USE>
@dataclasses.dataclass(frozen=True, slots=True)
class TermUse:
    """Use of a blacklisted term."""

    term: str
    location: my_location.Location
    source_asset: Asset


# </snip CLS_TERM_USE>


@step('Scanning references')
def main_ex_scan(
    cfg: Config, assets: list[Asset], scan_cache: my_scan_cache.ScanCache
) -> tuple[list[Dependency], list[TermUse]]:
    """Reference scanner.

    In order to run dependency linters, we need to scan the actual references.
    We'll use
    [``pyahocorasick``](https://github.com/WojciechMula/pyahocorasick)
    library to make it decently fast.

    Text occurrences found like this reflect occurrences in static code,
    but with some exceptions (strings, comments). Filtering through
    such is implemented in Clunkster.

    Also, for pure data registry scripts (like ``sound_balance``), which,
    technically reference every asset, but don't instantiate them,
    we added a special directive: ``//!clunkster: ignore``. Add it in any
    GML scripts that should be skipped.

    Scanning every file on every run is slow-ish, so results are cached
    per file in ``ScanCache``, and only files whose stat changed are
    rescanned. Changing the set of asset names (e.g. adding an asset)
    rescans everything, in parallel. Saving the cache is left to the caller.

    Blacklisted terms (see ``main_ex_lint_blacklist``) are searched for in
    the same pass.
    """
    # <snip MAIN_EX_SCAN>
    names = sorted({asset.name for asset in assets} | cfg.blacklist.keys())
    scan_cache.set_names(
        hashlib.md5('\n'.join(names).encode('utf-8')).hexdigest()
    )

    scans = tuple(
        (asset, file_path)
        for asset in assets
        for file_path in asset_scannables(asset, cfg.project.root)
    )

    # look up cached matches, stat files before reading them
    file_matches: dict[Path, tuple[my_scan_cache.FileMatch, ...]] = {}
    stale: list[tuple[Path, my_task.FileStat]] = []
    for _, file_path in scans:
        stat = my_task.file_stat(file_path)
        matches = scan_cache.get(file_path, stat)
        if matches is None:
            stale.append((file_path, stat))
        else:
            file_matches[file_path] = matches
    log.info('%d file(s) cached, %d to scan', len(file_matches), len(stale))

    stale_files = [file_path for file_path, _ in stale]
    for (file_path, stat), matches in zip(
        stale, scan_files(names, stale_files), strict=True
    ):
        scan_cache.put(file_path, stat, matches)
        file_matches[file_path] = matches

    name2asset = {asset.name: asset for asset in assets}
    dependencies: list[Dependency] = []
    term_uses: list[TermUse] = []
    for asset, file_path in scans:
        for match in file_matches[file_path]:
            location = my_location.Location(
                file=file_path,
                loc_index=match.idx,
                loc_line=match.line,
                loc_column=match.column,
            )
            if match.target in name2asset:
                dependencies.append(
                    Dependency(
                        location=location,
                        source_asset=asset,
                        target_asset=name2asset[match.target],
                        contexts=match.contexts,
                    )
                )
            if match.target in cfg.blacklist:
                term_uses.append(TermUse(match.target, location, asset))

    log.info('Found %d total dependency references.', len(dependencies))
    # </snip MAIN_EX_SCAN>
    return dependencies, term_uses


# <snip RULES_BLACKLIST>
RULE_BLACKLIST = my_lint.Rule(
    'B100', 'blacklisted term', my_lint.Severity.WARNING
)
# </snip RULES_BLACKLIST>


@step('Lint: blacklisted terms')
def main_ex_lint_blacklist(cfg: Config, term_uses: list[TermUse]) -> None:
    """Report uses of blacklisted terms.

    Blacklist (``blacklist.json`` in the config directory) maps terms to the
    reason they shouldn't be used anymore: scripts and functions being phased
    out, assets that are about to be removed, etc. Uses are only reported,
    and are found the same way as asset references, so strings and comments
    don't count.
    """
    # <snip MAIN_EX_LINT_BLACKLIST>
    violations = [
        my_lint.Violation(
            RULE_BLACKLIST,
            cfg.blacklist[use.term],
            location=use.location,
            asset=use.source_asset,
            group=use.term,
        )
        for use in term_uses
    ]
    if violations:
        log.info('Found %d use(s) of blacklisted terms.', len(violations))
    lint_report(cfg, violations)
    # </snip MAIN_EX_LINT_BLACKLIST>


# <snip RULES_UNUSED>
RULE_UNUSED = my_lint.Rule('U100', 'unused asset', my_lint.Severity.WARNING)
# </snip RULES_UNUSED>


@step('Lint: unused assets')
def main_ex_lint_unused(
    cfg: Config, dependencies: list[Dependency], assets: list[Asset]
) -> None:
    """Find and report assets that are never referenced by anything.

    Removing unused assets is a quick way to clean up a project.
    We can do this with a simple set difference: Total Assets
    minus Used Assets. However, this will not catch isolated reference loops
    (e.g., A references B, B references A, but neither is used by the game).
    We'll handle these later.

    Take the output of this with a grain of salt.
    """
    # <snip MAIN_EX_LINT_UNUSED>
    all_assets = {asset.name: asset for asset in assets}

    # populate used set from dependencies
    used_asset_names: set[str] = set()
    for dep in progress(dependencies):
        # ignore self-references
        if dep.source_asset.name == dep.target_asset.name:
            continue
        used_asset_names.add(dep.target_asset.name)

    orphan_names = set(all_assets.keys()) - used_asset_names
    violations = [
        # group the report by cluster
        my_lint.Violation(
            RULE_UNUSED,
            asset=all_assets[name],
            group=asset_cluster(cfg, all_assets[name]),
        )
        for name in orphan_names
    ]

    if violations:
        log.info('Found %d violations.', len(violations))
    else:
        log.info('Somehow all clear...')
    lint_report(cfg, violations)
    # </snip MAIN_EX_LINT_UNUSED>


# <snip CLS_PROMOTION>
@dataclasses.dataclass(frozen=True, slots=True)
class Promotion:
    """Asset moved to Common because of a cluster violation."""

    asset: Asset
    # cluster the asset was in
    cluster: str
    # why it was moved
    reason: str
    location: my_location.Location | None = None
    # moved asset that caused this one to move, if any
    caused_by: str | None = None
    # extra lines for the report (e.g. traces)
    details: tuple[str, ...] = ()


# </snip CLS_PROMOTION>


@step('Clusters: cross-cluster references')
def main_ex_promote_refs(
    cfg: Config,
    dependencies: list[Dependency],
    promotions: dict[str, Promotion],
) -> Config:
    """Move assets referenced across cluster boundaries to Common.

    Simple check of clusters on both ends of dependency edge will catch
    the majority of "stageA object referenced stageB asset" cases.

    However, this check (and the following ones) have a few special rules:

    1. Most clusters are allowed to reference only themselves and Common
    cluster, but some may need to reference certain more localized "nonlocal"
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
        guards must be defined in ``CONTEXT_RULES``. Read more on those in the
        [GML chapter](index.md#integration-into-the-game).

    3. References to rooms are severed. Since the only way to meaningfully
    "instantiate" a room is to go there, for all intents and purposes
    whatever references a room doesn't really depend on it.

    Instead of failing, an asset referenced from a cluster that isn't allowed
    to reference it is moved to Common: it stays in the base executable
    instead of being dehydrated, so the game can't run into its stub. A moved
    asset's own references are then checked as Common's, which may move
    more assets, until nothing changes. Moves are reported and their RAM is
    limited by a budget (see the report example below), since every moved
    asset is RAM the game always pays for. Fixing the reported references is
    still the way to get that RAM back.
    """

    # <snip MAIN_EX_PROMOTE_REFS>
    def cluster_of(asset: Asset) -> str:
        if asset.name in promotions:
            return 'Common'
        return asset_cluster(cfg, asset)

    def allowed_targets(dep: Dependency) -> set[str]:
        # permissions from lint rules
        allowed = allowed_clusters(cfg, cluster_of(dep.source_asset))
        # expanded based on script guards
        for ctx in dep.contexts:
            for primary in cfg.context_rules.get(ctx, ()):
                allowed.update(allowed_clusters(cfg, primary))
        return allowed

    # references to rooms are severed
    by_source: dict[str, list[Dependency]] = {}
    for dep in dependencies:
        if not isinstance(dep.target_asset, my_asset.Room):
            by_source.setdefault(dep.source_asset.name, []).append(dep)

    moved_before = len(promotions)
    pending = list(by_source)
    while pending:
        source_name = pending.pop()
        for dep in by_source[source_name]:
            target = dep.target_asset
            if target.name in promotions:
                continue
            target_cluster = cluster_of(target)
            if target_cluster in allowed_targets(dep):
                continue

            source = dep.source_asset
            source_moved = promotions.get(source.name)
            source_cluster = (
                cluster_of(source)
                if source_moved is None
                else f'{source_moved.cluster}, moved'
            )
            ctx = dep.contexts
            ctx_str = f' [Contexts: {", ".join(ctx)}]' if ctx else ''
            promotions[target.name] = Promotion(
                asset=target,
                cluster=target_cluster,
                reason=(
                    f'referenced from {source.name} '
                    f'[{source_cluster}]{ctx_str}'
                ),
                location=dep.location,
                caused_by=source.name if source.name in promotions else None,
            )
            # its own references now have to be allowed for Common
            if target.name in by_source:
                pending.append(target.name)

    log.info('Moved %d asset(s) to Common', len(promotions) - moved_before)
    # </snip MAIN_EX_PROMOTE_REFS>
    return dataclasses.replace(cfg, promoted=frozenset(promotions))


@step('Building graph')
def main_ex_graph(
    cfg: Config, assets: list[Asset], dependencies: list[Dependency]
) -> dict[str, RoomGraph]:
    """Build dependency graph.

    Reference scanner gave us a set of dependency edges, from which we can
    build a dependency graph. Graphs are done via
    [``rustworkx``](https://github.com/Qiskit/rustworkx).

    Our main application of this graph would be finding a set of used assets in
    each room, and feeding that info into linters.

    There's two thing that makes this entire process a bit messy.

    First, our context guards depend on the current room being processed.
    This means, that rooms have slightly different graphs from each other. The
    cleanest (but far not optimal) way of doing this is to create different
    graphs for different sets of clusters.

    Second, persistent objects. We can't cleanly trace where those objects
    travel through the game, so we have to make a few compromises. We'll allow
    only 2 types of persistent objects:

    1. Highly localized objects (like room transitions), that don't instantiate
      state-specific assets beyong their spawn room. I think it'd be wise
      to validate that those objects are in Common cluster, for safety.

    2. Ubiquitous ``World`` object, which is present in every room. We mark
      those objects in ``EXTRA_ROOTS``, so they get artificially added into
      the reachability sets.

    Note: even though we calculate graphs for each room, saving them is
    optional. Beyond reachability set generation, they are only used in
    better output of second cross-reference linter down the line. If saving
    graphs ever becomes a bottleneck you may omit those and only calculate the
    ``reachability_map: dict[str, set[str]]``
    """
    # <snip MAIN_EX_GRAPH>

    # most references are repeats of the same (source, target, contexts)
    #  triple, while graphs only need unique edges; collapse them once
    #  (dict keeps the order deterministic)
    edges: dict[tuple[str, str, tuple[str, ...]], None] = {
        (dep.source_asset.name, dep.target_asset.name, dep.contexts): None
        for dep in dependencies
        # delete references to rooms
        if not isinstance(dep.target_asset, my_asset.Room)
    }

    def build_graph(
        active_clusters: set[str],
    ) -> tuple[rx.PyDiGraph, dict[str, int]]:
        g = rx.PyDiGraph()

        asset_name2index: dict[str, int] = {}

        for asset in assets:
            # add_node() returns the rx's assigned node id
            asset_name2index[asset.name] = g.add_node(asset.name)

        for source_name, target_name, contexts in edges:
            source_idx = asset_name2index[source_name]
            target_idx = asset_name2index[target_name]

            # context guards (nested guards intersect)
            if contexts:
                edge_can_execute = True

                for raw_ctx in contexts:
                    # get granted clusters for guard

                    # room must satisfy this guard to proceed deeper into
                    #   the nested guards
                    granted_clusters = cfg.context_rules.get(raw_ctx)
                    if (
                        granted_clusters is not None
                        and not active_clusters.intersection(granted_clusters)
                    ):
                        edge_can_execute = False
                        break

                if not edge_can_execute:
                    continue

            g.add_edge(source_idx, target_idx, None)

        return g, asset_name2index

    # group rooms by their allowed clusters
    cluster_groups: dict[frozenset[str], list[my_asset.Room]] = {}

    for asset_room in assets:
        if not isinstance(asset_room, my_asset.Room):
            continue
        room_cluster = asset_cluster(cfg, asset_room)
        room_allowed = allowed_clusters(cfg, room_cluster)
        cluster_groups.setdefault(frozenset(room_allowed), []).append(
            asset_room
        )

    log.debug('Clusterset to rooms:')
    for cluster_set, rooms in cluster_groups.items():
        log.debug(' '.join(sorted(cluster_set)))
        for room in rooms:
            log.debug('  %s', room.name)

    room_graph_data: dict[str, RoomGraph] = {}

    # process clustersets
    log.debug('Building graphs:')
    for cluster_set, rooms in cluster_groups.items():
        graph, name_to_index = build_graph(set(cluster_set))

        # resolve persistent root indices
        persistent_idx = [
            name_to_index[p] for p in cfg.extra_roots if p in name_to_index
        ]

        log.debug('- %s', ' '.join(sorted(cluster_set)))
        for room in progress(rooms):
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

    # </snip MAIN_EX_GRAPH>

    return room_graph_data


@step('Lint: unreachable assets')
def main_ex_lint_unused_graph(
    cfg: Config,
    assets: list[Asset],
    room_graph_data: dict[str, RoomGraph],
) -> None:
    """Identify unreachable assets.

    With our newly build reachability map we can indentify which assets are
    never referenced in any room. This would solve closed loops we've
    been skipping over in the simpler linter.
    """
    # <snip MAIN_EX_LINT_UNUSED_GRAPH>

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
    violations = [
        my_lint.Violation(
            RULE_UNUSED, asset=asset, group=asset_cluster(cfg, asset)
        )
        for asset in assets
        if asset.name not in all_used_names
    ]

    if violations:
        log.info('Found %d unreachable assets.', len(violations))
    else:
        log.info('Clear??? omg')
    lint_report(cfg, violations)
    # </snip MAIN_EX_LINT_UNUSED_GRAPH>


@step('Clusters: room boundaries')
def main_ex_promote_rooms(
    cfg: Config,
    assets: list[Asset],
    room_graph_data: dict[str, RoomGraph],
    promotions: dict[str, Promotion],
) -> Config:
    """Move assets that rooms reach outside of their clusters to Common.

    Final cluster check validates boundaries on rooms as a whole: everything
    a room reaches must be in the clusters it loads. This catches cases the
    per-reference check can't see, like a guard granting several clusters
    in a room that loads only some of them, or persistent objects.

    Offending assets are moved to Common, same as with cross-cluster
    references, and reported with traces of how the room reaches them.
    """
    # <snip MAIN_EX_PROMOTE_ROOMS>
    asset_to_cluster: dict[str, str] = {
        asset.name: asset_cluster(cfg, asset) for asset in assets
    }
    name2asset = {asset.name: asset for asset in assets}
    moved_before = len(promotions)

    for rg in progress(list(room_graph_data.values())):
        room_cluster = asset_to_cluster.get(rg.room.name)
        if room_cluster is None:
            continue

        room_allowed = allowed_clusters(cfg, room_cluster)
        illegal_assets = sorted(
            name
            for name in rg.reachable_names
            if asset_to_cluster[name] not in {'Common', *room_allowed}
        )
        if not illegal_assets:
            continue

        room_idx = rg.name2index[rg.room.name]
        # pre-resolve active persistent root ids
        active_persistent_roots = [
            (p_name, rg.name2index[p_name])
            for p_name in cfg.extra_roots
            if p_name in rg.name2index
        ]

        for illegal_name in illegal_assets:
            if illegal_name in promotions:
                # already moved because of another room
                continue
            target_idx = rg.name2index[illegal_name]
            traces: list[str] = []

            # trace 1 - room contamination
            room_paths = rx.dijkstra_shortest_paths(
                rg.graph, room_idx, target_idx
            )
            if target_idx in room_paths:
                path_names = [rg.graph[idx] for idx in room_paths[target_idx]]
                traces.append(
                    f'Traceback via Room Root: {" -> ".join(path_names)}'
                )

            # trace 2 - implicit contamination via global controllers
            for p_name, p_idx in active_persistent_roots:
                p_paths = rx.dijkstra_shortest_paths(
                    rg.graph, p_idx, target_idx
                )
                if target_idx in p_paths:
                    path_names = [rg.graph[idx] for idx in p_paths[target_idx]]
                    traces.append(
                        f'Traceback via Persistent Root ({p_name}): '
                        f'{" -> ".join(path_names)}'
                    )
                    break

            if not traces:
                traces.append(
                    'Traceback: Path unknown '
                    '(Possibly misconfigured structure)'
                )

            promotions[illegal_name] = Promotion(
                asset=name2asset[illegal_name],
                cluster=asset_to_cluster[illegal_name],
                reason=(
                    f'reached from room {rg.room.name} [{room_cluster}], '
                    f'which loads {" ".join(sorted(room_allowed))}'
                ),
                details=tuple(traces),
            )

    log.info('Moved %d asset(s) to Common', len(promotions) - moved_before)
    # </snip MAIN_EX_PROMOTE_ROOMS>
    return dataclasses.replace(cfg, promoted=frozenset(promotions))


# <snip RULES_PROMOTED>
RULE_PROMOTED = my_lint.Rule(
    'P100', 'moved to Common', my_lint.Severity.WARNING
)
RULE_PROMOTED_BUDGET = my_lint.Rule(
    'P101', 'moved to Common over RAM budget', my_lint.Severity.ERROR
)
# </snip RULES_PROMOTED>


# <snip DEF_ASSET_RAM>
def asset_ram_estimate(cfg: Config, asset: Asset) -> int:
    """Estimate how much RAM a loaded asset takes, in bytes.

    Only covers assets that get dehydrated, others always stay in the base
    executable anyway. Rough GameMaker 8.2 model:

    - sprites: every frame is a texture of 4 bytes per pixel, plus a
      collision mask of 1 byte per pixel (one per frame if masks are
      separate); textures aren't padded to powers of two, except on rare
      hardware
    - backgrounds: a single texture
    - external audio: file size (sound effects are loaded whole, for streamed
      music it's a generous estimate)
    """
    root = cfg.project.root
    if isinstance(asset, my_asset.Sprite):
        meta = asset.get_sprite_metadata(root)
        if meta.frames == 0:
            return 0
        width, height = my_parse_png.size(asset.get_sprite_image(root, 0))
        masks = meta.frames if meta.per_frame_colliders else 1
        return (meta.frames * 4 + masks) * width * height
    if isinstance(asset, my_asset.Background):
        image = asset.get_background_image(root)
        if not image.exists():
            return 0
        width, height = my_parse_png.size(image)
        return width * height * 4
    if isinstance(asset, AssetExtAudio):
        return asset.file.stat().st_size
    return 0


# </snip DEF_ASSET_RAM>


@step('Clusters: moved to Common')
def main_ex_report_promotions(
    cfg: Config, promotions: dict[str, Promotion]
) -> None:
    """Report assets moved to Common and check their RAM budget.

    Every move is listed once, under the cluster the asset was in, with the
    reason, the estimated RAM, and the chain of moves that led to it. Only
    assets moved because of violations count towards the budget
    (``common_budget_mb`` in ``Config``). Exceeding it stops the build,
    since that likely means some reference pulled a large part of a stage
    into Common.
    """
    # <snip MAIN_EX_REPORT_PROMOTIONS>
    violations: list[my_lint.Violation] = []
    total_ram = 0
    for promotion in promotions.values():
        ram = asset_ram_estimate(cfg, promotion.asset)
        total_ram += ram

        # chain of moves that led to this one
        chain: list[str] = []
        cause = promotion.caused_by
        while cause is not None and len(chain) < 10:
            chain.append(f'because {cause} moved: {promotions[cause].reason}')
            cause = promotions[cause].caused_by

        size = f' (~{ram / 2**20:.1f} MB)' if ram else ''
        violations.append(
            my_lint.Violation(
                RULE_PROMOTED,
                f'{promotion.reason}{size}',
                location=promotion.location,
                asset=promotion.asset,
                group=promotion.cluster,
                details=promotion.details + tuple(chain),
            )
        )

    log.info(
        'Moved %d asset(s) to Common, ~%.1f MB of RAM (budget: %.0f MB)',
        len(promotions),
        total_ram / 2**20,
        cfg.common_budget_mb,
    )
    if total_ram > cfg.common_budget_mb * 2**20:
        violations.append(
            my_lint.Violation(
                RULE_PROMOTED_BUDGET,
                f'~{total_ram / 2**20:.1f} MB moved to Common, '
                f'budget is {cfg.common_budget_mb:.0f} MB',
            )
        )
    lint_report(cfg, violations)
    # <md>
    # Once nothing gets moved anymore, you may call the game qualified for
    # using the dangerous toys down the line.
    #
    # Congrats on defeating the tutorial boss.
    # </md>
    # </snip MAIN_EX_REPORT_PROMOTIONS>


@step('Lean: assets per room')
def main_ex_lean(
    cfg: Config,
    assets: list[Asset],
    room_data: dict[str, RoomGraph],
    atlas: Atlas | None,
) -> tuple[Config, dict[str, set[str]]]:
    """Find exactly which assets each room needs (lean builds).

    Instead of whole clusters, every room loads what it actually reaches
    (from the dependency graphs), Common assets included:

    - assets reached from global roots (``EXTRA_ROOTS``) in every room,
      unguarded, can't ever be unloaded: they stay in the executable, as do
      assets of persistent Common objects, which may follow the player
      anywhere
    - assets of other persistent objects are needed in every room of their
      cluster, since they can outlive the room they were made in
    - with atlases, rooms need the pages their tiles were pointed to

    :return: Config with ``resident`` set, and needed assets per room.
    """
    # <snip MAIN_EX_LEAN>
    root = cfg.project.root
    loaded_types = (my_asset.Sprite, my_asset.Background, AssetExtAudio)
    loadable = {a.name for a in assets if isinstance(a, loaded_types)}
    persistent = [
        a.name
        for a in assets
        if isinstance(a, my_asset.Object)
        and a.get_object_metadata(root).persistent
        and a.name not in cfg.extra_roots
    ]
    roots = set(cfg.extra_roots) | {
        name
        for name in persistent
        if asset_cluster(cfg, next(a for a in assets if a.name == name))
        == 'Common'
    }

    def reach(rg: RoomGraph, names: col.Iterable[str]) -> set[str]:
        found: set[str] = set()
        for name in names:
            if name in rg.name2index:
                idx = rg.name2index[name]
                found |= {rg.graph[i] for i in rx.descendants(rg.graph, idx)}
                found.add(name)
        return found & loadable

    # resident: what roots reach in every room
    resident = set(loadable)
    for rg in room_data.values():
        resident &= reach(rg, roots)

    # persistent stage objects: whole cluster
    cluster_of = {a.name: asset_cluster(cfg, a) for a in assets}
    by_cluster: dict[str, set[str]] = {}
    for name in persistent:
        if name in roots:
            continue
        rg = next(
            (rg for rg in room_data.values() if name in rg.name2index), None
        )
        if rg is not None:
            by_cluster.setdefault(cluster_of[name], set()).update(
                reach(rg, [name])
            )

    atlased = atlas.atlased if atlas is not None else frozenset()
    page_names = (
        {p.asset.name for p in atlas.pages} if atlas is not None else set()
    )
    needs: dict[str, set[str]] = {}
    for room_name, rg in room_data.items():
        need = rg.reachable_names & loadable
        need |= by_cluster.get(cluster_of[room_name], set())
        need -= resident | atlased
        plan = atlas.rooms.get(room_name) if atlas is not None else None
        if plan is not None:
            need |= {
                tile.bg
                for tiles in plan.layers.values()
                for tile in tiles
                if tile.bg in page_names
            }
            need |= {
                model.texture
                for model in plan.models + plan.auto_models
                if model.texture in page_names
            }
        needs[room_name] = need

    cfg = dataclasses.replace(cfg, resident=frozenset(resident))
    by_name = {a.name: a for a in assets}

    def megabytes(names: col.Iterable[str]) -> float:
        return (
            sum(
                asset_ram_estimate(cfg, by_name[n])
                for n in names
                if n in by_name
            )
            / 2**20
        )

    sizes = sorted(megabytes(need) for need in needs.values())
    log.info(
        'Resident: %d assets (~%.1f MB); per room: median ~%.1f MB, max '
        '~%.1f MB',
        len(resident),
        megabytes(resident),
        sizes[len(sizes) // 2] if sizes else 0,
        sizes[-1] if sizes else 0,
    )
    # </snip MAIN_EX_LEAN>
    return cfg, needs


# <snip DEFS_JUICE>
def juice_sprite(
    *,
    meta: my_asset.SpriteMetadata,
    images: col.Iterable[Path],
    out_file: Path,
) -> None:
    """Juice a sprite into external ``.gmspr`` file.

    :param meta: Sprite metadata.
    :param images: Sprite images.
    :param out_file: File to write resulting ``.gmspr`` bytes to.
    """
    frames_bgra: list[bytes] = []
    width, height = 0, 0

    for img_path in images:
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
    *, meta: my_asset.BackgroundMetadata, image: Path, out_file: Path
) -> None:
    """Juice a background into external ``.gmbck`` file.

    :param meta: Background metadata (``exists`` flag must be 1).
    :param image: Background image.
    :param out_file: File to write resulting ``.gmbck`` bytes to.
    """
    with Image.open(image) as img:
        juice_background_image(meta=meta, img=img, out_file=out_file)


def juice_background_image(
    *,
    meta: my_asset.BackgroundMetadata,
    img: Image.Image,
    out_file: Path,
) -> None:
    """Juice a background image into external ``.gmbck`` file.

    :param meta: Background metadata (``exists`` flag must be 1).
    :param img: Background image.
    :param out_file: File to write resulting ``.gmbck`` bytes to.
    """
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
        subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
            [  # ruff: ignore[start-process-with-partial-path]
                'ffmpeg',
                '-i',
                str(audio.file),
                '-y',
                '-c:a',
                'pcm_s16le',
                '-ar',
                '44100',
                # output may have no extension to guess the format from
                '-f',
                'wav',
                str(out_file),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        # FMOD kind 1/3 (Stream): compress to low-bitrate Ogg Vorbis
        subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
            [  # ruff: ignore[start-process-with-partial-path]
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
                '-f',
                'ogg',
                str(out_file),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def juice_obj_fix_mask(
    *,
    obj_name: str,
    obj_has_parent: bool,
    input_gml: str,
    output_gml_path: Path,
) -> None:
    """Fix objects masks not updating when replacing sprites.

    :param obj_name: Object name.
    :param obj_has_parent: Whether the object has parent.
    :param input_gml: Input GML text.
    :param output_gml_path: Output GML path.
    """
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
    if not output_gml_path.exists():
        output_gml_path.touch()

    # check that the text was properly saved with LFs
    assert '\r\n' not in input_gml, 'Object was saved with CRLF'

    # check different cases
    if target_event in input_gml:
        # CASE A: Room Start already exists

        # split event at event declaration and its trailing newline
        parts = input_gml.split(target_event + '\n')

        if len(parts) != 2:
            # handle edge case where the event is at the very end of
            #  the file with no trailing newline
            if input_gml.endswith(target_event):
                parts = input_gml.split(target_event)
                parts[1] = '\n'
            else:
                raise ValueError(
                    f'Validation Error: Multiple Room Start events or '
                    f"malformed structure found in '{obj_name}.gml'."
                )

        event_body = parts[1]

        if event_body.startswith(block_603):
            # CASE A1: starts with a code block
            offset = len(block_603)
            new_event_body = (
                event_body[:offset] + injection_code + event_body[offset:]
            )

        elif event_body.startswith(block_604 + block_603):
            # CASE A2: starts with call parent, followed by a code block
            offset = len(block_604) + len(block_603)
            new_event_body = (
                event_body[:offset] + injection_code + event_body[offset:]
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
            warnings.warn(
                f'Object {obj_name} starts with call parent without '
                f'code block??? Investigate.',
                stacklevel=2,
            )
        else:
            # idk
            raise ValueError(
                f'Validation Error: YYD ACTION match '
                f"failed in '{obj_name}.gml'. The block immediately "
                f"following '{target_event}' does not match YYD ACTION "
                f'603 or 604 patterns.'
            )

        # rebuild, maintain LF
        new_text = parts[0] + target_event + '\n' + new_event_body
        output_gml_path.write_text(new_text, encoding='utf-8', newline='\n')
    else:
        # CASE B: Room Start doesn't exist
        # objects with no parent have this string blank

        # append the event into the file

        # check newline
        #  since we could've just created the file, it is allowed
        #  to be empty
        if input_gml and not input_gml.endswith('\n'):
            input_gml += '\n'

        new_block = target_event + '\n'
        if obj_has_parent:
            # CASE B1: use the "Call parent event" block
            new_block += block_604

        # add the code block and injection
        new_block += block_603 + injection_code
        input_gml += new_block

        output_gml_path.write_text(input_gml, encoding='utf-8', newline='\n')


# </snip DEFS_JUICE>


def main_juicer_processing() -> None:
    """First step - the actual processing functions.

    As it's outlined in [Juicing](index.md#juicing), processing will be
    applied only to sprites, backgrounds and external audio. Plus fixing
    object's masks and room's stretch backgrounds.

    Object's masks require doing changes to every object, so this thing belongs
    in the processing stage.

    Room's stretch backgrounds, however, are a bit too expensive to be put into
    processing stage. Rooms are good candidates for simply symlinking their
    folders (gazillion tiny files), and sacrificing that for some lousy
    stretching backgrounds is not the play. Plus, those are usually very rare,
    and it makes more sense to just pre-bake correct scale manually.

    Use the regex ``bg_stretch.=1`` to find all the offenders with ``grep``,
    and put into their rooms correct hardcoded scale.
    """


# <snip CLS_JUICE_TASKS>
class TaskEncodeSprite(my_task.TaskGeneric):
    """Encode sprite into an external ``.gmspr`` file."""

    def __init__(
        self,
        *,
        sprite: my_asset.Sprite,
        dir_input_root: Path,
        file_output: Path,
    ) -> None:
        """Initialize the task.

        :param sprite: Sprite to encode.
        :param dir_input_root: Input project root.
        :param file_output: Wet file to write.
        """
        file_metadata = sprite.get_sprite_metadata_file(dir_input_root)
        self.sprite_meta = sprite.get_sprite_metadata(dir_input_root)
        self.sprite_images = tuple(
            sprite.get_sprite_image(dir_input_root, frame)
            for frame in range(self.sprite_meta.frames)
        )

        self.file_output_gmspr = file_output

        super().__init__(
            task_id=f'proc_spr_{sprite.name}',
            inputs=(file_metadata, *self.sprite_images),
            outputs=(self.file_output_gmspr,),
        )

    @override
    def execute(self) -> None:
        juice_sprite(
            meta=self.sprite_meta,
            images=self.sprite_images,
            out_file=self.file_output_gmspr,
        )


class TaskEncodeBackground(my_task.TaskGeneric):
    """Encode background into an external ``.gmbck`` file."""

    def __init__(
        self,
        *,
        background: my_asset.Background,
        dir_input_root: Path,
        file_output: Path,
    ) -> None:
        """Initialize the task.

        :param background: Background to encode.
        :param dir_input_root: Input project root.
        :param file_output: Wet file to write.
        """
        file_metadata = background.get_background_metadata_file(dir_input_root)
        self.background_meta = background.get_background_metadata(
            dir_input_root
        )
        self.background_image = background.get_background_image(dir_input_root)

        self.file_output_gmbck = file_output

        super().__init__(
            task_id=f'proc_bg_{background.name}',
            inputs=(file_metadata, self.background_image),
            outputs=(self.file_output_gmbck,),
        )

    @override
    def execute(self) -> None:
        juice_background(
            meta=self.background_meta,
            image=self.background_image,
            out_file=self.file_output_gmbck,
        )


class TaskCompressAudio(my_task.TaskGeneric):
    """Compress audio."""

    def __init__(
        self,
        *,
        audio: AssetExtAudio,
        file_output: Path,
    ) -> None:
        """Initialize the task.

        :param audio: Background to compress.
        :param file_output: Wet file to write.
        """
        self.audio = audio
        self.file_output = file_output

        super().__init__(
            task_id=f'compress_{audio.name_clean}',
            inputs=(audio.file,),
            outputs=(self.file_output,),
        )

    @override
    def execute(self) -> None:
        juice_audio(self.audio, self.file_output)


class TaskFixMaskObjects(my_task.TaskGeneric):
    """Copy object and inject mask fix."""

    def __init__(
        self,
        *,
        obj: my_asset.Object,
        dir_input_root: Path,
        dir_out_root: Path,
    ) -> None:
        """Initialize the task.

        :param obj: Object to fix.
        :param dir_input_root: Input project root.
        :param dir_out_root: Output project root.
        """
        self.file_input_meta = obj.get_object_metadata_file(dir_input_root)
        self.file_input_gml = obj.get_object_gml_file(dir_input_root)

        self.file_output_meta = (
            dir_out_root / self.file_input_meta.relative_to(dir_input_root)
        )
        self.file_output_gml = dir_out_root / self.file_input_gml.relative_to(
            dir_input_root
        )

        meta = obj.get_object_metadata(dir_input_root)
        self.obj_name = obj.name
        self.obj_has_parent = bool(meta.parent)
        # objects gml files are guaranteed to exist
        self.obj_input_gml = self.file_input_gml.read_text(encoding='utf-8')
        self.obj_output_gml_file = dir_out_root / obj.get_object_gml_file(
            dir_input_root
        ).relative_to(dir_input_root)

        super().__init__(
            task_id=f'fixmasks_{obj.name}',
            inputs=(self.file_input_meta, self.file_input_gml),
            outputs=(self.file_output_meta, self.file_output_gml),
        )

    @override
    def execute(self) -> None:
        shutil.copy2(self.file_input_meta, self.file_output_meta)
        juice_obj_fix_mask(
            obj_name=self.obj_name,
            obj_has_parent=self.obj_has_parent,
            input_gml=self.obj_input_gml,
            output_gml_path=self.obj_output_gml_file,
        )


# </snip CLS_JUICE_TASKS>


def main_juicer_classes() -> None:
    """Step 2 - wrap the asset processing functions into Tasks.

    Few design notes:

    1. make sure tasks contents stay lightweight enough to be sent over IPC
    2. make sure task's execute method stays pure (doesn't rely on global
       variables or other pre-initialized state)
    3. use keyword-only arguments for constructors because those paths are
       easy to mess up
    """


# <snip CLS_ATLAS>
# largest atlas page, pages are cropped to what they hold
ATLAS_PAGE_SIZE = 4096
# pixels around each region repeating its edges, so that scaled views don't
#  pull in neighboring regions
ATLAS_BORDER = 1
# overlapping regions are stored as one when that adds at most this share of
#  unused pixels
ATLAS_MAX_MERGE_WASTE = 0.25
# tiles at least this large (both sides) are split into cells
SPLIT_MIN_SIZE = 128
# splitting cell size
SPLIT_CELL = 16
# splitting is kept only if it drops at least this share of the pixels
SPLIT_MIN_GAIN = 0.15
# white patch added to pages, single color areas are drawn with it stretched
#  and tinted
ATLAS_WHITE = '__white'
ATLAS_WHITE_SIZE = 4
# metadata of atlas page backgrounds
ATLAS_PAGE_META = my_asset.BackgroundMetadata(
    exists=1,
    tileset=0,
    tile_width=16,
    tile_height=16,
    tile_hoffset=0,
    tile_voffset=0,
    tile_hsep=0,
    tile_vsep=0,
)
# baked models of a layer draw just above it: within one depth, tiles draw on
#  top of instances, and this keeps models ordered among themselves too
MODEL_DEPTH_STEP = 0.0001

# objects that take the tile at their position at runtime (and their
#  children), objects that work on whole tile layers, and baked models
TILE_FINDERS = frozenset({'shap_SmartTileActive'})
TILE_LAYER_USERS = frozenset({'shap_TileDeleter'})
MODEL_OBJECT = 'shap_Model'
# debug object turning layers deeper than AUTO_LAYER_MIN_DEPTH into models at
#  depth - AUTO_LAYER_OFFSET, reading the room source at runtime; builds do
#  it ahead instead
AUTO_LAYER_OBJECT = 'shap_DbgAutoLayer'
AUTO_LAYER_MIN_DEPTH = 90000
AUTO_LAYER_OFFSET = 100000
# objects whose Draw events start and stop drawing into a throwaway surface:
#  tile layers between them never show, so builds remove them
LAYER_HIDE_START = 'shap_LayHide'
LAYER_HIDE_END = 'shap_LayHideEnd'


# part of a tile's region: offset and size within the region, and the
#  single color it's filled with (ARGB, BGR order), if it is
AtlasPart = tuple[int, int, int, int, int | None]


@dataclasses.dataclass(frozen=True, slots=True)
class AtlasEntry:
    """Image region placed on an atlas page."""

    # source background, or ATLAS_WHITE
    bg: str
    left: int
    top: int
    width: int
    height: int
    # region's position on the page
    x: int
    y: int


@dataclasses.dataclass(frozen=True, slots=True)
class AtlasPage:
    """Atlas page, added to the build as a background."""

    asset: my_asset.Background
    width: int
    height: int
    entries: tuple[AtlasEntry, ...]


@dataclasses.dataclass(frozen=True, slots=True)
class ModelPlan:
    """Model baked from tiles."""

    # file name in data/model, as shap_lazy_model loads it
    name: str
    # background textured with
    texture: str
    depth: float
    quads: tuple[my_model.Quad, ...]


@dataclasses.dataclass(frozen=True, slots=True)
class RoomPlan:
    """New contents of a room's tile layers."""

    # depth -> tiles left in the layer (only changed layers)
    layers: dict[int, tuple[my_tiles.Tile, ...]]
    models: tuple[ModelPlan, ...]
    # AUTO_LAYER_OBJECT instances, replaced by instances of auto_models
    auto_layer_ids: tuple[str, ...] = ()
    auto_models: tuple[ModelPlan, ...] = ()


@dataclasses.dataclass(frozen=True, slots=True)
class Atlas:
    """Packed texture atlas, and rooms using it."""

    pages: tuple[AtlasPage, ...]
    # backgrounds whose tiles moved onto pages
    atlased: frozenset[str]
    # room name -> plan, for changed rooms
    rooms: dict[str, RoomPlan]


@dataclasses.dataclass(slots=True)
class TileProtection:
    """Tiles of a room that runtime code works with."""

    # layers whose tiles must stay exactly as they are
    fixed_layers: set[int] = dataclasses.field(default_factory=set)
    # layers whose tiles may change, but must stay tiles
    tile_layers: set[int] = dataclasses.field(default_factory=set)
    # depth -> points; tiles there must stay exactly as they are
    points: dict[int, list[tuple[float, float]]] = dataclasses.field(
        default_factory=dict
    )
    # instances of AUTO_LAYER_OBJECT
    auto_layer_ids: list[str] = dataclasses.field(default_factory=list)
    # LAYER_HIDE_START/END instances: depth, and whether they start hiding,
    #  in creation order
    hiding: list[tuple[float, bool]] = dataclasses.field(default_factory=list)

    def hidden(self, layer: int) -> bool:
        """Check whether a tile layer is drawn while hiding.

        Tiles draw after instances of their depth, so what counts is the
        last marker drawn before them: the shallowest one at or deeper than
        the layer, the latest created among equally deep ones.
        """
        before = [
            (depth, idx, start)
            for idx, (depth, start) in enumerate(self.hiding)
            if depth >= layer
        ]
        if not before:
            return False
        return min(before, key=lambda m: (m[0], -m[1]))[2]


def is_tile_layer_file(file: Path) -> bool:
    """Check whether a room file is a tile layer (named by its depth)."""
    return file.suffix == '.txt' and file.stem.removeprefix('-').isdigit()


# </snip CLS_ATLAS>


@step('Atlas: protected tiles')
def main_ex_tile_protection(
    cfg: Config, assets: list[Asset]
) -> dict[str, TileProtection]:
    """Find tiles that runtime code works with.

    Anything that rewrites tiles has to leave alone those that the game
    finds or changes at runtime. Since the game references these objects by
    name, this is game-specific:

    - instances of ``TILE_FINDERS`` (and their children) take the tile at
      their position, at their depth: tiles there stay exactly as they are
    - ``TILE_LAYER_USERS`` work on their whole layer: it stays as it is
    - ``tile_layer_*`` calls with literal depths, in objects placed in a room
      or the room's creation code: those layers may change, but stay tiles
      (hiding or shifting a layer wouldn't affect a model)
    - layers of existing ``shap_Model`` instances stay tiles too, so that
      nothing gets drawn twice
    - ``AUTO_LAYER_OBJECT`` instances are noted: builds do their work ahead
      (see ``main_ex_atlas``)
    - ``LAYER_HIDE_START``/``LAYER_HIDE_END`` instances are noted: layers
      they hide get removed
    """
    # <snip MAIN_EX_TILE_PROTECTION>
    root = cfg.project.root
    objects = {
        asset.name: asset
        for asset in assets
        if isinstance(asset, my_asset.Object)
    }
    metas = {
        name: obj.get_object_metadata(root) for name, obj in objects.items()
    }

    def descends(name: str, ancestors: frozenset[str]) -> bool:
        seen: set[str] = set()
        while name and name not in seen:
            if name in ancestors:
                return True
            seen.add(name)
            meta = metas.get(name)
            name = meta.parent if meta else ''
        return False

    layer_call = re.compile(
        r'\btile_layer_(?:hide|show|shift|delete|delete_at|depth)\s*\(\s*'
        r'(-?\d+)\s*[,)]'
    )

    def literal_depths(file: Path) -> set[int]:
        if not file.exists():
            return set()
        text = file.read_text(encoding='utf-8', errors='replace')
        return {int(m.group(1)) for m in layer_call.finditer(text)}

    object_depths = {
        name: literal_depths(obj.get_object_gml_file(root))
        for name, obj in objects.items()
    }
    depth_field = re.compile(
        r'^\s*depth\s*=\s*(-?\d+(?:\.\d+)?)', re.MULTILINE
    )

    protection: dict[str, TileProtection] = {}
    for room in assets:
        if not isinstance(room, my_asset.Room):
            continue
        folder = room.get_room_folder(root)
        prot = TileProtection()
        prot.tile_layers |= literal_depths(room.get_room_gml_file(root))
        instances = folder / 'instances.txt'
        lines = (
            instances.read_text(encoding='utf-8').splitlines()
            if instances.exists()
            else []
        )
        for line in lines:
            if not line:
                continue
            fields = line.split(',')
            obj = fields[0]
            if obj == AUTO_LAYER_OBJECT:
                prot.auto_layer_ids.append(fields[3])
            prot.tile_layers |= object_depths.get(obj, set())
            finder = descends(obj, TILE_FINDERS)
            layer_user = descends(obj, TILE_LAYER_USERS)
            hiding = obj in {LAYER_HIDE_START, LAYER_HIDE_END}
            if not (finder or layer_user or hiding or obj == MODEL_OBJECT):
                continue
            # depth from creation code, or the object's
            depth = float(metas[obj].depth) if obj in metas else 0.0
            code = folder / f'{fields[3]}.gml'
            if code.exists():
                found = depth_field.findall(
                    code.read_text(encoding='utf-8', errors='replace')
                )
                if found:
                    depth = float(found[-1])
            layer = int(depth)
            if hiding:
                prot.hiding.append((depth, obj == LAYER_HIDE_START))
            elif finder:
                prot.points.setdefault(layer, []).append((
                    float(fields[1]),
                    float(fields[2]),
                ))
            elif layer_user:
                prot.fixed_layers.add(layer)
            else:
                prot.tile_layers.add(layer)
        protection[room.name] = prot

    log.info(
        'Protected: %d layers fixed, %d kept as tiles, %d tile positions',
        sum(len(p.fixed_layers) for p in protection.values()),
        sum(len(p.tile_layers) for p in protection.values()),
        sum(len(v) for p in protection.values() for v in p.points.values()),
    )
    # </snip MAIN_EX_TILE_PROTECTION>
    return protection


@step('Atlas: packing tiles')
def main_ex_atlas(
    cfg: Config,
    assets: list[Asset],
    dependencies: list[Dependency],
    protection: dict[str, TileProtection],
) -> Atlas:
    """Pack tiles into texture atlases, and bake them into models.

    Fewer textures and draw calls per room, by rewriting room tile layers:

    1. Only backgrounds referenced from nothing but room tile layers
       qualify: room tiles point to a region of a background, so they can
       point to a region of an atlas page instead. Others stay as they are.
    2. Tiles of those get their transparent edges cropped (fully transparent
       ones are dropped). Large ones are split into cells: empty cells are
       dropped, single color ones are drawn with a white patch, stretched and
       tinted, and the rest merge back into as few rectangles as possible.
       Tiles stay where they were drawn, also when scaled or mirrored;
       tiles whose parts would land between pixels stay whole.
    3. Regions lying within others, or overlapping them closely enough, are
       stored once, and so are regions with identical pixels.
    4. Regions are packed onto pages of the cluster of their background (so
       pages load and unload with their stage), with a border repeating
       their edges, and tiles are pointed to the pages.
    5. Tiles of each layer are baked into models (``shap_Model``), one per
       texture where order allows. Tiles overlapping ones that have to stay
       tiles stay tiles too, so drawing order doesn't change.

    Rooms with ``AUTO_LAYER_OBJECT`` get its models made here, in place of
    the object, which reads the room source at runtime (and only works in
    debug). Layers hidden by ``LAYER_HIDE_START``/``LAYER_HIDE_END`` are
    removed.

    Protected tiles (see ``main_ex_tile_protection``) are only pointed to
    pages, never changed otherwise. With ``crop_found_tiles``, tiles found by
    position get their transparent edges cropped too, as long as they still
    cover that position. Original backgrounds stay in the
    project (so asset ids don't change), but aren't loaded anymore.
    """
    # <snip MAIN_EX_ATLAS>
    root = cfg.project.root
    backgrounds = {
        asset.name: asset
        for asset in assets
        if isinstance(asset, my_asset.Background)
    }
    rooms = [asset for asset in assets if isinstance(asset, my_asset.Room)]

    # backgrounds referenced from anything but room tiles stay as they are
    excluded: set[str] = set()
    for dep in dependencies:
        target = dep.target_asset
        if isinstance(target, my_asset.Background) and not (
            isinstance(dep.source_asset, my_asset.Room)
            and is_tile_layer_file(dep.location.file)
        ):
            excluded.add(target.name)

    pixels: dict[str, np.ndarray] = {}

    def image(name: str) -> np.ndarray:
        if name not in pixels:
            file = backgrounds[name].get_background_image(root)
            with Image.open(file) as img:
                pixels[name] = np.asarray(img.convert('RGBA'))
        return pixels[name]

    # read layers
    layers: dict[str, dict[int, list[my_tiles.Tile]]] = {}
    for room in progress(rooms, 'Reading tiles'):
        layers[room.name] = {
            depth: my_tiles.parse_layer(
                room.get_room_layer_file(root, depth).read_text(
                    encoding='utf-8'
                )
            )
            for depth in room.get_room_layers(root)
        }

    # pick backgrounds: tiles must stay within them
    candidates: set[str] = set()
    used: dict[str, list[my_atlas.Rect]] = {}
    for room_layers in layers.values():
        for tiles in room_layers.values():
            for tile in tiles:
                used.setdefault(tile.bg, []).append(tile.region())
    for name, rects in used.items():
        bg = backgrounds.get(name)
        if bg is None or name in excluded:
            continue
        if not bg.get_background_image(root).exists():
            continue
        height, width = image(name).shape[:2]
        if all(
            left >= 0
            and top >= 0
            and 0 < w <= ATLAS_PAGE_SIZE - 2 * ATLAS_BORDER
            and 0 < h <= ATLAS_PAGE_SIZE - 2 * ATLAS_BORDER
            and left + w <= width
            and top + h <= height
            for left, top, w, h in rects
        ):
            candidates.add(name)
        else:
            log.warning('Not atlasing %s: tiles reach outside of it', name)

    # region -> parts
    part_cache: dict[tuple[str, my_atlas.Rect], list[AtlasPart]] = {}

    def crop(
        pix: np.ndarray, x: int, y: int, w: int, h: int
    ) -> AtlasPart | None:
        alpha = pix[y : y + h, x : x + w, 3]
        cols = np.flatnonzero(alpha.any(axis=0))
        rows = np.flatnonzero(alpha.any(axis=1))
        if not cols.size:
            return None
        return (
            x + int(cols[0]),
            y + int(rows[0]),
            int(cols[-1] - cols[0]) + 1,
            int(rows[-1] - rows[0]) + 1,
            None,
        )

    def crop_tile(tile: my_tiles.Tile) -> my_tiles.Tile | None:
        """Crop a tile's transparent edges, ``None`` if it's all transparent.

        Crop offsets are snapped outwards so that the tile stays on whole
        pixels when scaled (e.g. multiples of 5 for scale 0.8).
        """
        left, top, width, height = tile.region()
        part = crop(
            image(tile.bg)[top : top + height, left : left + width],
            0,
            0,
            width,
            height,
        )
        if part is None:
            return None
        dx, dy, w, h, _ = part
        snapped_dx = _snap_offset(dx, tile.xscale)
        snapped_dy = _snap_offset(dy, tile.yscale)
        return tile.sub(
            snapped_dx, snapped_dy, w + dx - snapped_dx, h + dy - snapped_dy
        )

    def crop_found(
        room_name: str,
        depth: int,
        tile: my_tiles.Tile,
        found_at: list[tuple[float, float]],
    ) -> my_tiles.Tile:
        """Crop a tile found by position, if it still covers the position."""
        cropped = crop_tile(tile)
        if cropped is not None and all(it.starmap(cropped.contains, found_at)):
            return cropped
        log.warning(
            '%s, depth %d: kept tile %s whole, its SmartTile at %s is on %s',
            room_name,
            depth,
            tile.format(),
            ' '.join(f'{x:g},{y:g}' for x, y in found_at),
            'a fully transparent tile'
            if cropped is None
            else 'transparent pixels at its edge',
        )
        return tile

    def parts(name: str, rect: my_atlas.Rect) -> list[AtlasPart]:
        key = (name, rect)
        if key in part_cache:
            return part_cache[key]
        left, top, width, height = rect
        pix = image(name)[top : top + height, left : left + width]
        whole = crop(pix, 0, 0, width, height)
        result: list[AtlasPart] = [] if whole is None else [whole]
        if whole is not None and min(whole[2], whole[3]) >= SPLIT_MIN_SIZE:
            cells: dict[tuple[int, int], int | None] = {}
            for cy in range(0, height, SPLIT_CELL):
                for cx in range(0, width, SPLIT_CELL):
                    cell = pix[cy : cy + SPLIT_CELL, cx : cx + SPLIT_CELL]
                    if not cell[..., 3].any():
                        continue
                    first = cell[0, 0]
                    if (cell == first).all():
                        r, g, b, a = (int(c) for c in first)
                        cells[cx // SPLIT_CELL, cy // SPLIT_CELL] = (
                            a << 24 | b << 16 | g << 8 | r
                        )
                    else:
                        cells[cx // SPLIT_CELL, cy // SPLIT_CELL] = None
            split: list[AtlasPart] = []
            for cx, cy, cw, ch, color in my_atlas.grid_rects(cells):
                x, y = cx * SPLIT_CELL, cy * SPLIT_CELL
                w = min(cw * SPLIT_CELL, width - x)
                h = min(ch * SPLIT_CELL, height - y)
                if color is not None:
                    split.append((x, y, w, h, color))
                    continue
                part = crop(pix, x, y, w, h)
                if part is not None:
                    split.append(part)
            kept = sum(p[2] * p[3] for p in split if p[4] is None)
            if kept <= (1 - SPLIT_MIN_GAIN) * whole[2] * whole[3]:
                result = split
        part_cache[key] = result
        return result

    def on_pixels(tile: my_tiles.Tile, dx: int, dy: int) -> bool:
        return (dx * tile.xscale).is_integer() and (
            dy * tile.yscale
        ).is_integer()

    # 1-2: crop and split, tiles keep the background they came from
    new_layers: dict[str, dict[int, list[tuple[my_tiles.Tile, str]]]] = {}
    protected: dict[str, dict[int, set[int]]] = {}
    solid_clusters: set[str] = set()
    for room_name, room_layers in layers.items():
        prot = protection.get(room_name, TileProtection())
        for depth, tiles in room_layers.items():
            if prot.hidden(depth) and not (
                prot.auto_layer_ids and depth > AUTO_LAYER_MIN_DEPTH
            ):
                # never shows, gets removed
                new_layers.setdefault(room_name, {})[depth] = []
                protected.setdefault(room_name, {})[depth] = set()
                continue
            points = prot.points.get(depth, [])
            keep: set[int] = set()
            out: list[tuple[my_tiles.Tile, str]] = []
            for tile in tiles:
                found_at = [pt for pt in points if tile.contains(*pt)]
                fixed = depth in prot.fixed_layers or bool(found_at)
                if (
                    found_at
                    and depth not in prot.fixed_layers
                    and cfg.juicer.crop_found_tiles
                    and tile.bg in candidates
                ):
                    tile = crop_found(room_name, depth, tile, found_at)
                tile_parts = (
                    None
                    if fixed or tile.bg not in candidates
                    else parts(tile.bg, tile.region())
                )
                if tile_parts is None:
                    if fixed:
                        keep.add(len(out))
                    out.append((tile, tile.bg))
                    continue
                if not all(
                    _on_pixel(p[0] * tile.xscale)
                    and _on_pixel(p[1] * tile.yscale)
                    for p in tile_parts
                ):
                    # parts would land between pixels, crop it whole instead
                    #  (snapping parts could make them overlap)
                    cropped = crop_tile(tile)
                    if cropped is not None:
                        out.append((cropped, tile.bg))
                    continue
                for x, y, w, h, color in tile_parts:
                    piece = tile.sub(x, y, w, h)
                    if color is not None:
                        # white patch, stretched and tinted
                        piece = dataclasses.replace(
                            piece,
                            bg=ATLAS_WHITE,
                            left=0,
                            top=0,
                            width=ATLAS_WHITE_SIZE,
                            height=ATLAS_WHITE_SIZE,
                            xscale=w * tile.xscale / ATLAS_WHITE_SIZE,
                            yscale=h * tile.yscale / ATLAS_WHITE_SIZE,
                            color=tint(tile.color, color),
                        )
                        solid_clusters.add(
                            asset_cluster(cfg, backgrounds[tile.bg])
                        )
                    out.append((piece, tile.bg))
            new_layers.setdefault(room_name, {})[depth] = out
            protected.setdefault(room_name, {})[depth] = keep

    # 3: regions to store, per background; regions within or close to
    #  others are stored as part of them, identical ones once
    regions: dict[str, set[my_atlas.Rect]] = {}
    for room_layers in new_layers.values():
        for tiles_from in room_layers.values():
            for tile, _ in tiles_from:
                if tile.bg in candidates:
                    regions.setdefault(tile.bg, set()).add(tile.region())
    # (background, region) -> its container, and where that's stored (the
    #  container itself, or one with identical pixels in the same cluster)
    stored_as: dict[
        tuple[str, my_atlas.Rect],
        tuple[my_atlas.Rect, tuple[str, my_atlas.Rect]],
    ] = {}
    by_pixels: dict[tuple[str, bytes], tuple[str, my_atlas.Rect]] = {}
    for name in sorted(regions):
        cluster = asset_cluster(cfg, backgrounds[name])
        merged = my_atlas.merge_regions(regions[name], ATLAS_MAX_MERGE_WASTE)
        for rect, container in sorted(merged.items()):
            left, top, w, h = container
            digest = hashlib.md5(
                image(name)[top : top + h, left : left + w].tobytes()
                + f'{w}x{h}'.encode()
            ).digest()
            stored_as[name, rect] = (
                container,
                by_pixels.setdefault((cluster, digest), (name, container)),
            )

    # 4: pack per cluster, pages get a white patch if needed
    by_cluster: dict[str, set[tuple[str, my_atlas.Rect]]] = {}
    for _, (name, rect) in stored_as.values():
        cluster = asset_cluster(cfg, backgrounds[name])
        by_cluster.setdefault(cluster, set()).add((name, rect))
    for cluster in solid_clusters:
        by_cluster.setdefault(cluster, set())
    border = ATLAS_BORDER
    white_size = ATLAS_WHITE_SIZE + 2 * border
    pages: list[AtlasPage] = []
    placed: dict[tuple[str, my_atlas.Rect], tuple[str, int, int]] = {}
    white: dict[str, tuple[str, int, int]] = {}
    # packing is slow: results are cached by input in the build folder, and
    #  packed in parallel otherwise
    jobs: dict[
        str, tuple[list[tuple[str, my_atlas.Rect]], str, AtlasPackJob]
    ] = {}
    for cluster, stored in sorted(by_cluster.items()):
        keys = sorted(stored, key=lambda k: (-k[1][2] * k[1][3], k))
        job = (
            [(r[2] + 2 * border, r[3] + 2 * border) for _, r in keys],
            (white_size, white_size) if cluster in solid_clusters else None,
        )
        jobs[cluster] = (
            keys,
            hashlib.md5(repr(job).encode()).hexdigest(),
            job,
        )
    file_pack_cache = cfg.juicer.dir_out / 'clunkster_atlas_pack.json'
    pack_cache: dict[str, AtlasPackedPages] = {}
    if file_pack_cache.exists():
        pack_cache.update(
            json.loads(file_pack_cache.read_text(encoding='utf-8'))
        )
    missing = [c for c, (_, key, _) in jobs.items() if key not in pack_cache]
    if missing:
        log.info('Packing %d cluster(s)', len(missing))
        with concurrent.futures.ProcessPoolExecutor() as pool:
            for cluster, packed_pages in zip(
                missing,
                pool.map(_atlas_pack_job, [jobs[c][2] for c in missing]),
                strict=True,
            ):
                pack_cache[jobs[cluster][1]] = packed_pages
    file_pack_cache.parent.mkdir(parents=True, exist_ok=True)
    write_if_changed(
        file_pack_cache,
        json.dumps({key: pack_cache[key] for _, key, _ in jobs.values()}),
    )

    for cluster, (keys, key, _) in jobs.items():
        packed = pack_cache[key]
        prefix = re.sub(r'\W', '_', cluster)
        for idx, (page_width, page_height, members) in enumerate(packed):
            page_name = f'__atlas_{prefix}_{idx}'
            if page_name in backgrounds:
                raise ValueError(f'Atlas page name {page_name} is taken')
            entries: list[AtlasEntry] = []
            for item, x, y in members:
                if item is None:
                    entry = AtlasEntry(
                        ATLAS_WHITE,
                        0,
                        0,
                        ATLAS_WHITE_SIZE,
                        ATLAS_WHITE_SIZE,
                        x=x + border,
                        y=y + border,
                    )
                    white.setdefault(cluster, (page_name, entry.x, entry.y))
                else:
                    name, rect = keys[item]
                    entry = AtlasEntry(name, *rect, x=x + border, y=y + border)
                    placed[keys[item]] = (page_name, entry.x, entry.y)
                entries.append(entry)
            asset = my_asset.Background(
                name=page_name,
                # root assets are Common
                tree_path=() if cluster == 'Common' else (cluster,),
            )
            pages.append(
                AtlasPage(asset, page_width, page_height, tuple(entries))
            )

    def to_page(tile: my_tiles.Tile, source: str) -> my_tiles.Tile:
        if tile.bg == ATLAS_WHITE:
            page, x, y = white[asset_cluster(cfg, backgrounds[source])]
            return dataclasses.replace(tile, bg=page, left=x, top=y)
        if tile.bg not in candidates:
            return tile
        container, key = stored_as[tile.bg, tile.region()]
        page, x, y = placed[key]
        return dataclasses.replace(
            tile,
            bg=page,
            left=x + tile.left - container[0],
            top=y + tile.top - container[1],
        )

    # 5: bake
    page_sizes = {p.asset.name: (p.width, p.height) for p in pages}
    texture_sizes: dict[str, tuple[int, int] | None] = {}

    def texture_size(name: str) -> tuple[int, int] | None:
        if name in page_sizes:
            return page_sizes[name]
        if name not in texture_sizes:
            bg = backgrounds.get(name)
            file = bg.get_background_image(root) if bg else None
            texture_sizes[name] = (
                my_parse_png.size(file) if file and file.exists() else None
            )
        return texture_sizes[name]

    plans: dict[str, RoomPlan] = {}
    tiles_before = tiles_after = models_after = 0
    for room in rooms:
        prot = protection.get(room.name, TileProtection())
        changed: dict[int, tuple[my_tiles.Tile, ...]] = {}
        models: list[ModelPlan] = []
        auto_models: list[ModelPlan] = []
        for depth, tiles_from in new_layers.get(room.name, {}).items():
            original = layers[room.name][depth]
            mapped = list(it.starmap(to_page, tiles_from))
            if prot.auto_layer_ids and depth > AUTO_LAYER_MIN_DEPTH:
                # what AUTO_LAYER_OBJECT does at runtime: the whole layer
                #  as models at a shallower depth
                auto_models.extend(
                    _bake_layer(
                        cfg,
                        room.name,
                        depth,
                        # all tiles, like the object
                        [t for t in mapped if texture_size(t.bg) is not None],
                        texture_size,
                        kind='auto',
                        model_depth=depth - AUTO_LAYER_OFFSET,
                    )
                )
            if prot.hidden(depth):
                # never shows: removed (after auto layers took its tiles)
                tiles_before += len(original)
                changed[depth] = ()
                continue
            keep = set(protected[room.name][depth])
            if depth not in prot.tile_layers | prot.fixed_layers:
                # tiles reaching outside of their texture stay tiles, models
                #  would wrap around instead
                keep |= {
                    i
                    for i, tile in enumerate(mapped)
                    if not _within_texture(tile, texture_size(tile.bg))
                }
                keep = _overlap_closure(mapped, keep)
                layer_models = _bake_layer(
                    cfg,
                    room.name,
                    depth,
                    [t for i, t in enumerate(mapped) if i not in keep],
                    texture_size,
                )
                models.extend(layer_models)
                models_after += len(layer_models)
                mapped = [t for i, t in enumerate(mapped) if i in keep]
            tiles_before += len(original)
            tiles_after += len(mapped)
            if mapped != original:
                changed[depth] = tuple(mapped)
        if changed or models or prot.auto_layer_ids:
            plans[room.name] = RoomPlan(
                layers=changed,
                models=tuple(models),
                auto_layer_ids=tuple(prot.auto_layer_ids),
                auto_models=tuple(auto_models),
            )

    # every tile of these points to pages now
    atlased = frozenset(candidates)
    log.info(
        'Packed regions of %d background(s) into %d page(s): %s',
        len(atlased),
        len(pages),
        ', '.join(f'{p.asset.name} {p.width}x{p.height}' for p in pages),
    )
    log.info(
        'Tiles: %d -> %d tiles and %d models',
        tiles_before,
        tiles_after,
        models_after,
    )
    # </snip MAIN_EX_ATLAS>
    return Atlas(pages=tuple(pages), atlased=atlased, rooms=plans)


# <snip DEFS_ATLAS>
def tint(color: int, pixel: int) -> int:
    """Combine a tile color with a pixel color (both ARGB, BGR order).

    Channels multiply, like drawing the pixel with the tile color does.
    """
    channels = [
        round(((color >> shift) & 0xFF) * ((pixel >> shift) & 0xFF) / 255)
        for shift in (0, 8, 16, 24)
    ]
    return (
        channels[0] | channels[1] << 8 | channels[2] << 16 | channels[3] << 24
    )


# pages: width, height, rectangles (index or None for the extra one, x, y)
AtlasPackedPages = list[tuple[int, int, list[tuple[int | None, int, int]]]]
# sizes of rectangles, and the extra one
AtlasPackJob = tuple[list[tuple[int, int]], tuple[int, int] | None]


def atlas_pack_pages(
    sizes: col.Sequence[tuple[int, int]],
    extra: tuple[int, int] | None = None,
) -> AtlasPackedPages:
    """Pack rectangles onto as few pages as possible, with ``rpack``.

    Every page takes the longest run of the remaining rectangles (in the
    given order, largest first works best) that fits, so pages fill up.

    :param sizes: Rectangle sizes.
    :param extra: Rectangle added to every page, if any.
    :return: Pages: width, height and placed rectangles (index into
      ``sizes``, or ``None`` for the extra one, x, y).
    """

    def attempt(items: list[int]) -> list[tuple[int, int]] | None:
        rects = [sizes[i] for i in items]
        if extra is not None:
            rects.append(extra)
        try:
            return rpack.pack(
                rects, max_width=ATLAS_PAGE_SIZE, max_height=ATLAS_PAGE_SIZE
            )
        except rpack.PackingImpossibleError:
            return None

    extra_size = extra if extra is not None else (0, 0)
    pages: AtlasPackedPages = []
    remaining = list(range(len(sizes)))
    while remaining or (extra is not None and not pages):
        positions = attempt(remaining)
        count = len(remaining)
        if positions is None:
            # binary search the longest run that fits
            low, high = 1, len(remaining) - 1
            positions = attempt(remaining[:1])
            if positions is None:
                raise ValueError(f'{sizes[remaining[0]]} exceeds page size')
            count = 1
            while low <= high:
                middle = (low + high) // 2
                found = attempt(remaining[:middle])
                if found is None:
                    high = middle - 1
                else:
                    positions, count, low = found, middle, middle + 1
        items: list[int | None] = list(remaining[:count])
        if extra is not None:
            items.append(None)
        rects = [sizes[i] if i is not None else extra_size for i in items]
        width = max(
            x + r[0] for (x, _), r in zip(positions, rects, strict=True)
        )
        height = max(
            y + r[1] for (_, y), r in zip(positions, rects, strict=True)
        )
        pages.append((
            width,
            height,
            [
                (item, x, y)
                for item, (x, y) in zip(items, positions, strict=True)
            ],
        ))
        remaining = remaining[count:]
    return pages


def _within_texture(tile: my_tiles.Tile, size: tuple[int, int] | None) -> bool:
    """Check whether a tile's region lies within its texture."""
    return size is not None and (
        tile.left >= 0
        and tile.top >= 0
        and tile.left + tile.width <= size[0]
        and tile.top + tile.height <= size[1]
    )


def _atlas_pack_job(job: AtlasPackJob) -> AtlasPackedPages:
    """Run ``atlas_pack_pages`` (for process pools)."""
    return atlas_pack_pages(job[0], extra=job[1])


def _on_pixel(value: float) -> bool:
    """Check whether a position is a whole pixel (allowing float error)."""
    return abs(value - round(value)) < 1e-6


def _snap_offset(offset: int, scale: float) -> int:
    """Get the largest offset up to ``offset`` that's a whole pixel scaled."""
    while offset > 0 and not _on_pixel(offset * scale):
        offset -= 1
    return offset


def _overlaps(a: tuple[float, ...], b: tuple[float, ...]) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _overlap_closure(tiles: list[my_tiles.Tile], keep: set[int]) -> set[int]:
    """Extend kept tiles with tiles overlapping them, transitively.

    Kept tiles stay tiles while the rest becomes models drawn above them,
    so anything overlapping a kept tile has to stay a tile too.
    """
    keep = set(keep)
    bounds = [tile.bounds() for tile in tiles]
    new = list(keep)
    while new:
        added = [
            i
            for i in range(len(tiles))
            if i not in keep
            and any(_overlaps(bounds[i], bounds[k]) for k in new)
        ]
        keep.update(added)
        new = added
    return keep


def model_name(
    cfg: Config, room: str, depth: int, index: int, kind: str = ''
) -> str:
    """Name a baked model (file name in data/model).

    Scrambled by default, so the model folder doesn't show room names.
    """
    key = f'model/{room}/{depth}/{index}'
    if kind:
        key += f'/{kind}'
    if cfg.juicer.scramble_models or cfg.juicer.hash_names:
        digest = hashlib.blake2b(
            key.encode(), key=cfg.juicer.name_salt.encode(), digest_size=8
        ).hexdigest()
        return f'{digest.upper()}.g3z'
    suffix = f'__{kind}' if kind else ''
    return f'{room}__{depth}__{index}{suffix}.g3z'


def _bake_layer(  # ruff: ignore[too-many-arguments]
    cfg: Config,
    room: str,
    depth: int,
    tiles: list[my_tiles.Tile],
    texture_size: col.Callable[[str], tuple[int, int] | None],
    *,
    kind: str = '',
    model_depth: float | None = None,
) -> list[ModelPlan]:
    """Bake tiles of a layer into models, one per texture where possible.

    Models go just above the layer (see ``MODEL_DEPTH_STEP``), or all at
    ``model_depth``, ordered by creation then.

    A tile joins the latest model of its texture, unless a later model (of
    another texture) overlaps it: then drawing order would change, so it
    starts a new model.
    """
    groups: list[tuple[str, list[my_tiles.Tile], list[float]]] = []
    for tile in tiles:
        bounds = tile.bounds()
        target = None
        for texture, members, group_bounds in reversed(groups):
            if texture == tile.bg:
                target = (members, group_bounds)
                break
            if _overlaps(bounds, tuple(group_bounds)):
                break
        if target is None:
            groups.append((tile.bg, [], [*bounds]))
            target = (groups[-1][1], groups[-1][2])
        members, group_bounds = target
        members.append(tile)
        group_bounds[:] = [
            min(group_bounds[0], bounds[0]),
            min(group_bounds[1], bounds[1]),
            max(group_bounds[2], bounds[2]),
            max(group_bounds[3], bounds[3]),
        ]

    models: list[ModelPlan] = []
    for idx, (texture, members, _) in enumerate(groups):
        size = texture_size(texture)
        assert size is not None
        width, height = size
        quads = tuple(
            my_model.Quad(
                x1=t.x,
                y1=t.y,
                x2=t.x + t.width * t.xscale,
                y2=t.y + t.height * t.yscale,
                u1=t.left / width,
                v1=t.top / height,
                u2=(t.left + t.width) / width,
                v2=(t.top + t.height) / height,
                color=t.blend,
                alpha=t.alpha,
            )
            for t in members
        )
        models.append(
            ModelPlan(
                name=model_name(cfg, room, depth, idx, kind),
                texture=texture,
                depth=depth - MODEL_DEPTH_STEP * (idx + 1)
                if model_depth is None
                else model_depth,
                quads=quads,
            )
        )
    return models


def write_if_changed(path: Path, text: str) -> None:
    """Write a text file, unless it already has this content.

    Keeps file stats, and therefore the build cache, intact.
    """
    if path.exists() and path.read_text(encoding='utf-8') == text:
        return
    path.write_text(text, encoding='utf-8', newline='\n')


def atlas_compose(page: AtlasPage, images: dict[str, Path]) -> Image.Image:
    """Compose page image from background regions.

    :param page: Page to compose.
    :param images: Image files of the backgrounds.
    """
    border = ATLAS_BORDER
    out = Image.new('RGBA', (page.width, page.height))
    sources: dict[str, Image.Image] = {}
    for e in page.entries:
        if e.bg == ATLAS_WHITE:
            region = Image.new(
                'RGBA', (e.width, e.height), (255, 255, 255, 255)
            )
        else:
            if e.bg not in sources:
                with Image.open(images[e.bg]) as img:
                    sources[e.bg] = img.convert('RGBA')
            region = sources[e.bg].crop((
                e.left,
                e.top,
                e.left + e.width,
                e.top + e.height,
            ))
        if border:
            # repeat edge pixels outwards
            arr = np.pad(
                np.asarray(region),
                ((border, border), (border, border), (0, 0)),
                mode='edge',
            )
            region = Image.fromarray(arr, 'RGBA')
        out.paste(region, (e.x - border, e.y - border))
    return out


def _digest(value: object) -> str:
    return hashlib.md5(repr(value).encode()).hexdigest()[:12]


class TaskAtlasPage(my_task.TaskGeneric):
    """Compose an atlas page."""

    def __init__(
        self,
        *,
        page: AtlasPage,
        images: dict[str, Path],
        file_png: Path | None,
        file_wet: Path | None,
        file_dump: Path | None = None,
    ) -> None:
        """Initialize the task.

        :param page: Page to compose.
        :param images: Image files of the backgrounds on the page.
        :param file_png: Page image to write, if any.
        :param file_wet: Wet page file to write, if any.
        :param file_dump: Page image to write for inspection, if any.
        """
        self.page = page
        self.images = {
            e.bg: images[e.bg] for e in page.entries if e.bg != ATLAS_WHITE
        }
        self.file_png = file_png
        self.file_wet = file_wet
        self.file_dump = file_dump
        super().__init__(
            # the layout is part of the id: changes to it rebuild the page
            task_id=f'atlas_page_{page.asset.name}_{_digest(page)}',
            inputs=tuple(sorted(set(self.images.values()))),
            outputs=tuple(
                f for f in (file_png, file_wet, file_dump) if f is not None
            ),
        )

    @override
    def execute(self) -> None:
        img = atlas_compose(self.page, self.images)
        if self.file_png is not None:
            img.save(self.file_png)
        if self.file_dump is not None:
            img.save(self.file_dump)
        if self.file_wet is not None:
            juice_background_image(
                meta=ATLAS_PAGE_META, img=img, out_file=self.file_wet
            )


def _instance_id(room: str, used: set[str], key: str) -> str:
    """Pick an instance id (8 hex digits) unique within the room."""
    salt = 0
    while True:
        instance_id = hashlib.md5(f'{room}|{key}|{salt}'.encode()).hexdigest()
        instance_id = instance_id[:8].upper()
        if instance_id not in used:
            used.add(instance_id)
            return instance_id
        salt += 1


class TaskAtlasRoom(my_task.TaskGeneric):
    """Copy a room, applying its atlas plan.

    Changed tile layers are rewritten, models written into the model
    folder, and ``shap_Model`` instances added to draw them.
    """

    def __init__(
        self,
        *,
        dir_room: Path,
        dir_out: Path,
        dir_models: Path,
        plan: RoomPlan | None,
    ) -> None:
        """Initialize the task.

        :param dir_room: Room folder.
        :param dir_out: Output room folder.
        :param dir_models: Folder to write models into.
        :param plan: Room's plan, ``None`` to copy as is.
        """
        self.files = tuple(
            sorted(file for file in dir_room.rglob('*') if file.is_file())
        )
        self.dir_room = dir_room
        self.dir_out = dir_out
        self.dir_models = dir_models
        self.plan = plan

        # layers left without tiles are removed, like the room editor does
        self.empty_layers = (
            {depth for depth, tiles in plan.layers.items() if not tiles}
            if plan is not None
            else set()
        )
        outputs = [
            dir_out / file.relative_to(dir_room)
            for file in self.files
            if self._layer_depth(file) not in self.empty_layers
        ]
        # instances of plan.models, then of plan.auto_models
        self.instance_ids: list[str] = []
        self.auto_instance_ids: list[str] = []
        if plan is not None and (plan.models or plan.auto_models):
            used = {
                line.split(',')[3]
                for line in (dir_room / 'instances.txt')
                .read_text(encoding='utf-8')
                .splitlines()
                if line
            }
            for models, ids in (
                (plan.models, self.instance_ids),
                (plan.auto_models, self.auto_instance_ids),
            ):
                for model in models:
                    instance_id = _instance_id(dir_room.name, used, model.name)
                    ids.append(instance_id)
                    outputs.extend((
                        dir_out / f'{instance_id}.gml',
                        dir_models / model.name,
                    ))
        super().__init__(
            # the plan is part of the id: changes to it rebuild the room
            task_id=f'atlas_room_{dir_room.name}_{_digest(plan)}',
            inputs=self.files,
            outputs=tuple(outputs),
        )

    def _instances(self, text: str) -> str:
        """Rewrite instances.txt with model instances.

        Models of auto layers replace the auto layer object (created at the
        same point, as it does at runtime), other models go last.
        """
        assert self.plan is not None
        auto = set(self.plan.auto_layer_ids)

        def line(instance_id: str) -> str:
            return f'{MODEL_OBJECT},0,0,{instance_id},0,1,1,4294967295,0,1'

        lines: list[str] = []
        for existing in text.splitlines():
            if not existing:
                continue
            if existing.split(',')[3] in auto:
                lines.extend(line(i) for i in self.auto_instance_ids)
                auto.clear()
                continue
            if existing.split(',')[0] == AUTO_LAYER_OBJECT:
                continue
            lines.append(existing)
        lines.extend(line(i) for i in self.instance_ids)
        return ''.join(f'{x}\n' for x in lines)

    def _layer_depth(self, file: Path) -> int | None:
        """Get depth of a tile layer file, ``None`` for other files."""
        if file.parent == self.dir_room and is_tile_layer_file(file):
            return int(file.stem)
        return None

    @override
    def execute(self) -> None:
        plan = self.plan
        layers = plan.layers if plan is not None else {}
        for depth in self.empty_layers:
            # left from an earlier build
            (self.dir_out / f'{depth}.txt').unlink(missing_ok=True)
        for file in self.files:
            out = self.dir_out / file.relative_to(self.dir_room)
            depth = self._layer_depth(file)
            if depth in self.empty_layers:
                continue
            if file.name == 'layers.txt' and self.empty_layers:
                kept = [
                    line
                    for line in file.read_text(encoding='utf-8').splitlines()
                    if line and int(line) not in self.empty_layers
                ]
                out.write_text(
                    ''.join(f'{line}\n' for line in kept),
                    encoding='utf-8',
                    newline='\n',
                )
            elif depth is not None and depth in layers:
                out.write_text(
                    my_tiles.format_layer(layers[depth]),
                    encoding='utf-8',
                    newline='\n',
                )
            elif file.name == 'instances.txt' and plan is not None:
                out.write_text(
                    self._instances(file.read_text(encoding='utf-8')),
                    encoding='utf-8',
                    newline='\n',
                )
            else:
                shutil.copy2(file, out)

        if plan is None:
            return
        for instance_id, model in zip(
            self.instance_ids + self.auto_instance_ids,
            plan.models + plan.auto_models,
            strict=True,
        ):
            (self.dir_out / f'{instance_id}.gml').write_text(
                '//gm82 fields begin\n'
                f'name="{model.name}"\n'
                f'tex_bg={model.texture}\n'
                f'depth={my_tiles.format_number(model.depth)}\n'
                '//gm82 fields end\n',
                encoding='utf-8',
                newline='\n',
            )
            (self.dir_models / model.name).write_bytes(
                my_model.model_g3z(model.quads)
            )


# </snip DEFS_ATLAS>


# <snip CLS_JUICE_BUILD_TASKS>
@dataclasses.dataclass(frozen=True, slots=True)
class BuildTasks:
    """Build tasks."""

    tasks_threaded: tuple[my_task.Task, ...]
    tasks_mp: tuple[my_task.Task, ...]


# </snip CLS_JUICE_BUILD_TASKS>


@step('Juicer: generate tasks')
def main_juicer_gen_tasks(
    cfg: Config, assets: list[Asset], atlas: Atlas | None = None
) -> BuildTasks:
    """Step 3 - ~~Fly~~ Run the thing.

    This stage is responsible for mapping out source project, generating
    tasks, and sending tasks to executors.

    Few things make this process a bit messy:

    1. External audio is not a top level folder.
    2. We must also account for Common assets, and make sure they get copied
       just so.

    Therefore, I've made logic of task generation very explicit. Also, this
    step does some of the cheaper tasks, like creating build dir and symlinks.
    """
    # <snip MAIN_JUICER_GEN_TASKS>
    # filter assets by their juiceable type
    asset_sprites: list[my_asset.Sprite] = []
    asset_backgrounds: list[my_asset.Background] = []
    asset_objects: list[my_asset.Object] = []
    asset_audio: list[AssetExtAudio] = []
    for asset in assets:
        if isinstance(asset, my_asset.Sprite):
            asset_sprites.append(asset)
        if isinstance(asset, my_asset.Background):
            asset_backgrounds.append(asset)
        if isinstance(asset, my_asset.Object):
            asset_objects.append(asset)
        if isinstance(asset, AssetExtAudio):
            asset_audio.append(asset)

    build_type = 'prod' if cfg.juicer.is_prod else 'dev'
    img_dry = cfg.juicer.dir_dry / f'img_{build_type}.png'
    tasks_threaded: list[my_task.Task] = []
    tasks_mp: list[my_task.Task] = []

    # them functions
    def pth_symlink(pth: Path) -> None:
        """Create a symlink from input project root to build output."""
        # this ain't IO bound operation so do it in-place
        output_dir = cfg.juicer.dir_out / pth.relative_to(cfg.project.root)
        if not output_dir.is_symlink():
            output_dir.symlink_to(pth, target_is_directory=True)

    def copy_rebase(*files: Path) -> None:
        tasks_threaded.append(
            my_task.TaskCopy(
                *(
                    (fl, cfg.juicer.dir_out / fl.relative_to(cfg.project.root))
                    for fl in files
                ),
                root=cfg.project.root,
            )
        )

    def type_copy_yyd(asset_type: type[my_asset.AssetBuiltin]) -> None:
        copy_rebase(
            asset_type.type_get_tree_file(cfg.project.root),
            asset_type.type_get_index_file(cfg.project.root),
        )

    def map_root(dir_root: Path) -> None:
        """Map project root."""
        for pth in dir_root.iterdir():
            if pth.is_file():
                # count in project root file and also ini files that are
                #  generated by extensions; talking about you imgui
                if pth.suffix in {'.gm82', '.ini'}:
                    copy_rebase(pth)
                else:
                    raise NotImplementedError('Unknown file in project root')
                continue
            assert pth.is_dir()
            match pth.name:
                case 'backgrounds':
                    # process backgrounds
                    map_backgrounds()
                case 'cache':
                    # cache is not needed for building
                    pass
                case 'data':
                    # multicase handle
                    map_data(pth)
                case 'fonts':
                    # symlink
                    pth_symlink(pth)
                case 'objects':
                    # process fix masks
                    map_objects()
                case 'paths':
                    # symlink
                    pth_symlink(pth)
                case 'rooms':
                    if atlas is None:
                        # symlink
                        pth_symlink(pth)
                    else:
                        # copy, pointing tiles to atlas pages
                        map_rooms(pth)
                case 'save':
                    # symlink
                    pth_symlink(pth)
                case 'scripts':
                    # copy (we'll have to dynamically change a few scripts)
                    #  using copytree on the whole tree might be faster than
                    #  copying individual assets
                    tasks_threaded.append(
                        my_task.TaskCopyTree(
                            pth,
                            cfg.juicer.dir_out
                            / pth.relative_to(cfg.project.root),
                        )
                    )
                case 'settings':
                    # symlink
                    pth_symlink(pth)
                case 'sprites':
                    # process sprites
                    map_sprites()
                case 'triggers':
                    # symlink
                    pth_symlink(pth)
                case _:
                    raise NotImplementedError('Unknown folder in project root')

    def map_data(dir_data: Path) -> None:
        """Map data folder."""
        # make sure data folder exists
        (cfg.juicer.dir_out / dir_data.relative_to(cfg.project.root)).mkdir(
            exist_ok=True
        )

        # you wanna change names to reflect paths in AssetExtAudio classes
        for pth in dir_data.iterdir():
            if pth.is_file():
                copy_rebase(pth)
                continue
            match pth.name:
                case 'music':
                    # process bgm
                    map_audio()
                case 'sounds':
                    # process sfx + sfx3
                    pass  # done above
                case _:
                    # copy idk
                    tasks_threaded.append(
                        my_task.TaskCopyTree(
                            pth,
                            cfg.juicer.dir_out
                            / pth.relative_to(cfg.project.root),
                        )
                    )

    def map_backgrounds() -> None:
        """Map backgrounds."""
        if atlas is None:
            # copy yyd
            type_copy_yyd(my_asset.Background)
        else:
            map_atlas(atlas)

        for bg in asset_backgrounds:
            if atlas is not None and bg.name in atlas.atlased:
                # not drawn anymore, kept as a stub so that ids don't change
                copy_rebase(bg.get_background_metadata_file(cfg.project.root))
                tasks_threaded.append(
                    my_task.TaskCopy(
                        (img_dry, bg.get_background_image(cfg.juicer.dir_out)),
                        root=cfg.project.root,
                    )
                )
                continue
            if asset_resident(cfg, bg):
                # copy as is
                copy_rebase(
                    bg.get_background_metadata_file(cfg.project.root),
                    bg.get_background_image(cfg.project.root),
                )
                continue
            # copy metadata
            copy_rebase(bg.get_background_metadata_file(cfg.project.root))
            # copy dry image
            tasks_threaded.append(
                my_task.TaskCopy(
                    (img_dry, bg.get_background_image(cfg.juicer.dir_out)),
                    root=cfg.project.root,
                )
            )
            # generate wet image
            tasks_mp.append(
                TaskEncodeBackground(
                    background=bg,
                    dir_input_root=cfg.project.root,
                    file_output=cfg.juicer.dir_out / asset_wet_path(cfg, bg),
                )
            )

    def map_atlas(atlas: Atlas) -> None:
        """Add atlas pages to the build as backgrounds."""
        dir_src = my_asset.Background.type_get_dir(cfg.project.root)
        dir_out = my_asset.Background.type_get_dir(cfg.juicer.dir_out)
        dir_out.mkdir(parents=True, exist_ok=True)
        names = [page.asset.name for page in atlas.pages]

        # pages go to the end of the index, keeping ids of other backgrounds
        index = (dir_src / 'index.yyd').read_text(encoding='utf-8')
        if index and not index.endswith('\n'):
            index += '\n'
        write_if_changed(
            dir_out / 'index.yyd', index + ''.join(f'{n}\n' for n in names)
        )
        tree = (dir_src / 'tree.yyd').read_text(encoding='utf-8')
        if tree and not tree.endswith('\n'):
            tree += '\n'
        write_if_changed(
            dir_out / 'tree.yyd',
            tree
            + '+__clunkster_atlas\n'
            + ''.join(f'\t|{n}\n' for n in names),
        )

        meta_text = ''.join(
            f'{field.name}={getattr(ATLAS_PAGE_META, field.name)}\n'
            for field in dataclasses.fields(ATLAS_PAGE_META)
        )
        images = {
            bg.name: bg.get_background_image(cfg.project.root)
            for bg in asset_backgrounds
            if bg.name in atlas.atlased
        }
        dir_dump = cfg.juicer.dir_out / 'atlas_dump'
        for page in atlas.pages:
            write_if_changed(dir_out / f'{page.asset.name}.txt', meta_text)
            file_png: Path | None = page.asset.get_background_image(
                cfg.juicer.dir_out
            )
            file_wet: Path | None = None
            if not asset_resident(cfg, page.asset):
                # dehydrated like other backgrounds
                tasks_threaded.append(
                    my_task.TaskCopy(
                        (img_dry, file_png), root=cfg.project.root
                    )
                )
                file_png = None
                file_wet = cfg.juicer.dir_out / asset_wet_path(cfg, page.asset)
            tasks_mp.append(
                TaskAtlasPage(
                    page=page,
                    images=images,
                    file_png=file_png,
                    file_wet=file_wet,
                    file_dump=dir_dump / f'{page.asset.name}.png'
                    if cfg.juicer.dump_atlas
                    else None,
                )
            )

    def map_rooms(dir_rooms: Path) -> None:
        """Map rooms, applying their atlas plans."""
        assert atlas is not None
        dir_out = cfg.juicer.dir_out / dir_rooms.relative_to(cfg.project.root)
        if dir_out.is_symlink():
            # left from a build without atlas, removes just the link
            dir_out.unlink()
        dir_models = cfg.juicer.dir_out / 'data' / 'model'
        for pth in dir_rooms.iterdir():
            if pth.is_file():
                copy_rebase(pth)
                continue
            tasks_threaded.append(
                TaskAtlasRoom(
                    dir_room=pth,
                    dir_out=dir_out / pth.name,
                    dir_models=dir_models,
                    plan=atlas.rooms.get(pth.name),
                )
            )

    def map_sprites() -> None:
        """Map sprites."""
        # copy yyd
        type_copy_yyd(my_asset.Sprite)

        for sprite in asset_sprites:
            if asset_resident(cfg, sprite):
                # copy as is
                tasks_threaded.append(
                    my_task.TaskCopyTree(
                        dir_input=sprite.get_sprite_folder(cfg.project.root),
                        dir_output=sprite.get_sprite_folder(
                            cfg.juicer.dir_out
                        ),
                    )
                )
                continue
            # copy metadata
            copy_rebase(sprite.get_sprite_metadata_file(cfg.project.root))
            # copy dry images
            meta = sprite.get_sprite_metadata(cfg.project.root)
            # make separate tasks cause some images are large
            tasks_threaded.extend(
                my_task.TaskCopy(
                    (
                        img_dry,
                        sprite.get_sprite_image(
                            cfg.juicer.dir_out, image_index
                        ),
                    ),
                    root=cfg.project.root,
                )
                for image_index in range(meta.frames)
            )

            # generate wet image
            tasks_mp.append(
                TaskEncodeSprite(
                    sprite=sprite,
                    dir_input_root=cfg.project.root,
                    file_output=cfg.juicer.dir_out
                    / asset_wet_path(cfg, sprite),
                )
            )

    def map_audio() -> None:
        """Map music."""
        # no yyd files
        for audio in asset_audio:
            if asset_resident(cfg, audio):
                # copy as is
                copy_rebase(audio.file)
                continue
            # no metadata or dry stuff
            file_output = cfg.juicer.dir_out / asset_wet_path(cfg, audio)
            if not cfg.juicer.encode_audio:
                tasks_threaded.append(
                    my_task.TaskCopy(
                        (audio.file, file_output), root=cfg.project.root
                    )
                )
                continue
            tasks_mp.append(
                TaskCompressAudio(audio=audio, file_output=file_output)
            )

    def map_objects() -> None:
        """Map objects."""
        # copy yyd
        type_copy_yyd(my_asset.Object)

        # add all regardless of cluster
        tasks_threaded.extend(
            TaskFixMaskObjects(
                obj=obj,
                dir_input_root=cfg.project.root,
                dir_out_root=cfg.juicer.dir_out,
            )
            for obj in asset_objects
        )

    # ensure output dir exists before creating symlinks
    cfg.juicer.dir_out.mkdir(parents=True, exist_ok=True)

    # run mapper
    map_root(cfg.project.root)

    # validate all tasks have unique ids juuust in case
    dupes = [
        item
        for item, count in collections.Counter(
            task.task_id for task in it.chain(tasks_threaded, tasks_mp)
        ).items()
        if count > 1
    ]
    if dupes:
        raise ValueError(f'Duplicate task ids: {dupes}')
    dupes = [
        item
        for item, count in collections.Counter(
            out
            for task in it.chain(tasks_threaded, tasks_mp)
            for out in task.outputs
        ).items()
        if count > 1
    ]
    if dupes:
        raise ValueError(f'Several tasks write the same files: {dupes}')

    build_tasks = BuildTasks(
        tasks_threaded=tuple(tasks_threaded),
        tasks_mp=tuple(tasks_mp),
    )
    # </snip MAIN_JUICER_GEN_TASKS>
    return build_tasks  # ruff: ignore[unnecessary-assign]


# <snip DEF_RUN_TASKS_POOL>
class WorkerView:
    """Live view of running tasks: progress, and the latest task per worker.

    Updated from finished tasks only, and rendered by rich at its own pace,
    so it costs next to nothing.
    """

    # at most this many running tasks are listed
    MAX_RUNNING = 5

    def __init__(self, name: str, total: int) -> None:
        """Initialize the view.

        :param name: Name of the task batch.
        :param total: Number of tasks to run.
        """
        self.name = name
        self.total = total
        self.completed = 0
        # worker -> its latest finished task
        self.workers: dict[str, r_text.Text] = {}
        self.running: tuple[str, ...] = ()
        # rich renders from its own thread
        self._lock = threading.Lock()

    def update(self, done: my_run.TaskDone) -> None:
        """Record a finished task."""
        with self._lock:
            self.completed += 1
            self.workers[done.worker] = (
                r_text.Text(done.task.task_id)
                if done.error is None
                else r_text.Text(f'FAILED {done.task.task_id}', style='red')
            )
            self.running = tuple(task.task_id for task in done.running)

    @staticmethod
    def _worker_label(worker: str) -> str:
        if worker.isdigit():
            return f'process {worker}'
        # ThreadPoolExecutor-0_3 -> thread 3
        return f'thread {worker.rpartition("_")[2]}'

    def __rich__(self) -> r_console.Group:
        """Render the view."""
        with self._lock:
            header = r_table.Table.grid(expand=True, padding=(0, 1))
            header.add_column(no_wrap=True)
            header.add_column(ratio=1)
            header.add_column(no_wrap=True)
            header.add_row(
                self.name,
                r_progress_bar.ProgressBar(
                    total=self.total, completed=self.completed
                ),
                f'{self.completed}/{self.total}',
            )

            table = r_table.Table(box=None, padding=(0, 1), expand=True)
            table.add_column('worker', style='dim', no_wrap=True, min_width=13)
            table.add_column(
                'latest task', no_wrap=True, overflow='ellipsis', ratio=1
            )
            for worker, task_id in self.workers.items():
                table.add_row(self._worker_label(worker), task_id)

            running = self.running if self.completed < self.total else ()
            for idx, task_id in enumerate(running[: self.MAX_RUNNING]):
                table.add_row('running' if idx == 0 else '', task_id)
            if len(running) > self.MAX_RUNNING:
                table.add_row('', f'+{len(running) - self.MAX_RUNNING} more')
            return r_console.Group(header, table)


def run_tasks_pool(
    name: str,
    tasks: col.Sequence[my_task.Task],
    cache: my_cache.FileBuildCache,
    pool: concurrent.futures.Executor,
) -> list[my_run.TaskFailure]:
    """Run stale tasks in the pool, showing what the workers do."""
    stale, cached = my_run.tasks_filter_stale(tasks, cache)
    log.info('%s: %d to run, %d cached', name, len(stale), cached)
    if not stale:
        return []
    view = WorkerView(name, len(stale))
    with pool, r_live.Live(view, console=CONSOLE, refresh_per_second=8):
        failures = my_run.tasks_run(stale, cache, pool, on_done=view.update)
    if not CONSOLE.is_terminal:
        # outside of terminals, the final frame isn't ended with a newline
        CONSOLE.line()
    return failures


# </snip DEF_RUN_TASKS_POOL>


@step('Juicer: run tasks')
def main_juicer_run(cfg: Config, tasks: BuildTasks) -> None:
    """Run generated build tasks.

    Copy tasks are IO-bound, so they go into a thread pool, while encoding
    is CPU-bound and gets a process pool. Tasks that are still fresh in the
    build cache are skipped.
    """
    # <snip MAIN_JUICER_RUN>
    cache = my_cache.FileBuildCache(cfg.juicer.file_cache)

    failures = run_tasks_pool(
        'Copying',
        tasks.tasks_threaded,
        cache,
        concurrent.futures.ThreadPoolExecutor(),
    )
    failures += run_tasks_pool(
        'Encoding',
        tasks.tasks_mp,
        cache,
        concurrent.futures.ProcessPoolExecutor(),
    )

    for failure in failures:
        log.error('Task %s failed:\n%s', failure.task_id, failure.error)
    if failures:
        raise RuntimeError(f'{len(failures)} task(s) failed')
    # </snip MAIN_JUICER_RUN>


@step('Juicer: generating gml')
def main_juicer_gen_gml(
    cfg: Config,
    assets: list[Asset],
    atlas: Atlas | None = None,
    needs: dict[str, set[str]] | None = None,
) -> None:
    """It is time to finally integrate Clunkster into the project.

    For this we won't be "creating" scripts, but more like replacing ones
    that exist in the project. The list of scripts to be added into
    the project is
    [right down the road](index.md#integration-into-the-game).

    The game gets a table of every dehydrated asset (kind, resource, wet
    file), and a list of assets each room needs: every dehydrated asset of
    the room's clusters, or, in lean builds, exactly what the room uses
    (``needs``, see ``main_ex_lean``). Rooms with identical lists share
    one.

    This code contains traces of my own project configuration (sound registry,
    etc.), which might not be fully applicable for your project. You
    should review this code extra thoroughly before pasting it...
    """
    # <snip MAIN_JUICER_GEN_GML>
    log.info('Generating Clunkster scripts...')

    dir_scripts = my_asset.Script.type_get_dir(cfg.juicer.dir_out)
    scr_gen_type = dir_scripts / 'clunkster_gen_type.gml'
    scr_gen_init = dir_scripts / 'clunkster_gen_init.gml'
    scr_gen_validate_ctx = dir_scripts / 'clunkster_gen_validate_ctx.gml'
    for scr in (scr_gen_type, scr_gen_init, scr_gen_validate_ctx):
        if not scr.exists():
            raise FileNotFoundError(f'Generated script {scr.name} is missing')

    if atlas is not None:
        # atlased backgrounds aren't loaded anymore, their pages are
        assets = [asset for asset in assets if asset.name not in atlas.atlased]
        assets += [page.asset for page in atlas.pages]

    # dehydrated assets, numbered
    loaded_types = (my_asset.Sprite, my_asset.Background, AssetExtAudio)
    dehydrated = [
        asset
        for asset in assets
        if isinstance(asset, loaded_types) and not asset_resident(cfg, asset)
    ]
    slot = {asset.name: idx for idx, asset in enumerate(dehydrated)}
    rooms = [asset for asset in assets if isinstance(asset, my_asset.Room)]

    # assets needed per room
    room_slots: dict[str, list[int]] = {}
    for room in rooms:
        if needs is not None:
            names = needs.get(room.name, set())
        else:
            allowed = allowed_clusters(cfg, asset_cluster(cfg, room))
            names = {
                asset.name
                for asset in dehydrated
                if asset_cluster(cfg, asset) in allowed
            }
        room_slots[room.name] = sorted(slot[n] for n in names if n in slot)

    # common params for writing anything related to game maker
    text_params = {'encoding': 'utf-8', 'newline': '\n'}

    # technically, Game Juicer is in prod configuration, as far as the
    #  game is concerned, even if we use dev stubs instead of prod stubs
    scr_gen_type.write_text('return "prod"', **text_params)

    build_type = 'prod' if cfg.juicer.is_prod else 'dev'
    lines = [
        '///clunkster_gen_init()',
        '// AUTOGENERATED BY CLUNKSTER JUICER',
        f'global.__clunk_keep={cfg.juicer.keep_rooms}',
        f'global.__clunk_stub_spr="data/dry/spr_{build_type}.gmspr"',
        f'global.__clunk_stub_bg="data/dry/bg_{build_type}.gmbck"',
        'var _s0,_s1,_s3;',
        f'_s0="data/dry/snd_{build_type}.wav"',
        f'_s1="data/dry/mus_{build_type}.ogg"',
        f'_s3="data/dry/snd3_{build_type}.ogg"',
    ]
    for idx, asset in enumerate(dehydrated):
        file = asset_wet_path(cfg, asset).as_posix()
        prefix = f'global.__clunk_kind[{idx}]='
        if isinstance(asset, my_asset.Sprite):
            lines.append(f'{prefix}0 global.__clunk_res[{idx}]={asset.name}')
        elif isinstance(asset, my_asset.Background):
            lines.append(f'{prefix}1 global.__clunk_res[{idx}]={asset.name}')
        else:
            # sound kind, streamed, preload
            if isinstance(asset, AssetExtBgm):
                kind, streamed, preload = 1, 1, 1
            elif isinstance(asset, AssetExtSfx):
                kind, streamed, preload = 0, 0, 1
            else:
                kind, streamed, preload = 3, 1, 2
            lines.append(
                f'{prefix}2 global.__clunk_res[{idx}]={asset.name}'
                f' global.__clunk_skind[{idx}]={kind}'
                f' global.__clunk_stream[{idx}]={streamed}'
                f' global.__clunk_pre[{idx}]={preload}'
                f' global.__clunk_stub[{idx}]=_s{kind}'
            )
        lines.append(f'global.__clunk_file[{idx}]="{file}"')
    lines.append(f'global.__clunk_count={len(dehydrated)}')

    # room lists, parsed from strings to keep the script short
    lists: dict[tuple[int, ...], int] = {}
    for slots in room_slots.values():
        if slots:
            lists.setdefault(tuple(slots), len(lists))
    lines.append('var _ls,_l,_k,_s,_p;')
    lines.extend(
        f'_ls[{k}]="{",".join(map(str, slots))}"' for slots, k in lists.items()
    )
    lines.extend((
        f'for (_k=0;_k<{len(lists)};_k+=1) {{',
        '    _l[_k]=ds_list_create()',
        '    _s=_ls[_k]+","',
        '    while _s!="" {',
        '        _p=string_pos(",",_s)',
        '        ds_list_add(_l[_k],real(string_copy(_s,1,_p-1)))',
        '        _s=string_delete(_s,1,_p)',
        '    }',
        '}',
    ))
    lines.extend(
        f'ds_map_add(global.__clunk_rooms,{room},_l[{lists[tuple(slots)]}])'
        for room, slots in room_slots.items()
        if slots
    )
    scr_gen_init.write_text('\n'.join(lines), **text_params)

    # context guards must pass in rooms of their clusters (fatal), and should
    #  fail in rooms where the dependency graphs assumed they do, since
    #  assets behind them aren't loaded there (a warning, shims pass anywhere)
    gml_validate = [
        '///clunkster_gen_validate_ctx()',
        '// AUTOGENERATED BY CLUNKSTER JUICER',
        'var _violations,_warnings;_violations="" _warnings=""',
    ]
    for guard, granted in cfg.context_rules.items():
        for room in rooms:
            cluster = asset_cluster(cfg, room)
            if cluster in granted:
                gml_validate.append(
                    f'if not {guard}({room.name}) _violations+="Failed ctx '
                    f'check on {room.name} and {guard}"+lf'
                )
            elif not allowed_clusters(cfg, cluster) & granted:
                gml_validate.append(
                    f'if {guard}({room.name}) _warnings+="{guard} passes on '
                    f'{room.name}, assets behind it are not loaded there"+lf'
                )
    gml_validate.extend((
        'if _violations!="" show_error(_violations,1)',
        'if _warnings!="" show_error(_warnings,0)',
    ))
    scr_gen_validate_ctx.write_text('\n'.join(gml_validate), **text_params)

    log.info(
        '%d dehydrated assets, %d room lists',
        len(dehydrated),
        len(lists),
    )

    # <md>
    # Once the GML files are generated, the project should become playable.
    # Last possible step would be adding the automatic compile.
    # </md>
    # </snip MAIN_JUICER_GEN_GML>


@step('Juicer: compiling the game')
def main_juicer_gm_compile(cfg: Config) -> subprocess.Popen[bytes] | None:
    r"""This is it Luigi.

    Game Maker's CLI for compiling is:

    ::

        GameMaker.exe [project.gm82] --build [exe]

    And Game Maker's exe is usually at:

    ::

        C:\Users\user\AppData\Roaming\GameMaker8.2\GameMaker.exe

    but I also added a new environment variable ``GM82_PATH`` just for that
    one guy.

    Returns the launched game's process (if launching is on), so that the
    development loop can close it before the next build.
    """
    # <snip MAIN_JUICER_GM_COMPILE>
    log.info('Jostling Game Maker 8.2 compiler...')

    project_file = cfg.juicer.dir_out / cfg.juicer.fname_gm82
    output_exe = cfg.juicer.dir_out / 'game.exe'

    custom_path = os.getenv('GM82_PATH')
    if custom_path is not None:
        gm_exe = Path(custom_path)
    else:
        appdata_str = os.getenv('APPDATA')
        if appdata_str is None:
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

    log.info('Compiling %s...', output_exe.name)

    try:
        subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
            [str(gm_exe), str(project_file), '--build', str(output_exe)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(
            f'GameMaker 8.2 compilation failed with exit code {e.returncode}'
        ) from e

    log.info('Build completely successfully!')
    if not cfg.juicer.launch:
        return None
    return subprocess.Popen(  # ruff: ignore[subprocess-without-shell-equals-true]
        [str(output_exe)],
        cwd=cfg.juicer.dir_out,
        creationflags=subprocess.DETACHED_PROCESS
        | subprocess.CREATE_NEW_PROCESS_GROUP,
    )
    # </snip MAIN_JUICER_GM_COMPILE>


@step('Juicer: packaging')
def main_juicer_package(cfg: Config) -> Path:
    """Pack the game into a zip.

    The zip holds the compiled exe, named after the project, and the data
    folder (wet assets, stubs and whatever else the game loads from there).
    """
    # <snip MAIN_JUICER_PACKAGE>
    dir_out = cfg.juicer.dir_out
    name = Path(cfg.juicer.fname_gm82).stem
    file_zip = dir_out / f'{name}.zip'
    data_files = sorted(
        file for file in (dir_out / 'data').rglob('*') if file.is_file()
    )
    # already compressed formats aren't worth deflating
    stored_suffixes = {'.ogg', '.mp3', '.png', '.jpg', '.zip'}

    file_temp = file_zip.with_suffix('.tmp')
    with zipfile.ZipFile(
        file_temp, 'w', compression=zipfile.ZIP_DEFLATED
    ) as archive:
        archive.write(dir_out / 'game.exe', f'{name}.exe')
        for file in progress(data_files, 'Packaging'):
            archive.write(
                file,
                file.relative_to(dir_out).as_posix(),
                compress_type=zipfile.ZIP_STORED
                if file.suffix.lower() in stored_suffixes
                else zipfile.ZIP_DEFLATED,
            )
    file_temp.replace(file_zip)
    log.info(
        'Packaged %s (%.1f MB)', file_zip, file_zip.stat().st_size / 2**20
    )
    # </snip MAIN_JUICER_PACKAGE>
    return file_zip


@dataclasses.dataclass(frozen=True, slots=True, order=True)
class BMTile:
    """Tile applicable for backgrounds merge."""

    bg_name: str
    left: int
    top: int
    width: int
    height: int


def main_bm_get(
    cfg: Config, assets: list[Asset], dependencies: list[Dependency]
) -> None:
    """Get mergeable backgrounds."""
    bgs_used_code: set[str] = set()
    for dep in dependencies:
        if not isinstance(dep.target_asset, my_asset.Background):
            continue
        if isinstance(dep.source_asset, my_asset.Room):
            df = dep.location.file
            if df.suffix == '.txt' and all(c.isdigit() for c in df.stem):
                # allowed to be tiles
                continue
            if df.name == 'room.txt':
                # TODO this case is doable
                pass
        bgs_used_code.add(dep.target_asset.name)
    bgs_unused: set[str] = {
        bg.name for bg in assets if isinstance(bg, my_asset.Background)
    } - bgs_used_code
    print('\n'.join(sorted(bgs_unused)))

    # get them usages
    bm_tiles: set[BMTile] = set()
    for room in assets:
        if not isinstance(room, my_asset.Room):
            continue
        for layer in room.get_room_layers(cfg.project.root):
            for tile in room.get_room_layer(cfg.project.root, layer):
                if tile.bg not in bgs_unused:
                    continue
                bm_tiles.add(
                    BMTile(
                        bg_name=tile.bg,
                        left=tile.left,
                        top=tile.top,
                        width=tile.width,
                        height=tile.height,
                    )
                )
    pprint(sorted(bm_tiles))


def _run_tutorials(cfg: Config) -> None:
    main_ex_start(cfg)
    assets = main_ex_aliases(cfg)
    scan_cache = my_scan_cache.ScanCache(cfg.scan_cache)
    main_ex_scan(cfg, assets, scan_cache)
    scan_cache.save()


def test_tutorials() -> None:
    """Ensure the tutorial snippets don't rot."""
    dummy_proj = Path(__file__).parent / 'tests' / 'dummy_project'
    if not dummy_proj.exists():
        return  # skip if dummy project isn't set up yet

    # TODO dummy project and config
    cfg = Config(
        project=my_proj.Project(dummy_proj),
        alias=ALIAS,
        lint_rules=LINT_RULES,
        context_rules=CONTEXT_RULES,
        extra_roots=EXTRA_ROOTS,
        juicer=JUICER,
        scan_cache=Path(__file__).parent / 'scan_cache.json',
    )
    _run_tutorials(cfg)


def _load_private(config_dir: Path) -> Config:
    file_private_config = config_dir / 'config.json'
    if not file_private_config.exists():
        raise FileNotFoundError(
            f'Config file not found: {file_private_config}'
        )

    config = json.loads(file_private_config.read_text())

    juicer = ConfJuicer(
        is_prod=False,
        dir_out=config_dir.parent / '_build',
        dir_dry=JUICER.dir_dry,  # og dir
        rel_dir_wet=JUICER.rel_dir_wet,
        file_cache=config_dir.parent / 'clunkster_cache.json',
        fname_gm82=config['fname_gm82'],
        scramble_models=config.get('scramble_model_names', True),
        crop_found_tiles=config.get('crop_smart_tiles', False),
        keep_rooms=config.get('keep_rooms', 1),
    )

    file_private_alias = config_dir / 'alias.json'
    alias = json.loads(file_private_alias.read_text(encoding='utf-8'))

    file_private_lint_rules = config_dir / 'lint_rules.json'
    rules = json.loads(file_private_lint_rules.read_text(encoding='utf-8'))
    lint_rules = {cluster: set(allowed) for cluster, allowed in rules.items()}

    file_private_context_rules = config_dir / 'context_rules.json'
    file_blacklist = config_dir / 'blacklist.json'
    rules = json.loads(file_private_context_rules.read_text(encoding='utf-8'))
    context_rules = {guard: set(granted) for guard, granted in rules.items()}

    return Config(
        project=my_proj.Project(config_dir.parent / 'source'),
        alias=alias,
        lint_rules=lint_rules,
        context_rules=context_rules,
        extra_roots=EXTRA_ROOTS,
        juicer=juicer,
        scan_cache=config_dir.parent / 'clunkster_scan_cache.json',
        common_budget_mb=config.get('common_budget_mb', 500),
        blacklist=(
            json.loads(file_blacklist.read_text(encoding='utf-8'))
            if file_blacklist.exists()
            else {}
        ),
    )


# <snip DEF_RUN_CHECK>
def run_check(
    cfg: Config, scan_cache: my_scan_cache.ScanCache
) -> tuple[Config, list[Asset], list[Dependency], dict[str, RoomGraph]]:
    """Run all checks.

    :return: Config with assets moved to Common, the assets, their
      dependencies and room graphs.
    """
    main_ex_lint_tree(cfg)
    assets = main_ex_aliases(cfg)
    deps, term_uses = main_ex_scan(cfg, assets, scan_cache)
    main_ex_lint_blacklist(cfg, term_uses)
    # main_ex_lint_unused(cfg, deps, assets)

    promotions: dict[str, Promotion] = {}
    cfg = main_ex_promote_refs(cfg, deps, promotions)
    # graphs don't depend on moved assets, rooms are never moved
    room_data = main_ex_graph(cfg, assets, deps)
    while True:
        moved = len(promotions)
        cfg = main_ex_promote_rooms(cfg, assets, room_data, promotions)
        if len(promotions) == moved:
            break
        # moved assets' references now have to be allowed for Common
        cfg = main_ex_promote_refs(cfg, deps, promotions)

    main_ex_lint_unused_graph(cfg, assets, room_data)
    main_ex_report_promotions(cfg, promotions)
    return cfg, assets, deps, room_data


def run_build(
    cfg: Config, scan_cache: my_scan_cache.ScanCache | None
) -> subprocess.Popen[bytes] | None:
    """Build the game, then launch and/or package it, per juicer config.

    Without a scan cache, reference checks are skipped (quick builds), and
    assets stay in the clusters of their folders.

    :return: Launched game's process, if any.
    """
    deps: list[Dependency] | None = None
    room_data: dict[str, RoomGraph] = {}
    if scan_cache is None:
        main_ex_lint_tree(cfg)
        assets = main_ex_aliases(cfg)
    else:
        cfg, assets, deps, room_data = run_check(cfg, scan_cache)
    atlas: Atlas | None = None
    if cfg.juicer.atlas:
        if deps is None:
            raise ValueError('Atlas needs reference checks')
        protection = main_ex_tile_protection(cfg, assets)
        atlas = main_ex_atlas(cfg, assets, deps, protection)
    needs: dict[str, set[str]] | None = None
    if cfg.juicer.lean:
        if deps is None or not cfg.juicer.hash_names:
            raise ValueError('Lean builds need reference checks and prod')
        cfg, needs = main_ex_lean(cfg, assets, room_data, atlas)
    tasks = main_juicer_gen_tasks(cfg, assets, atlas)
    main_juicer_run(cfg, tasks)
    main_juicer_gen_gml(cfg, assets, atlas, needs)
    game = main_juicer_gm_compile(cfg)
    if cfg.juicer.package:
        main_juicer_package(cfg)
    return game


def project_watch_filter(root: Path) -> watchfiles.BaseFilter:
    """Filter for watching project's source files."""

    class ProjectFilter(watchfiles.DefaultFilter):
        @override
        def __call__(self, change: watchfiles.Change, path: str) -> bool:
            # GameMaker's cache isn't part of the project, and the game
            #  writes saves into save folder (symlinked into the build)
            top = Path(path).relative_to(root).parts[:1]
            return super().__call__(change, path) and top not in {
                ('cache',),
                ('save',),
            }

    return ProjectFilter()


# </snip DEF_RUN_CHECK>


def main_ex_watch(cfg: Config) -> None:
    """Rerun all linters whenever project files change.

    Watch mode makes cluster violations show up right after saving, not at
    build time. Thanks to the scan cache only changed files get rescanned,
    so reruns take a second or two.

    Linter errors don't stop the watch; it reports them and waits for the
    next change. Uses [watchfiles](https://github.com/samuelcolvin/watchfiles)
    for watching.
    """
    # <snip MAIN_EX_WATCH>
    root = cfg.project.root
    scan_cache = my_scan_cache.ScanCache(cfg.scan_cache)

    def check() -> None:
        errors = 0
        try:
            run_check(cfg, scan_cache)
        except my_lint.LinterFoundError as e:
            errors = len(e.violations)
        except Exception:
            # e.g. a file caught in the middle of being saved
            log.exception('Check failed')
        if errors:
            log.error('Found %d error(s)', errors)
        log.info('Watching %s for changes, Ctrl+C to stop', root)

    # the watcher yields an empty set on timeout, which is used to run the
    #  first check once it's watching, so that no changes are missed
    first = True
    watcher = watchfiles.watch(
        root,
        watch_filter=project_watch_filter(root),
        yield_on_timeout=True,
        rust_timeout=200,
    )
    try:
        for changes in watcher:
            if first:
                first = False
                check()
                continue
            if not changes:
                continue
            if CONSOLE.is_terminal:
                CONSOLE.clear()
            log.info('%d file(s) changed', len(changes))
            # fresh project, so that file reads aren't cached from before
            cfg = dataclasses.replace(cfg, project=my_proj.Project(root))
            check()
    finally:
        # saved once on exit, saving on every change takes too long
        scan_cache.save()
    # </snip MAIN_EX_WATCH>


def main_ex_dev(cfg: Config) -> None:
    """Build and run the game on demand.

    Development loop for the frequent "small edit, build, play" cycle:
    press Enter to check and build the project and launch the game. The
    game launched by the previous build is closed first, since the compiler
    can't overwrite a running ``game.exe``. Caches stay in memory between
    builds, so only what changed gets processed.

    Saved changes are reported as they happen. Type ``a`` to toggle
    building automatically after every save, and ``q`` to quit.
    """
    # <snip MAIN_EX_DEV>
    root = cfg.project.root
    scan_cache = my_scan_cache.ScanCache(cfg.scan_cache)
    # commands from the keyboard ('', 'a', 'q') and the watcher ('changed')
    commands: queue.Queue[str] = queue.Queue()
    stop_watching = threading.Event()

    def read_input() -> None:
        for line in sys.stdin:
            commands.put(line.strip().lower())
        commands.put('q')

    def watch_changes() -> None:
        for _ in watchfiles.watch(
            root,
            watch_filter=project_watch_filter(root),
            stop_event=stop_watching,
        ):
            commands.put('changed')

    threading.Thread(target=read_input, daemon=True).start()
    threading.Thread(target=watch_changes, daemon=True).start()

    usage = 'Enter: build and run, a: toggle auto build, q: quit'
    log.info(usage)
    auto_build = False
    game: subprocess.Popen[bytes] | None = None
    try:
        while True:
            try:
                # timeout, so that Ctrl+C gets through on Windows
                command = commands.get(timeout=0.5)
            except queue.Empty:
                continue

            if command == 'q':
                break
            if command == 'a':
                auto_build = not auto_build
                log.info('Auto build: %s', 'on' if auto_build else 'off')
                continue
            if command == 'changed' and not auto_build:
                log.info('Project changed, press Enter to build')
                continue
            if command not in {'', 'changed'}:
                log.info(usage)
                continue

            if CONSOLE.is_terminal:
                CONSOLE.clear()
            if game is not None and game.poll() is None:
                log.info('Closing the game')
                game.terminate()
                game.wait()
            # fresh project, so that file reads aren't cached from before
            cfg = dataclasses.replace(cfg, project=my_proj.Project(root))
            errors = 0
            try:
                game = run_build(cfg, scan_cache)
            except my_lint.LinterFoundError as e:
                errors = len(e.violations)
            except Exception:
                log.exception('Build failed')
            if errors:
                log.error('Build stopped, found %d error(s)', errors)
            log.info(usage)
    finally:
        stop_watching.set()
        scan_cache.save()
    # </snip MAIN_EX_DEV>


def _build_profile(
    cfg: Config, config_dir: Path, mode: str, flags: col.Collection[str] = ()
) -> Config:
    """Adjust the juicer config for the build mode and flags."""
    unknown = set(flags) - {'--lean', '--atlas'}
    if unknown or (flags and mode != 'prod'):
        raise ValueError(
            f'Unknown flags {sorted(unknown)}'
            if unknown
            else '--lean and --atlas are for prod builds'
        )
    if mode == 'quick':
        juicer = dataclasses.replace(cfg.juicer, encode_audio=False)
        return dataclasses.replace(cfg, juicer=juicer)
    if mode == 'atlas':
        # own folder: rooms are copies there, not a symlink to the source
        juicer = dataclasses.replace(
            cfg.juicer,
            dir_out=config_dir.parent / '_build_atlas',
            file_cache=config_dir.parent / 'clunkster_cache_atlas.json',
            atlas=True,
            dump_atlas=True,
        )
        return dataclasses.replace(cfg, juicer=juicer)
    if mode != 'prod':
        return cfg

    # salt for hashed names, kept out of the config so that it doesn't end
    #  up in the repository
    file_salt = config_dir.parent / 'clunkster_salt.txt'
    if not file_salt.exists():
        file_salt.write_text(secrets.token_hex(16), encoding='utf-8')
    juicer = dataclasses.replace(
        cfg.juicer,
        is_prod=True,
        dir_out=config_dir.parent / '_build_prod',
        file_cache=config_dir.parent / 'clunkster_cache_prod.json',
        hash_names=True,
        name_salt=file_salt.read_text(encoding='utf-8').strip(),
        # package=True,     # temp
        launch=False,
        atlas='--atlas' in flags,
        lean='--lean' in flags,
    )
    return dataclasses.replace(cfg, juicer=juicer)


def main() -> None:
    """Pipeline private entrypoint.

    Usage: ``main.py <config dir> [mode]``, where mode is one of
    ``build`` (default), ``quick``, ``prod``, ``atlas``, ``check``, ``watch``,
    ``dev`` or ``test``:

    - ``build``: check references, build and launch the game
    - ``quick``: build and launch, skipping reference checks and audio
      encoding
    - ``prod [--atlas] [--lean]``: check references, build into
      ``_build_prod`` with hashed wet asset names, and pack it into a zip;
      ``--atlas`` adds atlases and baked tiles, ``--lean`` makes rooms load
      exactly the assets they use
    - ``atlas``: like ``build``, but with atlases and baked tiles, into
      ``_build_atlas``, and atlas pages written to ``atlas_dump`` there (for
      testing them without a full prod build)
    """
    config_dir = Path(sys.argv[1]).resolve()
    mode = sys.argv[2] if len(sys.argv) > 2 else 'build'
    cfg = _build_profile(
        _load_private(config_dir), config_dir, mode, sys.argv[3:]
    )

    # allow testing tutorials on private data as well
    if mode == 'test':
        _run_tutorials(cfg)
        return

    setup_output()

    if mode == 'check':
        scan_cache = my_scan_cache.ScanCache(cfg.scan_cache)
        try:
            run_check(cfg, scan_cache)
        finally:
            scan_cache.save()
        log.info('All ok, exiting regardless :D')
        return
    if mode == 'watch':
        with contextlib.suppress(KeyboardInterrupt):
            main_ex_watch(cfg)
        return
    if mode == 'dev':
        with contextlib.suppress(KeyboardInterrupt):
            main_ex_dev(cfg)
        return
    if mode == 'quick':
        run_build(cfg, None)
        return
    if mode not in {'build', 'prod', 'atlas'}:
        raise ValueError(f'Unknown mode: {mode}')

    scan_cache = my_scan_cache.ScanCache(cfg.scan_cache)
    try:
        run_build(cfg, scan_cache)
    finally:
        scan_cache.save()


if __name__ == '__main__':
    main()
