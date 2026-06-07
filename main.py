"""Main pipeline, together with examples."""

import collections.abc as col
import json
import multiprocessing as mp
import warnings
from concurrent import futures
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path

import tqdm
from ahocorasick import Automaton  # ty: ignore[unresolved-import]

from clunkster.analyze import (
    location as my_analyze_location,
)
from clunkster.analyze import (
    scan_dep as my_analyze_scan_dep,
)
from clunkster.parse import tree as my_parse_tree

# --- COG_START: CLS_ASSET_TYPE ---
# asset_name, tree_path (asset name not appended)
TreeEntry = tuple[str, tuple[str, ...]]


class AssetType(Enum):
    """GameMaker8.2 asset type."""

    BACKGROUND = auto()
    FONT = auto()
    OBJECT = auto()
    PATH = auto()
    ROOM = auto()
    SCRIPT = auto()
    SPRITE = auto()
    SOUND = auto()

    DATA_SFX = auto()
    DATA_MUSIC = auto()

    def is_builtin(self) -> bool:
        """Check whether this asset type is builtin or not."""
        return self in {
            AssetType.BACKGROUND,
            AssetType.FONT,
            AssetType.OBJECT,
            AssetType.PATH,
            AssetType.ROOM,
            AssetType.SCRIPT,
            AssetType.SPRITE,
            AssetType.SOUND,
        }

    def exists(self, project_root: Path) -> bool:
        """Check whether this asset type exists in the project."""
        return (project_root / self.get_dir()).exists()

    def get_dir(self) -> str:
        """Get project's directory name for given asset type."""
        return {
            AssetType.BACKGROUND: 'backgrounds',
            AssetType.FONT: 'fonts',
            AssetType.OBJECT: 'objects',
            AssetType.PATH: 'paths',
            AssetType.ROOM: 'rooms',
            AssetType.SCRIPT: 'scripts',
            AssetType.SPRITE: 'sprites',
            AssetType.SOUND: 'sounds',
            AssetType.DATA_SFX: 'data/sounds',
            AssetType.DATA_MUSIC: 'data/music',
        }[self]

    def get_scannables(
        self, asset_name: str, project_root: Path
    ) -> col.Iterator[Path]:
        """Get scannable files for given asset."""
        asset_dir = project_root / self.get_dir()
        match self:
            case AssetType.SCRIPT:
                file_gml = asset_dir / f'{asset_name}.gml'
                yield file_gml  # guaranteed to exist

            case AssetType.OBJECT:
                file_meta = asset_dir / f'{asset_name}.txt'
                file_gml = asset_dir / f'{asset_name}.gml'
                yield file_meta
                yield file_gml  # both guaranteed to exist

            case AssetType.ROOM:
                dir_room = asset_dir / asset_name
                yield from dir_room.glob('*.txt')
                yield from dir_room.glob('*.gml')

    def iter_tree(self, project_root: Path) -> col.Iterator[TreeEntry]:
        """Iterate asset tree of given asset type.

        :param project_root: Project's root directory.
        :return: Iterator of (asset_name, tree_path). The ``tree_path``
          contains path in asset's respective "tree" structure: ``tree.yyd``
          for builtin assets and filesystem tree of ``data/`` for external
          assets. The asset name is not appended to ``tree_path``.
        """
        asset_dir = project_root / self.get_dir()
        if self.is_builtin():
            tree_text = (asset_dir / 'tree.yyd').read_text(encoding='utf-8')
            return my_parse_tree.parse(tree_text.splitlines())
        return (
            (f'"{file.stem}"', file.relative_to(asset_dir).parts[:-1])
            for file in asset_dir.rglob('*')
            if file.is_file()
        )


# --- COG_END: CLS_ASSET_TYPE ---


# --- COG_START: CLUSTERABLE_ASSETS ---
CLUSTERABLE_ASSETS: tuple[AssetType, ...] = (
    AssetType.SPRITE,
    AssetType.BACKGROUND,
    AssetType.SOUND,
    AssetType.PATH,
    AssetType.SCRIPT,
    AssetType.FONT,
    AssetType.OBJECT,
    AssetType.ROOM,
    AssetType.DATA_SFX,
    AssetType.DATA_MUSIC,
)
# --- COG_END: CLUSTERABLE_ASSETS ---

