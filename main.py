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
import shutil
import subprocess  # ruff: ignore[suspicious-subprocess-import]
import sys
import threading
import time
import warnings
from abc import ABC
from pathlib import Path
from pprint import pprint
from typing import override

import rustworkx as rx
import watchfiles
from ahocorasick import Automaton  # ty: ignore[unresolved-import]
from gmcodec import core as gmc_core
from gmcodec import file as gmc_file
from gmcodec import model as gmc_model
from gmcodec import validate as gmc_validate
from PIL import Image
from rich import console as r_console
from rich import progress as r_progress
from rich import table as r_table
from rich.logging import RichHandler

from clunkster import asset as my_asset
from clunkster import lint as my_lint
from clunkster import project as my_proj
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
    # assets moved to Common because of cluster violations, derived by the
    #  cluster checks (see main_ex_promote_refs)
    promoted: frozenset[str] = frozenset()
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


# <snip DEF_ASSET_WET_FNAME>
def asset_wet_fname(asset: my_asset.Asset) -> str:
    """Get asset's wet file name."""
    if isinstance(asset, AssetExtSfx):
        return f'{asset.name_clean}.wav'
    if isinstance(asset, (AssetExtSfx3, AssetExtBgm)):
        return f'{asset.name_clean}.ogg'
    if isinstance(asset, my_asset.Sprite):
        return f'{asset.name}.gmspr'
    if isinstance(asset, my_asset.Background):
        return f'{asset.name}.gmbck'
    raise NotImplementedError('Asset type not supported')


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


@step('Scanning references')
def main_ex_scan(
    cfg: Config, assets: list[Asset], scan_cache: my_scan_cache.ScanCache
) -> list[Dependency]:
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
    """
    # <snip MAIN_EX_SCAN>
    names = sorted(asset.name for asset in assets)
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
    dependencies = [
        Dependency(
            location=my_location.Location(
                file=file_path,
                loc_index=match.idx,
                loc_line=match.line,
                loc_column=match.column,
            ),
            source_asset=asset,
            target_asset=name2asset[match.target],
            contexts=match.contexts,
        )
        for asset, file_path in scans
        for match in file_matches[file_path]
    ]

    log.info('Found %d total dependency references.', len(dependencies))
    # </snip MAIN_EX_SCAN>
    return dependencies


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
def next_pow2(n: int) -> int:
    """Get the smallest power of two that is at least ``n``."""
    return 1 << max(0, (n - 1).bit_length())


def asset_ram_estimate(cfg: Config, asset: Asset) -> int:
    """Estimate how much RAM a loaded asset takes, in bytes.

    Only covers assets that get dehydrated, others always stay in the base
    executable anyway. Rough GameMaker 8.2 model:

    - sprites: every frame is a texture padded to power of two sizes, 4 bytes
      per pixel, plus a collision mask of 1 byte per pixel (one per frame if
      masks are separate)
    - backgrounds: a single padded texture
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
        texture = next_pow2(width) * next_pow2(height) * 4
        return meta.frames * texture + masks * width * height
    if isinstance(asset, my_asset.Background):
        image = asset.get_background_image(root)
        if not image.exists():
            return 0
        width, height = my_parse_png.size(image)
        return next_pow2(width) * next_pow2(height) * 4
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
        dir_wet_root: Path,
    ) -> None:
        """Initialize the task.

        :param sprite: Sprite to encode.
        :param dir_input_root: Input project root.
        :param dir_wet_root: Wet dir (e.g. ``<output>/data/chunks/<cluster>``).
        """
        file_metadata = sprite.get_sprite_metadata_file(dir_input_root)
        self.sprite_meta = sprite.get_sprite_metadata(dir_input_root)
        self.sprite_images = tuple(
            sprite.get_sprite_image(dir_input_root, frame)
            for frame in range(self.sprite_meta.frames)
        )

        self.file_output_gmspr = (
            dir_wet_root
            / type(sprite).type_get_dir_rel()
            / asset_wet_fname(sprite)
        )

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
        dir_wet_root: Path,
    ) -> None:
        """Initialize the task.

        :param background: Background to encode.
        :param dir_input_root: Input project root.
        :param dir_wet_root: Wet dir (e.g. ``<output>/data/chunks/<cluster>``).
        """
        file_metadata = background.get_background_metadata_file(dir_input_root)
        self.background_meta = background.get_background_metadata(
            dir_input_root
        )
        self.background_image = background.get_background_image(dir_input_root)

        self.file_output_gmbck = (
            dir_wet_root
            / type(background).type_get_dir_rel()
            / asset_wet_fname(background)
        )

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
        dir_wet_root: Path,
    ) -> None:
        """Initialize the task.

        :param audio: Background to compress.
        :param dir_wet_root: Wet dir (e.g. ``<output>/data/chunks/<cluster>``).
        """
        self.audio = audio
        self.file_output = (
            dir_wet_root
            / type(audio).type_get_dir_rel()
            / asset_wet_fname(audio)
        )

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


