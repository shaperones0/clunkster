# Clunkster

<!--[[[cog
import sys
sys.path.append("scripts")

from scripts.readme_example import ExampleHeader, main_manager, gen_stub_cls, gen_stub_var

exs, rend = main_manager()
]]]-->
<!--[[[end]]]-->

GameMaker 8.2 optimization tools.

Most of the tools depend heavily on asset clustering (i.e., assigning each asset to an isolated group like "StageA", "StageB", "Common", etc.), but some use it only to group console output.

Given the architectural differences across GameMaker projects, Clunkster is organized as a set of "[examples](#examples)" that you can copy and modify. The library itself provides the functions that facilitate the core logic and handle engine-specific edge cases.

Please refer to [Rationale](#rationale) and [Prerequisites](#prerequisites) to see if these tools fit your project's needs.

<!--[[[cog
# dum pogapp cant do inline inserts
cog.outl(f"""
Non-destructive tools:
- Linter: `tree.yyd` validator
- Linter: unused assets detector (see {rend.href('ex_lint_unused')})
- Linter: heavy assets detector (RAM & disk size)
- Linter: cross-cluster reference boundary validator (see {rend.href('ex_lint_crossref')})
- (TODO) Linter: room indirect reference validator via dependency graph

Lightly destructive tools:
- (TODO) Backgrounds minifier: strip tilesets of all unused space
- (TODO) Audio optimizer: optimize audio files via [FFmpeg](https://www.ffmpeg.org/)

Super destructive tools:
- (TODO) Project crippler (Dev Build): replace assets with lightweight stubs for faster development
- (TODO) Project juicer (Prod Build): convert assets into external versions and generate code for their loading (See: [Dehydration](#dehydration))

""")
]]]-->

Non-destructive tools:
- Linter: `tree.yyd` validator
- Linter: unused assets detector (see [ex2.4](#example-24---lint-unused-assets))
- Linter: heavy assets detector (RAM & disk size)
- Linter: cross-cluster reference boundary validator (see [ex2.5](#example-25---lint-cross-cluster-references))
- (TODO) Linter: room indirect reference validator via dependency graph

Lightly destructive tools:
- (TODO) Backgrounds minifier: strip tilesets of all unused space
- (TODO) Audio optimizer: optimize audio files via [FFmpeg](https://www.ffmpeg.org/)

Super destructive tools:
- (TODO) Project crippler (Dev Build): replace assets with lightweight stubs for faster development
- (TODO) Project juicer (Prod Build): convert assets into external versions and generate code for their loading (See: [Dehydration](#dehydration))


<!--[[[end]]]-->


# TOC

<!--[[[cog
from readme_toc import generate_toc
cog.outl('\n'.join(generate_toc()))
]]]-->
* [Examples](#examples)
  * [1 - Reading project](#1---reading-project)
    * [Example 1.1 - Finding assets](#example-11---finding-assets)
    * [Example 1.2 - Generating clusters](#example-12---generating-clusters)
    * [Example 1.3 - Cluster aliasing](#example-13---cluster-aliasing)
  * [2 - References](#2---references)
    * [Example 2.1 - Reference scanning](#example-21---reference-scanning)
    * [Example 2.2 - Reference scanning (fancier)](#example-22---reference-scanning-fancier)
    * [Example 2.3 - Reference scanning (multiprocessing)](#example-23---reference-scanning-multiprocessing)
    * [Example 2.4 - Lint: unused assets](#example-24---lint-unused-assets)
    * [Example 2.5 - Lint: cross-cluster references](#example-25---lint-cross-cluster-references)
* [Rationale](#rationale)
  * [Linters](#linters)
  * [Prerequisites](#prerequisites)
  * [Workflow](#workflow)
    * [Preparation](#preparation)
* [Dehydration](#dehydration)
<!--[[[end]]]-->

# Examples

The following examples represent actual workflows. Copy and modify as needed.

<!--[[[cog
cog.outl(rend.render())
]]]-->
## 1 - Reading project
### Example 1.1 - Finding assets
First, we want to check that builtin assets get scanned correctly.

For this we define classes `AssetType`, which houses logic
for navigating GameMaker's project structure, as well as `Asset`,
which stores necessary information of the assets.

Logic in `AssetType` includes external assets, and expects them to
be present in specific directories. You might want to modify them, if
yours are different.

```python
import collections.abc as col
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path

from clunkster.parse import tree as my_parse_tree

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

@dataclass(frozen=True, slots=True)
class Asset:
    """Simple asset definition."""

    asset_type: AssetType
    name: str
    tree_path: tuple[str, ...]
    cluster: str
    files_to_scan: tuple[Path, ...]

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

PROJECT = Path('path/to/the/project')

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
```
### Example 1.2 - Generating clusters
Autogenerate clusters for the assets.

Now that assets discovering works, we may generate clusters. By default,
those are assigned based on the first directory in trees.

```python
import collections.abc as col
from pathlib import Path

from clunkster.parse import tree as my_parse_tree

# see Example 1.1 - Finding assets
class AssetType: ...

# see Example 1.1 - Finding assets
class Asset: ...

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

PROJECT = Path('path/to/the/project')

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
```

There's a chance of duplicates in result. Also, some of those
"clusters" (like Backgrounds, or World, etc.) should be a part of
Common cluster.
### Example 1.3 - Cluster aliasing
Manually fix inconsistencies in cluster map.

After we did initial scan, you may encounter inconsistencies like different
clusters `"StageA"` and `"stage_a"` (project didn't follow strict
naming), as well as a bunch of things that should belong to Common cluster
(Backgrounds, Game, etc.).

Which is easily fixed by a simple alias system for clusters.

```python
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

# invert ALIAS
cluster_to_name: dict[str, str] = {}
for name, clusters in ALIAS.items():
    for cluster in clusters:
        if cluster in cluster_to_name:
            raise ValueError('Invalid ALIAS (duplicate aliases)')
        cluster_to_name[cluster] = name
```

Then we apply aliasing in the asset iteration loop.

```python
cluster_name = path[0] if path else 'Common'
# replace clusters with aliases
if cluster_name in cluster_to_name:
    cluster_name = cluster_to_name[cluster_name]
```

Keep using the table thing until all aliases are gone.

Full example:

```python
import collections.abc as col
import warnings
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path

from clunkster.parse import tree as my_parse_tree

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

@dataclass(frozen=True, slots=True)
class Asset:
    """Simple asset definition."""

    asset_type: AssetType
    name: str
    tree_path: tuple[str, ...]
    cluster: str
    files_to_scan: tuple[Path, ...]

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

PROJECT = Path('path/to/the/project')

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
```
## 2 - References
### Example 2.1 - Reference scanning
Simple scanner.

Before running dependency builder we need to set up scanning
for the actual dependencies.

We compile Aho-Corasick automaton to quickly scan every text
(script or metadata file) in the project for asset references.

This is a simple synchronous code, but in real projects scanning
might take up 5-10 seconds.

Multiprocessing version is available in later examples.

```python
from ahocorasick import Automaton

from clunkster.analyze import scan_dep as my_analyze_scan_dep

# see Example 1.1 - Finding assets
class AssetType: ...

# see Example 1.1 - Finding assets
class Asset: ...

# see Example 1.3 - Cluster aliasing
assets: list[Asset] = ...

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
```
### Example 2.2 - Reference scanning (fancier)
Simple scanner with some extra stuff.

We can add a progress bar + robust struct for storing our dependencies.

```python
from dataclasses import dataclass

import tqdm
from ahocorasick import Automaton

from clunkster.analyze import location as my_analyze_location
from clunkster.analyze import scan_dep as my_analyze_scan_dep

# see Example 1.1 - Finding assets
class AssetType: ...

# see Example 1.1 - Finding assets
class Asset: ...

@dataclass(frozen=True, slots=True)
class Dependency:
    """Full dependency data to be used in graph building."""

    location: my_analyze_location.BoundLocation
    source_asset: Asset
    target_asset: Asset
    contexts: tuple[str, ...]

# see Example 1.3 - Cluster aliasing
assets: list[Asset] = ...

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
```
### Example 2.3 - Reference scanning (multiprocessing)
Multiprocessing scanner.

Multiprocessing can speed up scanning (but in practice it didn't - we
left this sample moreso as a reference). To do this, we can divide
the scanning tasks across a pool of worker processes.

For this we must set up few additional methods - worker's "init" and
worker "work".

```python
import multiprocessing as mp
from concurrent import futures
from dataclasses import dataclass
from pathlib import Path

import tqdm
from ahocorasick import Automaton

from clunkster.analyze import location as my_analyze_location
from clunkster.analyze import scan_dep as my_analyze_scan_dep

# see Example 1.1 - Finding assets
class AssetType: ...

# see Example 1.1 - Finding assets
class Asset: ...

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

@dataclass(frozen=True, slots=True)
class Dependency:
    """Full dependency data to be used in graph building."""

    location: my_analyze_location.BoundLocation
    source_asset: Asset
    target_asset: Asset
    contexts: tuple[str, ...]

# we can't send the compiled Aho-Corasick automaton across process boundaries
#  safely; instead, we use a global variable inside the worker process and
#  initialize it once when the process boots up

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

# see Example 1.3 - Cluster aliasing
assets: list[Asset] = ...

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
```
### Example 2.4 - Lint: unused assets
Find and report assets that are never referenced by anything.

Removing unused assets is a quick way to clean up a project.
We can do this with a simple set difference: Total Assets
minus Used Assets.

This will not catch isolated reference loops (e.g., A references B,
B references A, but neither is used by the main game).

Also, some things that are indirectly referenced by the engine (like
with rooms and `room_goto_next()`) might still get reported.

Take the output of this with a grain of salt.

```python
# see Example 1.1 - Finding assets
class AssetType: ...

# see Example 1.1 - Finding assets
class Asset: ...

# see Example 2.2 - Reference scanning (fancier)
class Dependency: ...

# see Example 1.3 - Cluster aliasing
assets: list[Asset] = ...

# see Example 2.2 - Reference scanning (fancier)
dependencies: list[Dependency] = ...

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
```
### Example 2.5 - Lint: cross-cluster references
Validate cluster boundaries.

Simple check of clusters on both ends of dependency edge will filter
out the majority of "stageA object referenced stageB asset" cases.

However, this iteration (and following linters) have a few special rules:

1. Most clusters are allowed to reference only themselves and Common
cluster, but some may need to reference certain more localized "common"
cluster. Such as when one collab maker creates multiple stages, and has
many common scripts and util objects shared between them, but, technically,
not between the rest of the collab. Such rules should be defined in
`LINT_RULES`.

2. We allow special context guard scripts in a form of:

```
if room_is_stageA() {
    ...
}
```
Those guards allow references to any foreign cluster inside them. Such
guards must be defined in `CONTEXT_RULES`.

3. References to rooms are severed. Since the only way to meaningfully
"reference" a room is to go there, for all intents and purposes reference
whatever references a room doesn't really depend on it.

Make sure to fill in the `LINT_RULES` and `CONTEXT_RULES` - they'll
be used by future linters.

```python
LINT_RULES: dict[str, set[str]] = {
    # common assets cannot borrow from Stage specific folders
    'Common': {'Common'},
    # example of a stage that shares assets with another
    # "StageB": {"StageB", "StageA", "Common"},
}

CONTEXT_RULES: dict[str, set[str]] = {
    'room_is_stageA': {'StageA'},
    'room_is_stageB': {'StageB'},
    'room_is_final': {'StageX', 'StageY', 'StageZ'},
    # ...
}

# see Example 1.1 - Finding assets
class AssetType: ...

# see Example 1.1 - Finding assets
class Asset: ...

# see Example 2.2 - Reference scanning (fancier)
class Dependency: ...

# see Example 2.2 - Reference scanning (fancier)
dependencies: list[Dependency] = ...

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
```
<!--[[[end]]]-->

# Rationale

GameMaker 8.2 runner is 32-bit, meaning there's a hard cap on RAM of around 4 GB. Furthermore, certain parts of the engine start having issues at even 2.5 GB of RAM consumption.

Also, such large projects take 10-15 seconds to build.

To solve this, you can split the large project into logical clusters. You have "Common" assets (`Player`, `Block`, ...), and stage-specific assets (`bStageATiles`, `StageAPostProc`, ...). So, when game is in a room from stage A, it technically doesn't require assets from Stage B.

To lighten the load, unneeded assets can be replaced with lightweight stubs right in the project.

For dev builds, the tool can nuke all assets except for ones from specified clusters. Optionally, the stubs can be made more noticeable:
- sprites and backgrounds become pink-black checkerboards
- sounds get replaced with buzz.wav and/or [fiddlesticks.mp3](https://developer.valvesoftware.com/wiki/Missing_content)

Prod builds are similar, but we add dynamic loading. The project is copied, only Common cluster is kept in the base executable. The stage-specific assets are packaged into external files ("wet" versions). When the player enters a new stage, the game dynamically loads ("hydrates") the required assets from the disk. Optionally the stubs can be made less noticeable (though you probably should still make them loud):
- sprites and backgrounds become 2x2 transparent
- sounds get replaced with null.wav

## Linters

To prevent developers from accidentally referencing a `StageB` sprite inside a `StageA` object, a dependency linter is included. It builds dependency graph based on static `.gml` and `.txt` metafile analysis.

From those dependencies, the tool can:
- find orphaned assets that are not referenced by anything
- find assets that reference other assets in disallowed clusters
- construct sets of assets referenced (both directly and indirectly) in each room, and yell at you if a room references something that it hasn't explicitly been marked to load.

## Prerequisites

1. Use this tool only if it's necessary.
    - Setting this up requires a fair bit of technical knowledge (about both GameMaker 8.2 and Python) and can be a headache. I would only recommend using this tool if your game eats more than 1.5 GB of RAM and your project takes more than 10 seconds to build.
2. Use Git - changes made by this tool are destructive and **will nuke your project** (that's literally what Clunkster is designed to do).
3. Follow good project keeping practices
   - Keep asset names clean (press broom icon on IDE's top toolbar to run required checks)
   - Keep assets belonging to certain stage in that stage's folder
   - Do not reference things from `stageA` in `stageB` objects (unless such an object is only placed in a room that guarantees both stages loaded)
   - Reference Common objects in Stage-specific, not the other way around
     - If this is unavoidable (for example, when making a stage-specific movement gimmick), use "_guard scripts_" (`if room_is_stageA() { ... }`)
   - If an asset is shared between multiple stages, then it belongs in Common cluster
4. Follow good coding practices
    - no dynamic asset referencing (tool won't acknowledge those references when building dependency graph):
      - DON'T do math on asset IDs: `draw_sprite(sprSpikeUp+2, x, y)`
      - DON'T use string execution: `execute_string("instance_create(0, 0, obj_enemy_" + string(current_level) + ")")`
      - DON'T pass assets via global variables across cluster boundaries: `global.current_boss = obj_StageB_Boss` (If Stage A reads this global, the analyzer cannot trace the dependency)

Other than that, use the modern project format (`.gm82`) and Python 3.14+ ([`uv`](https://docs.astral.sh/uv/) recommended).

## Workflow

This is the workflow that I used for the project that this tool was initially made for. As of now, each step of the workflow is represented as an example in [Examples](#examples) section. Examples without links are WIP.

### Preparation

Firstly, you should build the initial dependency scanning pipeline.

This starts with parsing `tree.yyd` files in order to discover assets and run initial checks to determine, what needs to be fixed before generating clusters.  generate initial cluster map. Therefore, in this step your goal is to:
- ensure that stage assets are grouped in consistently named folders across all asset types

See examples: 
- [1](#example-1---finding-assets) setting up asset discovery
- [2](#example-2---external-assets-data) adding external assets (`data/`)

After that we may generate initial cluster map. In this step our goal is:
- assign clusters based on `tree.yyd` data
- make aliases for folders that don't represent actual clusters (such as "Tiles" backgrounds or "Killers" objects)

See examples:

- [3](#example-3---generating-clusters) generating initial cluster map
- [4](#example-4---cluster-aliasing) fixing duplicate clusters via aliases

Next, you want to set up dependency scanning. For this, we use [`ahocorasick`](https://pypi.org/project/pyahocorasick/). In my testing, sync version takes around the same amount of time as multiprocessing, so no real difference here.

See examples:
- [5](#example-5---reference-scanning) simple references generator 
- [6](#example-6---reference-scanning-fancy) reference generator with better struct and progressbar :3
- [7](#example-7---reference-scanning-multiprocessing) multiprocessing reference generator

Once that's done you may start with some initial cleaning. Basic linter can find most violations just by checking each dependency on presence of cross-cluster references.

See example:
- [8](#example-8---simple-linter-unused-assets) finding unused assets (simple ver)
- [8](#example-9---simple-linter-cross-cluster-references) finding cross-cluster references

# Dehydration

Following terms are used:
- prepare: the process of stripping the asset from the project.
- store-dry-prod: how the stripped asset is represented inside resulting prod build (invisible stubs).
- store-dry-dev: how the stripped asset is represented inside resulting dev build (stubs that yell loudly when referenced).
- store-wet: how the actual data is stored externally.
- hydrate: the process of dynamically loading wet assets back into memory at runtime.
- dehydrate: the process of unloading the assets from memory at runtime.

___

**Backgrounds**: impactful, high priority.
- prepare: use [`gmcodec`](https://github.com/shaperones0/gmcodec) to generate `.gmbck` files.
- store-dry-prod: transparent 2x2.
- store-dry-dev: pink-black checkerboard with transparent padding
- store-wet: `.gmbck` files.
- hydrate: use `background_replace_background` to load externally.
- dehydrate: use `background_replace_background` to replace back with dry stub.
____
**Fonts**: not numerous enough to be impactful, difficult.
____
**Objects**: slightly impactful, risky (and difficult).
____
**Paths**: not impactful.
____
**Room**: impactful, risky.
- prepare: 
  - read instances.txt, tiles and each object creation code, 
  - turn them into scripts that add them back in via `room_instance_add` (don't forget their respective globalvars) 
  - and `room_tile_add`, 
  - generate objects for each room instance creation code to be run on room start.
- store-dry-prod: blank room that tries to load its assets? TODO idk.
- store-dry-dev: blank room with a single stub object (to raise errors).
- store-wet: aforementioned script and object.
- hydrate: run the scripts, add the room start object as well.
- dehydrate: `room_instance_clear`, `room_tile_clear`.
____
**Scripts**: impossible to create dynamically.
____
**Sprites**: impactful, high priority.
- prepare: use [`gmcodec`](https://github.com/shaperones0/gmcodec) to generate `.gmspr` files
- store-dry-prod: transparent 2x2 with same number of frames as original.
- store-dry-dev: pink-black checkerboard with transparent padding.
- store-wet: `.gmspr` files.
- hydrate: use `sprite_replace_sprite` to load externally.
- dehydrate: use `sprite_replace_sprite` to replace back with dry stub.
____
**Sounds**: very impactful, TODO.
____
**Data**: Sounds and Music: impactful, high priority.
- prepare:
  - put sounds from same cluster into their folders, 
  - generate a script that loads every sound as `null.wav` (or `buzz.wav`) via `sound_add_ext` on game start,
  - generate a script that would load said WASD pack.
- store-dry-dev: `buzz.wav` for sounds and `fiddlesticks.mp3` for music.
- store-dry-prod: `null.wav` files.
- store-wet: just files sitting in their folders.
- hydrate: run the loader script.
- dehydrate: replace back with stubs.