# those are used in starting examples
# --- COG_START: CLUSTERABLE_BUILTINS ---
CLUSTERABLE_BUILTINS: tuple[AssetType, ...] = (
    AssetType.SPRITE,
    AssetType.BACKGROUND,
    AssetType.SOUND,
    AssetType.PATH,
    AssetType.SCRIPT,
    AssetType.FONT,
    AssetType.OBJECT,
    AssetType.ROOM,
)
# --- COG_END: CLUSTERABLE_BUILTINS ---

# --- COG_START: CLUSTERABLE_EXTERNALS ---
CLUSTERABLE_EXTERNALS: tuple[AssetType, ...] = (
    AssetType.DATA_SFX,
    AssetType.DATA_MUSIC,
)
# --- COG_END: CLUSTERABLE_EXTERNALS ---

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

# --- COG_START: PROJECT ---
PROJECT = Path('path/to/the/project')
# --- COG_END: PROJECT ---


# --- COG_START: CLS_ASSET ---
@dataclass(frozen=True, slots=True)
class Asset:
    """Simple asset definition."""

    asset_type: AssetType
    name: str
    tree_path: tuple[str, ...]
    cluster: str
    files_to_scan: tuple[Path, ...]


# --- COG_END: CLS_ASSET ---


# --- COG_START: CLS_SCAN_JOB ---
@dataclass(frozen=True, slots=True)
class ScanJob:
    """A lightweight payload sent over IPC to a worker process.

    Uses frozen and slots to speed up transfer across processes.
    """

    asset_name: str
    file_path: Path


@dataclass(frozen=True, slots=True)
class ScanResult:
    """Result of a scan."""

    matches: list[my_analyze_scan_dep.DependencyMatch]
    job: ScanJob


# --- COG_END: CLS_SCAN_JOB ---


# --- COG_START: CLS_DEPENDENCY ---
@dataclass(frozen=True, slots=True)
class Dependency:
    """Full dependency data to be used in graph building."""

    location: my_analyze_location.BoundLocation
    source_asset: Asset
    target_asset: Asset
    contexts: tuple[str, ...]


# --- COG_END: CLS_DEPENDENCY ---


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
    """First, we want to check that builtin assets get scanned correctly.

    For this we define classes ``AssetType``, which houses logic
    for navigating GameMaker's project structure, as well as ``Asset``,
    which stores necessary information of the assets.

    Logic in ``AssetType`` includes external assets, and expects them to
    be present in specific directories. You might want to modify them, if
    yours are different.
    """
    # --- COG_START: MAIN_EX_START ---

    assets: list[Asset] = []

    for asset_type in CLUSTERABLE_BUILTINS:
        # check if given asset type exist in the project
        if not asset_type.exists(PROJECT):
            continue

        # iterate through tree.yyd file or direct fs structure
        for asset_name, asset_path in asset_type.iter_tree(PROJECT):
            # we don't have clusters yet so we'll just set it to "Unknown"
            scannables = asset_type.get_scannables(asset_name, PROJECT)
            assets.append(
                Asset(
                    asset_type=asset_type,
                    name=asset_name,
                    tree_path=asset_path,
                    cluster='Unknown',
                    files_to_scan=tuple(scannables),
                )
            )

    # you should investigate the resulting array for inconsistencies
    print(f'Discovered {len(assets)} total assets.')
    # --- COG_END: MAIN_EX_START ---


