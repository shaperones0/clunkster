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
- Linter: unused assets detector (see {rend.href('ex_lint_unused')} and {rend.href('ex_lint_unused_graph')})
- (TODO) Linter: heavy assets detector (RAM & disk size)
- Linter: cross-cluster reference boundary validator (see {rend.href('ex_lint_crossref')})
- Linter: room indirect reference validator via dependency graph (see {rend.href('ex_lint_crossref_graph')})

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
- Linter: unused assets detector (see [ex2.4](#example-24---lint-unused-assets) and [ex3.2](#example-32---lint-unreachable-assets))
- (TODO) Linter: heavy assets detector (RAM & disk size)
- Linter: cross-cluster reference boundary validator (see [ex2.5](#example-25---lint-cross-cluster-references))
- Linter: room indirect reference validator via dependency graph (see [ex3.3](#example-33---lint-room-cluster-boundaries))

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
    * [Example 1.2 - Lint: `tree.yyd` files](#example-12---lint-treeyyd-files)
    * [Example 1.3 - Generating clusters](#example-13---generating-clusters)
    * [Example 1.4 - Cluster aliasing](#example-14---cluster-aliasing)
  * [2 - References](#2---references)
    * [Example 2.1 - Reference scanning](#example-21---reference-scanning)
    * [Example 2.2 - Reference scanning (fancier)](#example-22---reference-scanning-fancier)
    * [Example 2.3 - Reference scanning (multiprocessing)](#example-23---reference-scanning-multiprocessing)
    * [Example 2.4 - Lint: unused assets](#example-24---lint-unused-assets)
    * [Example 2.5 - Lint: cross-cluster references](#example-25---lint-cross-cluster-references)
  * [3 - Dependency graph](#3---dependency-graph)
    * [Example 3.1 - Generate set of used assets in each room](#example-31---generate-set-of-used-assets-in-each-room)
    * [Example 3.2 - Lint: unreachable assets](#example-32---lint-unreachable-assets)
    * [Example 3.3 - Lint: room cluster boundaries](#example-33---lint-room-cluster-boundaries)
* [Rationale](#rationale)
  * [Linters](#linters)
  * [Prerequisites](#prerequisites)
    * [[HowTo] Prerequisites - Project & Asset organization](#howto-prerequisites---project-asset-organization)
    * [[HowTo] Prerequisites - Eradicating dynamic asset referencing](#howto-prerequisites---eradicating-dynamic-asset-referencing)
    * [[HowTo] Prerequisites - Building dependency flow](#howto-prerequisites---building-dependency-flow)
    * [[HowTo] Prerequisites - Timelines...](#howto-prerequisites---timelines)
    * [[HowTo] Prerequisites - State contamination via Globals and Persistence](#howto-prerequisites---state-contamination-via-globals-and-persistence)
    * [[HowTo] Prerequisites - Proper use of the Ignore Pragma](#howto-prerequisites---proper-use-of-the-ignore-pragma)
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

    def file_tree(self, project_root: Path) -> Path:
        """Get tree.yyd for this asset type."""
        return project_root / self.get_dir() / 'tree.yyd'

    def file_index(self, project_root: Path) -> Path:
        """Get index.yyd for this asset type."""
        return project_root / self.get_dir() / 'index.yyd'

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

for asset_type in CLUSTERABLE_ASSETS:
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
### Example 1.2 - Lint: `tree.yyd` files
Check integrity of `tree.yyd` files.

Asset discovery and clusterization is based on scanning `tree.yyd`
files, so we have to ensure that they have no duplicate folders.

Technically, before doing that you should also check that there are also
no duplicate asset names via broom icon on IDE toolbar.

```python
import collections
import collections.abc as col
from pathlib import Path

from clunkster.parse import index as my_parse_index
from clunkster.parse import tree as my_parse_tree

# see Example 1.1 - Finding assets
class AssetType: ...

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
    if not asset_type.exists(PROJECT):
        continue
    # tree.yyd exists only for builtin assets
    if not asset_type.is_builtin():
        continue

    # get assets from index, validate uniqueness
    assets_from_index = list(
        my_parse_index.parse_skimmed(
            asset_type.file_index(PROJECT).read_text().splitlines()
        )
    )
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

    # feed into the linter
    tree_file = PROJECT / asset_type.get_dir() / 'tree.yyd'
    print(f'Checking {tree_file} ...')
    lint_tree(tree_file.read_text(encoding='utf-8').splitlines())
```

If you got no duplicates messages in the output then you're all good.
### Example 1.3 - Generating clusters
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
### Example 1.4 - Cluster aliasing
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

    def file_tree(self, project_root: Path) -> Path:
        """Get tree.yyd for this asset type."""
        return project_root / self.get_dir() / 'tree.yyd'

    def file_index(self, project_root: Path) -> Path:
        """Get index.yyd for this asset type."""
        return project_root / self.get_dir() / 'index.yyd'

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

Found asset references precisely reflect occurences in static code.
In later steps we will artificially add some unreflected dependencies
(such as persistent object existing potentially in every room). But
such manipulations should not be done on resulting dependency list,
but rather later, by injecting edges inside graph build process.

Also, for pure data registry scripts (like `sound_balance`), which,
technically reference every asset, but don't instantiate them,
we added a special directive: `//!clunkster: ignore`. Add it any
GML scripts that should be skipped.

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

# see Example 1.4 - Cluster aliasing
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

# see Example 1.4 - Cluster aliasing
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

# see Example 1.4 - Cluster aliasing
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

# see Example 1.4 - Cluster aliasing
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
else:
    print(
        f'\nFound {total_orphans} orphaned assets across '
        f'{len(orphans_by_cluster)} clusters:'
    )

    for cluster, orphans in sorted(orphans_by_cluster.items()):
        print(f'\n=== {cluster} ===')

        # sort
        orphans.sort(
            key=lambda a: (a.asset_type.name, a.tree_path, a.name)
        )

        for asset in orphans:
            print(
                f'[{asset.asset_type.name: <10}] '
                f'{"/".join(asset.tree_path)}'
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
```
## 3 - Dependency graph
### Example 3.1 - Generate set of used assets in each room
Build dependency graph.

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
ubiquitous assets as `EXTRA_ROOTS`, so they get artificially added into
the reachability sets.

You might also notice that, along with reachability sets, we are saving
graphs and data to translate graph output. This is only used for
better output in some of the latter tools, so if such data ever becomes
a bottleneck (which I HIGHLY doubt) you may omit those and only calculate
`reachability_map:dict[str,set[str]]`

```python
import sys
from dataclasses import dataclass

import rustworkx as rx
import tqdm

# see Example 2.5 - Lint: cross-cluster references
LINT_RULES: dict[str, set[str]] = ...

# see Example 2.5 - Lint: cross-cluster references
CONTEXT_RULES: dict[str, set[str]] = ...

EXTRA_ROOTS: set[str] = {
    'World'
    # ...
}

# see Example 1.1 - Finding assets
class AssetType: ...

# see Example 1.1 - Finding assets
class Asset: ...

# see Example 2.2 - Reference scanning (fancier)
class Dependency: ...

@dataclass
class RoomGraph:
    """Bundle of room graph data."""

    room_name: str
    reachable_names: set[str]
    graph: rx.PyDiGraph
    name2index: dict[str, int]

# see Example 1.4 - Cluster aliasing
assets: list[Asset] = ...

# see Example 2.2 - Reference scanning (fancier)
dependencies: list[Dependency] = ...

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
        if dep.target_asset.asset_type == AssetType.ROOM:
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

for asset_room in assets:
    if asset_room.asset_type != AssetType.ROOM:
        continue
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
```
### Example 3.2 - Lint: unreachable assets
Identify unreachable assets.

With our newly build reachability map we can indentify which assets are
never referenced in any room. This would solve closed loops we've
been skipping over in simpler linter.

```python
import collections

# see Example 2.5 - Lint: cross-cluster references
LINT_RULES: dict[str, set[str]] = ...

# see Example 2.5 - Lint: cross-cluster references
CONTEXT_RULES: dict[str, set[str]] = ...

# see Example 3.1 - Generate set of used assets in each room
EXTRA_ROOTS: set[str] = ...

# see Example 1.1 - Finding assets
class AssetType: ...

# see Example 1.1 - Finding assets
class Asset: ...

# see Example 2.2 - Reference scanning (fancier)
class Dependency: ...

# see Example 3.1 - Generate set of used assets in each room
class RoomGraph: ...

# see Example 1.4 - Cluster aliasing
assets: list[Asset] = ...

# see Example 2.2 - Reference scanning (fancier)
dependencies: list[Dependency] = ...

# see Example 3.1 - Generate set of used assets in each room
room_graph_data: dict[str, RoomGraph] = ...

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

# we must explicitly add the Rooms themselves (edges to them
#  were severed in the previous step)
all_used_names.update(
    asset.name for asset in assets if asset.asset_type == AssetType.ROOM
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
            key=lambda a: (a.asset_type.name, a.tree_path, a.name),
        ):
            print(
                f'[{asset.asset_type.name: <10}] '
                f'{"/".join(asset.tree_path)}'
                f'/{asset.name}'
            )

        print()
```
### Example 3.3 - Lint: room cluster boundaries
Validate room and their dependencies clustering boundaries.

Final step of linting process before the project would be qualified for
destructive (and actually useful) tools in validating cluster boundaries
on rooms as a whole.

Note that this tool is intended to be used only after resolved every
issue raised by simpler crossref linter.

```python
import rustworkx as rx

# see Example 2.5 - Lint: cross-cluster references
LINT_RULES: dict[str, set[str]] = ...

# see Example 2.5 - Lint: cross-cluster references
CONTEXT_RULES: dict[str, set[str]] = ...

# see Example 3.1 - Generate set of used assets in each room
EXTRA_ROOTS: set[str] = ...

# see Example 1.1 - Finding assets
class AssetType: ...

# see Example 1.1 - Finding assets
class Asset: ...

# see Example 2.2 - Reference scanning (fancier)
class Dependency: ...

# see Example 3.1 - Generate set of used assets in each room
class RoomGraph: ...

# see Example 1.4 - Cluster aliasing
assets: list[Asset] = ...

# see Example 2.2 - Reference scanning (fancier)
dependencies: list[Dependency] = ...

# see Example 3.1 - Generate set of used assets in each room
room_graph_data: dict[str, RoomGraph] = ...

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
   - DON'T use timelines
   - DON'T use the dastardly "Treat uninitialized variables as 0 (BAD!!!)" option
   - Minimize usage of persistent objects (they get tagged as referenced in every existing room)
4. Follow good coding practices
    - No dynamic asset referencing (tool won't acknowledge those references when building dependency graph):
      - DON'T do math on asset IDs: `draw_sprite(sprSpikeUp+2, x, y)`
      - DON'T use string execution: `execute_string("instance_create(0, 0, obj_enemy_" + string(current_level) + ")")`
      - DON'T pass assets via global variables across cluster boundaries: `global.current_boss = obj_StageB_Boss` (If Stage A reads this global, the analyzer cannot trace the dependency)
      - ^ That rule includes assigning assets to constants
    - Use the linter ignore pragma `//!clunkster: ignore` only in pure data registry scripts (like ``sound_balance``), which only reference assets but don't instantiate them

Other than that, use the modern project format (`.gm82`) and Python 3.14+ ([`uv`](https://docs.astral.sh/uv/) recommended).

Following sections elaborate on prerequisites, reasons behind them, antipatterns, and how to properly fix them.

### [HowTo] Prerequisites - Project & Asset organization

<!--[[[cog
cog.outl(f"""
Since Clunkster largely relies on splitting assets into clusters, the tool needs a way to automatically generate clusters for each asset. The easiest implementation parses `tree.yyd` files and takes the name of the root directory as a cluster name (see [{rend.href('ex_clusters')}]), merging those based on a provided config (see [{rend.href('ex_aliases')}]). Therefore, some amount of project keeping is required.
""")
]]]-->

Since Clunkster largely relies on splitting assets into clusters, the tool needs a way to automatically generate clusters for each asset. The easiest implementation parses `tree.yyd` files and takes the name of the root directory as a cluster name (see [[ex1.3](#example-13---generating-clusters)]), merging those based on a provided config (see [[ex1.4](#example-14---cluster-aliasing)]). Therefore, some amount of project keeping is required.

<!--[[[end]]]-->
❌ Bad:

Sprites:
```
+Enemies
    |sprite83
    |enemy
    |enemy_burn
    |spr_stageA_specific_enemy_that_is_not_encountered_anywhere_else
+StageA
    |a_sprite_that_is_used_to_be_stageA_specific_but_is_in_fact_used_everywhere
+StageFinalBoss_2_Fix_Final
    |enemy
```
Backgrounds:
```
+Stage3
    |bgStage1
    |tileset_that_is_used_everywhere_but_its_in_this_folder_for_reason
    |bgDarkness_2000x200_semitransparent_black_with_spotlight_in_center
```

While the tool doesn't require you to name things properly, no duplicates can exist in the project. Secondly, since the folder structure now has structural value to our clusterization, you should dedicate some effort to cleaning up the project posthaste.

✅ Good:

Sprites:
```
+sprEnemies
    |sprEnemySpawner
    |sprEnemy
    |sprEnemyBurn
    |sprEnemyPoisoned
+sprStageA
    |sprFireball
+sprStageFinal
    |sprEnemyBuffed
```
Backgrounds:
```
+bgStageA
    |bStageA
+bgStageC
    |bStageC
tCommon
```

With this well organized asset tree you can write an `ALIAS` config so they get correctly assigned to their clusters:

```python
ALIAS: dict[str, list[str]] = {
    'StageA': [
        'sprStageA',
        'bgStageA'
    ],
    'StageC': [
        'bgStageC'
    ],
    'Common': [
        'sprEnemies',
        # tCommon was automatically assigned Common cluster,
        # since its in the root of the tree
    ],
    # ...
}
```

Even though appropriate naming of the assets isn't required, I recommend cleaning them up now. It would also be a good idea to do optimization passes before starting integrating Clunkster (unless you have an "unrunable game" situation like I had when I started making this tool).

In some cases, it might help to prepend asset names with their stage name for easy reference. However, whenever you'll have to move things around (and you _will_), renaming assets would take some effort.

> Tip: When renaming assets, use the IDE's search utility to find all occurrences of the asset name in any code.

### [HowTo] Prerequisites - Eradicating dynamic asset referencing

I have seen these ones quite often. Let's look at anti-patterns from the [Prerequisites](#prerequisites) list.

❌ Bad: Doing maths on asset IDs.

```gml
// BAD: Analyzer only sees 'spr_player_base', misses the rest
draw_sprite(spr_player_base + current_animation, image_index, x, y)
```

This logic relies on Game Maker's internal resource order. While the order was made much more predictable in Game Maker 8.2's new save format, it is still fairly hidden and should not be used in general.

❌ Bad: String execution.

```gml
// BAD: Analyzer cannot trace the boss asset
execute_string(str_cat("instance_create(x, y, obj_boss_", current_level,")"))
```

`execute_string` requires Game Maker to parse it and build an AST at runtime, which is slow. Any dynamic code execution should generally be limited to functions like `variable_*`, and those should never reference assets.

Let's refactor those pesky examples.

✅ Good: Use explicit references...

```gml
// GOOD: All assets are explicitly declared and mapped
switch current_level {
    case "forest": instance_create(x, y, obj_boss_forest) break
    case "volcano": instance_create(x, y, obj_boss_volcano) break
}
```

✅ Good: ... or arrays
```gml
var _amb;
_amb[0] = "sfx_ambience0"
_amb[1] = "sfx_ambience1"
_amb[2] = "sfx_ambience2"
_amb[3] = "sfx_ambience3"
_amb[4] = "sfx_ambience4"

sound_loop(_amb[irandom(4)])
```


### [HowTo] Prerequisites - Building dependency flow

If you've decided to use this tool before the project has reached critical mass - this section is for you.

A healthy dependency graph flows in one direction: Stage-specific assets may reference Common assets, but Common assets cannot hardcode references to Stage-specific assets. Therefore, any sort of ubiquitous object (like the Player or World) should remain agnostic to the stages they occupy. Let's look at an example.

The Ice Stage of the game contains new special spikes that fall from the ceiling. You created a new object: `SpikeIce`. Now you have to make the Player take damage when they touch it. Sounds easy!

❌ Bad:

```gml
///Player.Step
if place_meeting(x, y, SpikeIce) {
    player_take_damage()
}
```
<!--[[[cog
cog.outl(f"""
Now the Player directly references `SpikeIce`. The {rend.href("ex_lint_crossref", "analyzer")} will flag this, because the Player now requires the `SpikeIce` asset (and, therefore, all of it's referenced assets down the line, such as its sprite) to be loaded globally.
""")
]]]-->

Now the Player directly references `SpikeIce`. The [analyzer](#example-25---lint-cross-cluster-references) will flag this, because the Player now requires the `SpikeIce` asset (and, therefore, all of it's referenced assets down the line, such as its sprite) to be loaded globally.

<!--[[[end]]]-->
This can be solved in a few ways.

**Version 1 - Moving the logic from Common to Stage-specific**

Just invert the logic - make the spikes damage the player, instead of the player checking for spikes:

```gml
///IceSpike.Step
if place_meeting(x, y, Player) {
    player_take_damage()
}
```

This works (and is the best solution in many cases), but I bet this game has some other damage sources. How about we...

**Version 2 - Turn explicit reference into implicit ones**

... introduce a new Common object `ParentHazard`, and simply make the original Player logic poll for hazards, instead of specific spikes:

```gml
///Player.Step
if place_meeting(x, y, ParentHazard) {
    player_take_damage()
}
```

This is also a valid solution in many cases.

___

Now let's think of something less trivial. The Player now gains the ability to use spells, and the Ice Stage adds ice magic when picking up a certain powerup, implemented like this:

❌ Bad:

```gml
///Player.KeyPress_50

if global.Powerups[powerup_shield] {
    // Common spell
    instance_create(x, y, ProjectileShield)
}

if global.Powerups[powerup_spell_ice] {
    // Ice Stage spell
    instance_create_moving(x, y, ProjectileIcicle, 1, 270, 0.2)
}
```

You can already see the Common to Stage-specific reference. We can fix it in a few ways.

**Version 1 - Moving the logic from Common to Stage-specific**

Make picking up a spell spawn an Ice Stage-bound object `SpellIcicle`, which houses the logic for shooting it.

```gml
///SpellIcicle.KeyPress_50
with Player {
    //handle the case when player doesn't exist (dead)
    instance_create_moving(x, y, ProjectileIcicle, 1, 270, 0.2)
}
```

Now the Player doesn't know about `ProjectileIcicle`. This solution works well for small, isolated gimmicks. However, if you want to combine the logic of several Stage-specific things, keeping a perfect dependency flow might be impossible. For such cases, we introduce...

**Version 2 - Context-aware logic**

Imagine now we want to assign spells to different keys and make sure the Player can't use an icicle while having a shield up or a new multistage spell "Blizzard" (existing in a cluster `CommonNorth`, which is accessed by both Ice Stage and Tundra Stage) is active. To punish spell abuse, you decide to add logic for Player freezing to death when spamming cold spells.

This logic can be implemented as an abstract "temperature" variable on the Player, or it can be put into a controller object. Such as `ControllerSpellsNorth`:

```gml
///ControllerSpellsNorth.Create
freezing = 0

///ControllerSpellsNorth.Step
//unfreeze over time
freezing = approach(freezing, 0, 0.05)

///SpellIcicle.KeyPress_50
if room_is_ice() {
    with Player {
        //spawn the icicle projectile
        instance_create_moving(x, y, ProjectileIcicle, 1, 270, 0.2)

        //lower the chill
        other.freezing -= 10

        //check if frozen
        if other.freezing < -30 {
            player_kill(killcause_freeze)
        }
    }
}

///SpellIcicle.KeyPress_51
with Player {
    //spawn the blizzard projectile
    instance_create(x, y, ProjectileBlizzard)

    other.freezing -= 20

    if other.freezing < -30 {
        player_kill(killcause_freeze)
    }
}
```

A few things to digest from here:
1) `ControllerSpellsNorth` is now an object from `CommonNorth` as well - therefore it is totally allowed to reference any other asset from `CommonNorth`. After all, when the `CommonNorth` cluster is loaded, everything from it becomes available.
2) The new function `room_is_ice` - is not just an ordinary "location check script". It can be used as a "Context Guard" in Clunkster's analyzer. We can assign it a target cluster that this context guards behind itself (the `IceStage` in our case):
```python
CONTEXT_RULES: dict[str, set[str]] = {
    # guard for ice stage -specific things
    'room_is_ice': {
        'IceStage'

        # notice that we don't put any other more
        # "common" stages in here
    },

    # guard for things that are allowed in CommonNorth,
    # but don't require any more specific logic
    # (e.g. from IceStage)
    'room_is_north': {
        'CommonNorth'
    }
}
```
Now everything protected by this guard can freely reference any `IceStage` asset.

3) Since anything from the `CommonNorth` cluster should, logically, be available anywhere in `IceStage`, we must also define this behavior in a different config:
```python
LINT_RULES: dict[str, set[str]] = {
    # common assets cannot borrow from Stage specific folders
    'Common': {'Common'},

    'IceStage': {
        'Common',       # explicitly include the common cluster
        'CommonNorth',  # include the regional common cluster
        'IceStage'      # include anything from itself
    },

    # this will make any Ice Stage room load all 3 of those clusters
}
```
Now everything in `CommonNorth` can be freely accessed by `IceStage`.

> Tip: The attentive ones among you have likely noticed that this same trick can be applied to a World object, making it useful again. I sure do hope having multiple persistent objects in the game won't become a big issue in some examples later down the line, haha.

Here's the sample implementation of those context guards.

```gml
///room_is_ice([room])
//Check whether the given room is from Ice Stage

var _room;
if argument_count == 0 {
    if global._clunkster_reg_mode return 1

    //optionally, if you are applying this tool onto an existing project,
    //you might want to temporarily bypass the guard, until you fix
    //all the initial bugs
    //return 1 //TEMP

    _room = room
}
else {
    _room = argument[0]
}

switch _room {
case rIceIntro:
case rIceBarrage:
    return 1
default:
    return 0
}
```

Notice that weird `global._clunkster_reg_mode` at the top. This is a secret tool that might come in handy later.

### [HowTo] Prerequisites - Timelines...

... nobody uses timelines, right?

Convert them to `switch` statements.

```gml
///Obj.Create
time=0

///Obj.Step
time+=1

switch time {
case 20:
    ... //code on Step 20
    break
case 100:
    ... //code on Step 100
    break
}
```

### [HowTo] Prerequisites - State contamination via Globals and Persistence

Now that we've handled the easy cases, let's start on some that are less obvious (and far harder to trace, since they won't get flagged in linters).

Global variables and persistent objects can cross cluster boundaries, making them vectors for dependency leakage.

❌ Bad: Passing a specific asset through a global variable or constant.

```gml
global.next_cutscene_actor = StageB_NpcFairy
```

If the Player enters Stage A, this reference will linger, and the analyzer won't be able to catch it. If the Player instantiates this reference in Stage A:

```gml
instance_create(x, y, global.next_cutscene_actor)
```

... it could potentially produce a broken stub-asset behavior if the Stage B has been unloaded.

❌ Bad: Overusing Persistence

Persistent objects act similarly to global variables. If you do something like:
```gml
with WeatherBlizzard {
    ControllerWeather.current_weather = id
}
```
and then `WeatherBlizzard`'s home cluster of `CommonNorth` gets unloaded, you might get the same result as the previous example.

✅ Good: Pass abstract strings or enums and let a stage-specific director object spawn the correct asset locally.

```gml
///StageB_NpcFairySpawner.Step
if global.next_cutscene_actor == "fairy" {
    instance_create(x, y, StageB_NpcFairy)
    global.next_cutscene_actor = ""
}
```

✅ Good: Don't forget to register all persistent objects in `EXTRA_ROOTS`:
```python
EXTRA_ROOTS: set[str] = {
    'World'
    # ...
}
```
As a side note, all dependencies of each Extra Root will be merged with dependency graph of **every** room, so unless you wanna deal with humongous dependency graphs, keep your persistent objects minimal. Ideally, just one `World` object.

### [HowTo] Prerequisites - Proper use of the Ignore Pragma

We provide a pragma for ignoring files during dependency scans: `//!clunkster: ignore`. You should only use it on pure data registries that define metadata without instantiating objects.

❌ Bad: Skipping Your Homework

```gml
///Player.Collision_ForestLog

//eeehhh i need to convert collision with stage-specific object event
// into an End Step event + rip all that boolean logic, hide every
// call behind a guard or something ehhhh

//i dont feel like doin it :3
//!clunkster: ignore

with Player  {
    save_set_persistent("deaths", save_get("deaths") + 1)
    if global.player_skin == "knight" instance_create(x, y, Knight_BloodEmitter)
    else if instance_exists(mario_kart) instance_create(mario_kart.x, mario_kart.y+24, BloodEmitter)
    else instance_create(x, y, BloodEmitter)
    if (global.darkStage) {
        dark_gib_sound(1)
    }
    else {
        sound_play("player_death")

        // Dance specific
        if is_in_game() && !global.paused {
            if room != rDanceStage {
                camera_update()
            } else {
                dance_camera_update()
            }
        }
    }
    instance_create(0, 0, GameOver)
    instance_destroy()
}
```

❌ Bad: Putting instantiating references into _registries_ (= making them impure)

```gml
///music_register()
//Register EVERY music in here
//!clunkster: ignore

music_def_begin("musStageTutorial",0.8)
    music_def_room(rTutorial,mus_autoplay)
    music_def_room(rTutorialBoss,mus_fadeout)
    music_def_room(rFinal_Respite,mus_autoplay)
music_def_end()

///World.RoomStart

//autostart music
_l_auto=dsmap(global._mus_room_auto,room)
if not is_undefined(_l_auto) {
    _s=ds_list_size(_l_auto)

    for (_i=0;_i<_s;_i+=1) {
        _snd=ds_list_find_value(_l_auto,_i)

        // BAD!!! The reference that was hidden from the linter
        // is now being passed into the an instantiating function.
        // Since Clunkster has no idea that rFinal_Respite needed
        // "musTitle", it might put it into a cluster that
        // rFinal_Respite has no access too, playing you an
        // unloaded stub asset.
        // Woe be upon you.
        music_play(_snd)
    }
}
```

✅ Good: Make registries only define pure data and non-instantiating references.

```gml
///music_register()
//Register EVERY music in here
//!clunkster: ignore

music_def_begin("musTitle")
    music_def_volume(0.8)
    music_def_og_samplerate(44100)
    music_def_loop(31*44100 + 19422, 70*44100 + 28955)

    //instead of defining autoplay logic in registry,
    // autoplay logic can be moved into a different file
    // without the ignore pragma

    //but we can still keep logic like "make sure the track is
    // stopped when we enter any room other than this".
    // sound_stop(...) is not an instantiating function,
    // and will work just fine if this specific sound
    // was replaced with a stub "null.wav"
    music_def_room_allowed(rTitle, rOptions, rFinal_Respite)
music_def_end()
```

✅ Good: Guard instantiating registry logic.

```gml
///music_register()
//Register EVERY music in here

// notice: the ignore is gone

if room_is_tutorial_or_final() {
    //anything shared between tutorial and final stage

    music_def_begin("musStageTutorial",0.8)
        music_def_room(rTutorial,mus_autoplay)
        music_def_room(rTutorialBoss,mus_fadeout)
        music_def_room(rFinal_Respite,mus_autoplay)

        //validate that all of the rooms actually belong to the cluster
        assert(room_is_tutorial_or_final(rTutorial))
        assert(room_is_tutorial_or_final(rTutorialBoss))
        assert(room_is_tutorial_or_final(rFinal_Respite))
    music_def_end()
}
```

And, since this registry, ideally, runs only on game start, in order to not loose data that we deliberately hidden behind guard, we can introduce a little ethical hack (that doesn't ruin our cluster-boundary model).

Remember the `global._clunkster_reg_mode` from before? Here's out plan:

New script `clunkster_init`:

```gml
///clunkster_init()
global._clunkster_reg_mode = 0

//any other initialization logic might be
// autogenerated by Clunkster and added here
```

New script `clunkster_registry_begin`:

```gml
///clunkster_registry_begin()
global._clunkster_reg_mode = 1
```

New script `clunkster_registry_end`:

```gml
///clunkster_registry_end()
global._clunkster_reg_mode = 0
```

And here's how we will call the registries in Game Start:

```gml
clunkster_registry_begin()
    sound_register()
    music_register()
clunkster_registry_end()
```

And guards should intelligently silence themselves if used as context guards in registry mode, but still do proper validation if they were given an actual room:

```gml
///room_is_tutorial_or_final([room])
//Check whether the given room is from Tutorial or Final Stage

var _room;
if argument_count == 0 {
    if global._clunkster_reg_mode return 1

    //optionally, if you are applying this tool onto an existing project,
    //you might want to temporarily bypass the guard, until you fix
    //all the initial bugs
    //return 1 //TEMP

    _room = room
}
else {
    _room = argument[0]
}

switch _room {
case rTutorial:
case rTutorialBoss:
case rFinal_Respite:
    return 1
default:
    return 0
}
```

## Workflow

This is the workflow that I used for the project that this tool was initially made for. As of now, each step of the workflow is represented as an example in [Examples](#examples) section. Examples without links are WIP.

### Preparation

<!--[[[cog
# dum pogapp cant do inline inserts
cog.outl(f"""
Firstly, you should build the initial dependency scanning pipeline.

This starts with parsing `tree.yyd` files in order to discover assets and run initial checks to determine, what needs to be fixed before generating clusters.  generate initial cluster map. Therefore, in this step your goal is to:
- ensure that stage assets are grouped in consistently named folders across all asset types

See examples:
- [{rend.href('ex_start')}] setting up asset discovery

After that we may generate initial cluster map. In this step our goal is:
- assign clusters based on `tree.yyd` data
- make aliases for folders that don't represent actual clusters (such as "Tiles" backgrounds or "Killers" objects)

See examples:

- [{rend.href('ex_clusters')}] generating initial cluster map
- [{rend.href('ex_aliases')}] fixing duplicate clusters via aliases

Next, you want to set up dependency scanning. For this, we use [`ahocorasick`](https://pypi.org/project/pyahocorasick/). In my testing, sync version takes around the same amount of time as multiprocessing, so no real difference here.

See examples:
- [{rend.href('ex_scan_sync')}] simple references generator
- [{rend.href('ex_scan_sync2')}] reference generator with better struct and progressbar :3
- [{rend.href('ex_scan_mp')}] multiprocessing reference generator

Once that's done you may start with some initial cleaning. Basic linter can find most violations just by checking each dependency on presence of cross-cluster references.

See example:
- [{rend.href('ex_lint_unused')}] finding unused assets (simple ver)
- [{rend.href('ex_lint_crossref')}] finding cross-cluster references
""")
]]]-->

Firstly, you should build the initial dependency scanning pipeline.

This starts with parsing `tree.yyd` files in order to discover assets and run initial checks to determine, what needs to be fixed before generating clusters.  generate initial cluster map. Therefore, in this step your goal is to:
- ensure that stage assets are grouped in consistently named folders across all asset types

See examples:
- [[ex1.1](#example-11---finding-assets)] setting up asset discovery

After that we may generate initial cluster map. In this step our goal is:
- assign clusters based on `tree.yyd` data
- make aliases for folders that don't represent actual clusters (such as "Tiles" backgrounds or "Killers" objects)

See examples:

- [[ex1.3](#example-13---generating-clusters)] generating initial cluster map
- [[ex1.4](#example-14---cluster-aliasing)] fixing duplicate clusters via aliases

Next, you want to set up dependency scanning. For this, we use [`ahocorasick`](https://pypi.org/project/pyahocorasick/). In my testing, sync version takes around the same amount of time as multiprocessing, so no real difference here.

See examples:
- [[ex2.1](#example-21---reference-scanning)] simple references generator
- [[ex2.2](#example-22---reference-scanning-fancier)] reference generator with better struct and progressbar :3
- [[ex2.3](#example-23---reference-scanning-multiprocessing)] multiprocessing reference generator

Once that's done you may start with some initial cleaning. Basic linter can find most violations just by checking each dependency on presence of cross-cluster references.

See example:
- [[ex2.4](#example-24---lint-unused-assets)] finding unused assets (simple ver)
- [[ex2.5](#example-25---lint-cross-cluster-references)] finding cross-cluster references

<!--[[[end]]]-->

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