# <snip CLS_JUICE_BUILD_TASKS>
@dataclasses.dataclass(frozen=True, slots=True)
class BuildTasks:
    """Build tasks."""

    tasks_threaded: tuple[my_task.Task, ...]
    tasks_mp: tuple[my_task.Task, ...]


# </snip CLS_JUICE_BUILD_TASKS>


@step('Juicer: generate tasks')
def main_juicer_gen_tasks(cfg: Config, assets: list[Asset]) -> BuildTasks:
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
    dir_wet = cfg.juicer.dir_out / cfg.juicer.rel_dir_wet
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
                    # symlink
                    pth_symlink(pth)
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
        # copy yyd
        type_copy_yyd(my_asset.Background)

        for bg in asset_backgrounds:
            if asset_cluster(cfg, bg) == 'Common':
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
                    dir_wet_root=dir_wet / asset_cluster(cfg, bg),
                )
            )

    def map_sprites() -> None:
        """Map sprites."""
        # copy yyd
        type_copy_yyd(my_asset.Sprite)

        for sprite in asset_sprites:
            if asset_cluster(cfg, sprite) == 'Common':
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
                    dir_wet_root=dir_wet / asset_cluster(cfg, sprite),
                )
            )

    def map_audio() -> None:
        """Map music."""
        # no yyd files
        for audio in asset_audio:
            if asset_cluster(cfg, audio) == 'Common':
                # copy as is
                copy_rebase(audio.file)
                continue
            # no metadata or dry stuff
            tasks_mp.append(
                TaskCompressAudio(
                    audio=audio,
                    dir_wet_root=dir_wet / asset_cluster(cfg, audio),
                )
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

    build_tasks = BuildTasks(
        tasks_threaded=tuple(tasks_threaded),
        tasks_mp=tuple(tasks_mp),
    )
    # </snip MAIN_JUICER_GEN_TASKS>
    return build_tasks  # ruff: ignore[unnecessary-assign]


# <snip DEF_RUN_TASKS_POOL>
def run_tasks_pool(
    name: str,
    tasks: col.Sequence[my_task.Task],
    cache: my_cache.FileBuildCache,
    pool: concurrent.futures.Executor,
) -> list[my_run.TaskFailure]:
    """Run stale tasks in the pool with a progress bar."""
    stale, cached = my_run.tasks_filter_stale(tasks, cache)
    log.info('%s: %d to run, %d cached', name, len(stale), cached)
    if not stale:
        return []
    with (
        pool,
        r_progress.Progress(
            *r_progress.Progress.get_default_columns(),
            r_progress.MofNCompleteColumn(),
            console=CONSOLE,
        ) as bar,
    ):
        bar_task = bar.add_task(name, total=len(stale))
        return my_run.tasks_run(
            stale, cache, pool, on_done=lambda *_: bar.advance(bar_task)
        )


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
def main_juicer_gen_gml(cfg: Config, assets: list[Asset]) -> None:
    """It is time to finally integrate Clunkster into the project.

    For this we won't be "creating" scripts, but more like replacing ones
    that exist in the project. The list of scripts to be added into
    the project is
    [right down the road](index.md#integration-into-the-game).

    This code contains traces of my own project configuration (sound registry,
    etc.), which might not be fully applicable for your project. You
    should review this code extra thoroughly before pasting it...
    """
    # <snip MAIN_JUICER_GEN_GML>
    log.info('Generating Clunkster scripts...')

    dir_scripts = my_asset.Script.type_get_dir(cfg.juicer.dir_out)

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
        if asset_cluster(cfg, asset) == 'Common':
            # skip common assets
            continue

        dehydrated_clusters.add(asset_cluster(cfg, asset))

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

        asset_name_to_file_wet[asset.name] = (
            cfg.juicer.rel_dir_wet
            / asset_cluster(cfg, asset)
            / type(asset).type_get_dir_rel()
            / asset_wet_fname(asset)
        ).as_posix()

    # common params for writing anything related to game maker
    text_params = {'encoding': 'utf-8', 'newline': '\n'}

    # write the clunkster_gen_type

    # technically, Game Juicer is in prod configuration, as far as the
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
        room_cluster = asset_cluster(cfg, room)
        cluster_to_rooms.setdefault(room_cluster, []).append(room.name)

        needed_clusters = allowed_clusters(cfg, room_cluster)
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

    for context_guard, granted_clusters in cfg.context_rules.items():
        for clusters in granted_clusters:
            gml_validate.extend(
                f'if not {context_guard}({room}) _violations+="Failed ctx '
                f'check on {room} and {context_guard}"+lf'
                for room in cluster_to_rooms.get(clusters, ())
            )
    gml_validate.append('if _violations!="" show_error(_violations,1)')

    scr_gen_validate_ctx.write_text('\n'.join(gml_validate), **text_params)

    # write the clunkster_gen_init_audio, prepare the code for music/sound

    build_type = 'prod' if cfg.juicer.is_prod else 'dev'
    stub_sfx = f'data/dry/snd_{build_type}.wav'
    stub_sfx3 = f'data/dry/snd3_{build_type}.ogg'
    stub_bgm = f'data/dry/mus_{build_type}.ogg'
    stub_bg = f'data/dry/bg_{build_type}.gmbck'
    stub_spr = f'data/dry/spr_{build_type}.gmspr'

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
        cluster = asset_cluster(cfg, asset)
        cluster_load_code.setdefault(cluster, []).append(
            f'    sound_replace({asset.name},"{pth_wet}",{kind},{preload}) '
            f'sndreg_apply({asset.name})'
        )
        # populate unload code
        cluster_unload_code.setdefault(cluster, []).append(
            f'    sound_replace({asset.name},{stub_var},{kind},{preload})'
        )

    scr_gen_init_audio.write_text('\n'.join(gml_gen_init_audio), **text_params)

    # prepare the code for sprites/backgrounds

    for asset in assets_spr:
        # no need for any init code
        pth_wet = asset_name_to_file_wet[asset.name]
        cluster = asset_cluster(cfg, asset)
        cluster_load_code.setdefault(cluster, []).append(
            f'    sprite_replace_sprite({asset.name},"{pth_wet}")'
        )
        cluster_unload_code.setdefault(cluster, []).append(
            f'    sprite_replace_sprite({asset.name},_p_spr)'
        )

    for asset in assets_bg:
        # no need for any init code
        pth_wet = asset_name_to_file_wet[asset.name]
        cluster = asset_cluster(cfg, asset)
        cluster_load_code.setdefault(cluster, []).append(
            f'    background_replace_background({asset.name},"{pth_wet}")'
        )
        cluster_unload_code.setdefault(cluster, []).append(
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

    # <md>
    # Once the GML files are generated, the project should become playable.
    # Last possible step would be adding the automatic compile.
    # </md>
    # </snip MAIN_JUICER_GEN_GML>


@step('Juicer: compiling the game')
def main_juicer_gm_compile(cfg: Config) -> subprocess.Popen[bytes]:
    r"""This is it Luigi.

    Game Maker's CLI for compiling is:

    ::

        GameMaker.exe [project.gm82] --build [exe]

    And Game Maker's exe is usually at:

    ::

        C:\Users\user\AppData\Roaming\GameMaker8.2\GameMaker.exe

    but I also added a new environment variable ``GM82_PATH`` just for that
    one guy.

    Returns the launched game's process, so that the development loop can
    close it before the next build.
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
    return subprocess.Popen(  # ruff: ignore[subprocess-without-shell-equals-true]
        [str(output_exe)],
        cwd=cfg.juicer.dir_out,
        creationflags=subprocess.DETACHED_PROCESS
        | subprocess.CREATE_NEW_PROCESS_GROUP,
    )
    # </snip MAIN_JUICER_GM_COMPILE>


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
    )

    file_private_alias = config_dir / 'alias.json'
    alias = json.loads(file_private_alias.read_text(encoding='utf-8'))

    file_private_lint_rules = config_dir / 'lint_rules.json'
    rules = json.loads(file_private_lint_rules.read_text(encoding='utf-8'))
    lint_rules = {cluster: set(allowed) for cluster, allowed in rules.items()}

    file_private_context_rules = config_dir / 'context_rules.json'
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
    )


# <snip DEF_RUN_CHECK>
def run_check(
    cfg: Config, scan_cache: my_scan_cache.ScanCache
) -> tuple[Config, list[Asset]]:
    """Run all checks.

    :return: Config with assets moved to Common, and the assets.
    """
    main_ex_lint_tree(cfg)
    assets = main_ex_aliases(cfg)
    deps = main_ex_scan(cfg, assets, scan_cache)
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
    return cfg, assets


def run_build(
    cfg: Config, scan_cache: my_scan_cache.ScanCache
) -> subprocess.Popen[bytes]:
    """Run all checks, build the game and launch it."""
    cfg, assets = run_check(cfg, scan_cache)
    tasks = main_juicer_gen_tasks(cfg, assets)
    main_juicer_run(cfg, tasks)
    main_juicer_gen_gml(cfg, assets)
    return main_juicer_gm_compile(cfg)


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


def main() -> None:
    """Pipeline private entrypoint.

    Usage: ``main.py <config dir> [build|check|watch|dev|test]``, defaults to
    ``build``.
    """
    cfg = _load_private(Path(sys.argv[1]).resolve())
    mode = sys.argv[2] if len(sys.argv) > 2 else 'build'

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
    if mode != 'build':
        raise ValueError(f'Unknown mode: {mode}')

    scan_cache = my_scan_cache.ScanCache(cfg.scan_cache)
    try:
        run_build(cfg, scan_cache)
    finally:
        scan_cache.save()


if __name__ == '__main__':
    main()