def main_ex_clusters() -> None:
    """Autogenerate clusters for the assets.

    Now that assets discovering works, we may generate clusters. By default,
    those are assigned based on the first directory in trees.
    """
    # --- COG_START: MAIN_EX_CLUSTERS ---
    assets: list[Asset] = []

    # cluster -> its assets
    cluster_map: dict[str, list[str]] = {}
    # asset type -> found clusters (useful for initial cleanup)
    asset_to_cluster: dict[AssetType, list[str]] = {}
    for asset_type in CLUSTERABLE_ASSETS:
        # we merge logic for both builtins and externals into one loop
        asset_dir = PROJECT / asset_type.get_dir()
        if not asset_dir.exists():
            continue

        # fill in set of clusters associated with this asset type
        cluster_set: set[str] = set()
        # create asset iterator (asset_name, folder path)
        if asset_type.is_builtin():
            tree_text = (asset_dir / 'tree.yyd').read_text(encoding='utf-8')
            asset_iter = my_parse_tree.parse(tree_text.splitlines())
        else:
            asset_iter = (
                (f'"{file.stem}"', file.relative_to(asset_dir).parts[:-1])
                for file in asset_dir.rglob('*')
                if file.is_file()
            )

        # iterate them assets
        for asset_name, path in asset_iter:
            # use base folder as cluster name
            cluster_name = path[0] if path else 'Common'
            cluster_set.add(cluster_name)
            cluster_map.setdefault(cluster_name, []).append(asset_name)

            assets.append(
                Asset(
                    asset_type=asset_type,
                    name=asset_name,
                    tree_path=path,
                    cluster=cluster_name,
                    files_to_scan=tuple(
                        asset_type.get_scannables(asset_name, PROJECT)
                    ),
                )
            )
        asset_to_cluster[asset_type] = list(cluster_set)

    # print the asset type to cluster table
    # (helps to find duplicates)
    clusters_all = sorted(
        {name for clusters in asset_to_cluster.values() for name in clusters}
    )
    print('All clusters:', *clusters_all)
    for asset_type, clusters in asset_to_cluster.items():
        cluster_set = set(clusters)
        row = [
            col if col in cluster_set else ' ' * len(col)
            for col in clusters_all
        ]
        print(f'{asset_type.get_dir(): >12}:', '|'.join(row))

    # MD: There's a chance of duplicates in result. Also, some of those
    # MD: "clusters" (like Backgrounds, or World, etc.) should be a part of
    # MD: Common cluster.
    # --- COG_END: MAIN_EX_CLUSTERS ---


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
        asset_dir = PROJECT / asset_type.get_dir()
        if not asset_dir.exists():
            continue

        if asset_type.is_builtin():
            tree_text = (asset_dir / 'tree.yyd').read_text(encoding='utf-8')
            asset_iter = my_parse_tree.parse(tree_text.splitlines())
        else:
            asset_iter = (
                (f'"{file.stem}"', file.relative_to(asset_dir).parts[:-1])
                for file in asset_dir.rglob('*')
                if file.is_file()
            )

        for asset_name, path in asset_iter:
            # --- COG_START: MAIN_EX_ALIAS_GIST_ALIAS ---
            # MD: Then we apply aliasing in the asset iteration loop.
            cluster_name = path[0] if path else 'Common'
            # replace clusters with aliases
            if cluster_name in cluster_to_name:
                cluster_name = cluster_to_name[cluster_name]
            # MD: Keep using the table thing until all aliases are gone.
            # --- COG_END: MAIN_EX_ALIAS_GIST_ALIAS ---

            assets.append(
                Asset(
                    asset_type=asset_type,
                    name=asset_name,
                    tree_path=path,
                    cluster=cluster_name,
                    files_to_scan=tuple(
                        asset_type.get_scannables(asset_name, PROJECT)
                    ),
                )
            )
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
    asset_to_cluster: dict[AssetType, list[str]] = {}
    used_aliases: set[str] = set()
    asset_name_set: set[str] = set()  # clean asset name issues
    for asset_type in CLUSTERABLE_ASSETS:
        asset_dir = PROJECT / asset_type.get_dir()
        if not asset_dir.exists():
            continue

        cluster_set: set[str] = set()
        if asset_type.is_builtin():
            tree_text = (asset_dir / 'tree.yyd').read_text(encoding='utf-8')
            asset_iter = my_parse_tree.parse(tree_text.splitlines())
        else:
            asset_iter = (
                (f'"{file.stem}"', file.relative_to(asset_dir).parts[:-1])
                for file in asset_dir.rglob('*')
                if file.is_file()
            )

        for asset_name, path in asset_iter:
            cluster_name = path[0] if path else 'Common'
            used_aliases.add(cluster_name)
            if cluster_name in cluster_to_name:
                cluster_name = cluster_to_name[cluster_name]
            used_aliases.add(cluster_name)

            cluster_set.add(cluster_name)
            cluster_map.setdefault(cluster_name, []).append(asset_name)

            if asset_name in asset_name_set:
                raise ValueError(f'Duplicate asset name {asset_name}')
            asset_name_set.add(asset_name)

            assets.append(
                Asset(
                    asset_type=asset_type,
                    name=asset_name,
                    tree_path=path,
                    cluster=cluster_name,
                    files_to_scan=tuple(
                        asset_type.get_scannables(asset_name, PROJECT)
                    ),
                )
            )
        asset_to_cluster[asset_type] = list(cluster_set)

    clusters_all = sorted(
        {name for clusters in asset_to_cluster.values() for name in clusters}
    )
    print('All clusters:', *clusters_all)
    for asset_type, clusters in asset_to_cluster.items():
        cluster_set = set(clusters)
        row = [
            col if col in cluster_set else ' ' * len(col)
            for col in clusters_all
        ]
        print(f'{asset_type.get_dir(): >12}:', '|'.join(row))

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
    # --- COG_END: MAIN_EX_ALIASES ---
    return assets


def main_ex_scan_sync(assets: list[Asset]) -> None:
    """Simple scanner.

    Before running dependency builder we need to set up scanning
    for the actual dependencies.

    We compile Aho-Corasick automaton to quickly scan every text
    (script or metadata file) in the project for asset references.

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
        for file_path in asset.files_to_scan:
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
        for file_path in asset.files_to_scan
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
        for file_path in asset.files_to_scan
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
        return

    print(
        f'\nFound {total_orphans} orphaned assets across '
        f'{len(orphans_by_cluster)} clusters:'
    )

    for cluster, orphans in sorted(orphans_by_cluster.items()):
        print(f'\n=== {cluster} ===')

        # sort
        orphans.sort(key=lambda a: (a.asset_type.name, a.tree_path, a.name))

        for asset in orphans:
            print(
                f'[{asset.asset_type.name: <10}] {"/".join(asset.tree_path)}'
                f'/{asset.name}'
            )
    # --- COG_END: MAIN_EX_LINT_UNUSED ---


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
    violations: dict[
        str,
        dict[str, list[str]],
    ] = {}
    total_violations = 0

    for dep in dependencies:
        target = dep.target_asset
        source = dep.source_asset

        # remove deps to room
        if target.asset_type == AssetType.ROOM:
            continue

        # get permissions from lint rules
        allowed_targets = set(
            LINT_RULES.get(source.cluster, {source.cluster, 'Common'})
        )

        # expand permissions based on script guards
        for ctx in dep.contexts:
            if ctx in CONTEXT_RULES:
                allowed_targets.update(CONTEXT_RULES[ctx])

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
        return

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
    # --- COG_END: MAIN_EX_LINT_CROSSREF ---


def _run_tutorials() -> None:
    main_ex_start()
    main_ex_clusters()
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

    # TODO dummy config and dummy aliases

    _run_tutorials()


def _load_private(config_dir: Path) -> None:
    global PROJECT, ALIAS, LINT_RULES, CONTEXT_RULES

    _file_private_config = config_dir / 'config.json'
    if not _file_private_config.exists():
        raise FileNotFoundError(
            f'Config file not found: {_file_private_config}'
        )

    _private_config = json.loads(
        _file_private_config.read_text(encoding='utf-8')
    )
    PROJECT = Path(_private_config['project'])

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
        main_ex_aliases()
        # return
        assets = stage_discover_assets()

        deps = main_ex_scan_sync2(assets)

        main_ex_lint_unused(deps, assets)
        # main_ex_lint(deps)


if __name__ == '__main__':
    main()
