# Clunkster

Split assets into clusters (or chunks, packs, or whatever) to lighten the load. 

You probably don't need assets from area A while playing or working on area B.

Given the many different circumstances of the projects this tool might be used on, it was organized as a set of "examples" that can be copied and modified for best effect. Useful functions that facilitate the core logic are provided as well.

However, you might want to address [Rationale](#rationale) and [Prerequisites](#prerequisites) to see if the tool fits your needs and your project.

Planned tools:
- [x] Asset clusterizer based on folders in `tree.yyd` files (mostly helps other tools).
- [ ] Dependency graph builder (constructs the list of assets that are "potentially used" in each room).
- [ ] Dependency linter (things in a room from chunk A should not require things bound to chunk B).
- [ ] Project crippler (replace assets with lightweight dummies for faster development)
- [ ] Externator (generate external versions of assets and generate code for their loading)
- [ ] Game splitter (run Externator, ensure rooms will have assets from their chunks loaded)

## TOC

<!--[[[cog
import sys
sys.path.append("scripts")
from readme_toc import generate_toc

generate_toc()
]]]-->
* [Clunkster](#clunkster)
  * [Examples](#examples)
    * [Example 1 - Finding assets](#example-1---finding-assets)
    * [Example 2 - External assets (`data/`)](#example-2---external-assets-data)
    * [Example 3 - Generating clusters](#example-3---generating-clusters)
    * [Example 4 - Cluster aliasing](#example-4---cluster-aliasing)
    * [Example 5 - Reference scanning](#example-5---reference-scanning)
    * [Example 6 - Reference scanning (fancy)](#example-6---reference-scanning-fancy)
    * [Example 7 - Reference scanning (multiprocessing)](#example-7---reference-scanning-multiprocessing)
  * [Rationale](#rationale)
    * [Dev solution](#dev-solution)
    * [Prod solution](#prod-solution)
    * [Safety backbone (dependency linter)](#safety-backbone-dependency-linter)
  * [Prerequisites](#prerequisites)
  * [Workflow](#workflow)
    * [Preparation](#preparation)
  * [Dehydration strategy for each asset type](#dehydration-strategy-for-each-asset-type)
<!--[[[end]]]-->

## Examples

The following examples represent actual workflows. Copy and modify as needed.

### Example 1 - Finding assets

<!--[[[cog
from scripts import readme_snippets, readme_imports, readme_docstring
import itertools as it

snippets = readme_snippets.SnippetExtractor.from_file_path('main.py')
imports = readme_imports.ImportsFilter.from_file_path('main.py')
docs = readme_docstring.extract_file('main.py')

snips_main = snippets.extract('MAIN_EX_START')
snips_prepend = [
    snippets.extract('CLS_ASSET'),
    snippets.extract('CLUSTERABLE_BUILTINS'),
    snippets.extract('PROJECT')
]
snip_docs = readme_snippets.Snippet.from_md(
    docs['main_ex_start']
)
snip_imports = readme_snippets.Snippet.from_code(
    imports.filter_used_unparse(
        snips_main[0].content,
        *(
            snip[0].content for snip in snips_prepend
        )
    )
)

cog.outl(readme_snippets.snippets_render(
    snip_docs,
    snip_imports,
    *it.chain.from_iterable(snips_prepend),
    *snips_main
))
]]]-->
First, we want to check that builtin assets get scanned correctly.

```python
from dataclasses import dataclass
from pathlib import Path
from clunkster.asset import AssetType
from clunkster.parse import tree as my_parse_tree

@dataclass
class Asset:
    """Simple asset definition."""

    asset_type: AssetType
    name: str
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
    # get project directory for the given asset type
    asset_dir = PROJECT / asset_type.get_dir()
    if not asset_dir.exists():
        continue

    # iterate through tree.yyd file of the asset type

    # we use tree.yyd as source of truth for later examples,
    #  however, undesired results happen if tree.yyd has duplicate assets,
    #  which it technically can have
    tree_text = (asset_dir / 'tree.yyd').read_text(encoding='utf-8')

    # parser for tree files is included (second argument is path to asset)
    for asset_name, _path in my_parse_tree.parse(tree_text.splitlines()):
        # we don't have clusters yet so we'll just set it to "Unknown"
        # also skip the scanning part
        assets.append(
            Asset(
                asset_type=asset_type,
                name=asset_name,
                cluster='Unknown',
                files_to_scan=tuple(
                    asset_type.get_scannables(asset_name, PROJECT)
                ),
            )
        )

# you should investigate the resulting array for inconsistencies
print(f'Discovered {len(assets)} total assets.')
```
<!--[[[end]]]-->

### Example 2 - External assets (`data/`)

<!--[[[cog
snips_main = snippets.extract('MAIN_EX_START_EXTERNALS_GIST')
snips_prepend = [
    snippets.extract('CLUSTERABLE_EXTERNALS'),
]
snip_docs = readme_snippets.Snippet.from_md(
    docs['main_ex_start_externals']
)
snip_imports = readme_snippets.Snippet.from_code(
    imports.filter_used_unparse(
        snips_main[0].content,
        *(
            snip[0].content for snip in snips_prepend
        )
    )
)

cog.outl(readme_snippets.snippets_render(
    snip_docs,
    # snip_imports,
    *it.chain.from_iterable(snips_prepend),
    *snips_main
))
]]]-->
Populate assets with externals.

Some projects make use of external assets, such as for gm82snd.
In case of gm82snd, I have hardcoded it to look for music in `data/music`
and for sounds in `data/sounds`.

```python
CLUSTERABLE_EXTERNALS: tuple[AssetType, ...] = (
    AssetType.DATA_SFX,
    AssetType.DATA_MUSIC,
)

# ...

# add external data
for asset_type in CLUSTERABLE_EXTERNALS:
    # you may want to manually map dir names if you don't use
    #  data/sounds for sfx and data/music for bgm
    asset_dir = PROJECT / asset_type.get_dir()
    if not asset_dir.exists():
        continue

    # you may also want to set up a better glob filter here
    for file in asset_dir.rglob('*'):
        if not file.is_file():
            continue

        # gm82snd references sounds by their file stems as strings
        asset_name = f'"{file.stem}"'
        assets.append(
            Asset(
                asset_type=asset_type,
                name=asset_name,
                cluster='Unknown',
                files_to_scan=tuple(
                    asset_type.get_scannables(asset_name, PROJECT)
                ),
            )
        )

# again, investigate the resulting array for inconsistencies
print(f'Discovered {len(assets)} total assets.')
```
<!--[[[end]]]-->

### Example 3 - Generating clusters

<!--[[[cog
snips_main = snippets.extract('MAIN_EX_CLUSTERS')
snips_prepend = [
    snippets.extract('CLS_ASSET'),
    snippets.extract('CLUSTERABLE_ASSETS'),
    snippets.extract('PROJECT')
]
snip_docs = readme_snippets.Snippet.from_md(
    docs['main_ex_clusters']
)
snip_imports = readme_snippets.Snippet.from_code(
    imports.filter_used_unparse(
        snips_main[0].content,
        *(
            snip[0].content for snip in snips_prepend
        )
    )
)

cog.outl(readme_snippets.snippets_render(
    snip_docs,
    snip_imports,
    *it.chain.from_iterable(snips_prepend),
    *snips_main
))
]]]-->
Autogenerate clusters for the assets.

Now that assets discovering works, we may generate clusters.

```python
from dataclasses import dataclass
from pathlib import Path
from clunkster.asset import AssetType
from clunkster.parse import tree as my_parse_tree

@dataclass
class Asset:
    """Simple asset definition."""

    asset_type: AssetType
    name: str
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
<!--[[[end]]]-->

### Example 4 - Cluster aliasing
<!--[[[cog
snips_main = snippets.extract('MAIN_EX_ALIAS_GIST_INVERT') + \
    snippets.extract('MAIN_EX_ALIAS_GIST_ALIAS')
snips_prepend = [
    snippets.extract('ALIAS'),
]
snip_docs = readme_snippets.Snippet.from_md(
    docs['main_ex_aliases']
)
snip_imports = readme_snippets.Snippet.from_code(
    imports.filter_used_unparse(
        snips_main[0].content,
        *(
            snip[0].content for snip in snips_prepend
        )
    )
)

cog.outl(readme_snippets.snippets_render(
    snip_docs,
    *it.chain.from_iterable(snips_prepend),
    *snips_main
))
]]]-->
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
<!--[[[end]]]-->

### Example 5 - Reference scanning

<!--[[[cog
snips_main = snippets.extract('MAIN_EX_SCAN_SYNC')
snips_prepend = [
    [readme_snippets.Snippet.from_code('# ... generate assets list')]
]
snip_docs = readme_snippets.Snippet.from_md(
    docs['main_ex_scan_sync']
)
snip_imports = readme_snippets.Snippet.from_code(
    imports.filter_used_unparse(
        snips_main[0].content,
        *(
            snip[0].content for snip in snips_prepend
        )
    )
)

cog.outl(readme_snippets.snippets_render(
    snip_docs,
    snip_imports,
    *it.chain.from_iterable(snips_prepend),
    *snips_main
))
]]]-->
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

# ... generate assets list

automaton = Automaton()
for asset in assets:
    automaton.add_word(asset.name, asset.name)
automaton.make_automaton()

total_matches = 0
for asset in assets:
    for file_path in asset.files_to_scan:
        matches: list[my_analyze_scan_dep.DependencyMatch] = list(
            my_analyze_scan_dep.scan(
                automaton, file_path.read_text(encoding='utf-8')
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
<!--[[[end]]]-->

### Example 6 - Reference scanning (fancy)
<!--[[[cog
snips_main = snippets.extract('MAIN_EX_SCAN_SYNC2')
snips_prepend = [
    snippets.extract('CLS_DEPENDENCY'),
    [readme_snippets.Snippet.from_code('# ... generate assets list')]
]
snip_docs = readme_snippets.Snippet.from_md(
    docs['main_ex_scan_sync2']
)
snip_imports = readme_snippets.Snippet.from_code(
    imports.filter_used_unparse(
        snips_main[0].content,
        *(
            snip[0].content for snip in snips_prepend if snip[0].type == readme_snippets.SnippetType.PYTHON
        )
    )
)

cog.outl(readme_snippets.snippets_render(
    snip_docs,
    snip_imports,
    *it.chain.from_iterable(snips_prepend),
    *snips_main
))
]]]-->
Simple scanner with some extra stuff.

We can add a progress bar + robust struct for storing our dependencies.

```python
from dataclasses import dataclass
import tqdm
from ahocorasick import Automaton
from clunkster.analyze import location as my_analyze_location
from clunkster.analyze import scan_dep as my_analyze_scan_dep

@dataclass
class Dependency:
    """Full dependency data to be used in graph building."""

    location: my_analyze_location.BoundLocation
    source_asset: Asset
    target_asset: Asset
    contexts: tuple[str, ...]

# ... generate assets list

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
    matches: list[my_analyze_scan_dep.DependencyMatch] = list(
        my_analyze_scan_dep.scan(
            automaton, file_path.read_text(encoding='utf-8')
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
<!--[[[end]]]-->

### Example 7 - Reference scanning (multiprocessing)

<!--[[[cog
snips_main = snippets.extract('MAIN_EX_SCAN_MP')
snips_prepend = [
    snippets.extract('CLS_SCAN_JOB'),
    snippets.extract('CLS_DEPENDENCY'),
    snippets.extract('REG_WORKERS_EXPLAIN'),
    snippets.extract('REG_WORKERS'),
    [readme_snippets.Snippet.from_code('# ... generate assets list')]
]
snip_docs = readme_snippets.Snippet.from_md(
    docs['main_ex_scan_mp']
)
snip_imports = readme_snippets.Snippet.from_code(
    imports.filter_used_unparse(
        snips_main[0].content,
        *(
            snip[0].content for snip in snips_prepend if snip[0].type == readme_snippets.SnippetType.PYTHON
        )
    )
)

cog.outl(readme_snippets.snippets_render(
    snip_docs,
    snip_imports,
    *it.chain.from_iterable(snips_prepend),
    *snips_main
))
]]]-->
Multiprocessing scanner.

Projects this tool is intended for can have thousands of scripts and
metadata files. To speed up the scanning, we employ multiprocessing.
We divide all the scanning tasks across a pool of worker processes.

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

@dataclass
class Dependency:
    """Full dependency data to be used in graph building."""

    location: my_analyze_location.BoundLocation
    source_asset: Asset
    target_asset: Asset
    contexts: tuple[str, ...]
```

We cannot send the compiled Aho-Corasick `Automaton` across process
boundaries safely. Instead, we use a global variable inside the worker
process and initialize it once when the process boots up.

```python
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
        matches=list(my_analyze_scan_dep.scan(_WORKER_AUTOMATON, text)),
        job=job,
    )

# ... generate assets list

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

    for future in tqdm.tqdm(
        futures.as_completed(submits),
        total=len(jobs),
        desc='Scanning',
    ):
        result: ScanResult = future.result()
        total_matches += len(result.matches)
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
<!--[[[end]]]-->

## Rationale

Game Maker 8.2 keeps the entire project in memory while open. The same goes for the `.exe` - the build process packs all resources into the executable, which are then unpacked and loaded during the initial loading screen.

A 450 MB project can consume 1.13 GB of RAM in the IDE (which translates into time spent on "Saving the project", "Saving the executable", "Loading" when the game is booting up, and some more loading on the first frame if the game uses external sound effects)

The problem:
- Hitting "Run test build" can take 10-15 seconds to get the game running.
- The game itself consumes around 2.5 GB of RAM.

### Dev solution

Most large projects naturally separate into logical clusters. You have "Common" assets (`Player`, `Block`, ...), and stage-specific assets (`bStageATiles`, `StageAPostProc`, ...). When dev is working on Stage A, they technically don't need assets from Stage B loaded in.

The solution is to replace the unneeded assets with lightweight stubs. You specify the clusters you are actively working on (e.g. `["Common", "StageA"]`), and the tool will carve out the rest.

Once the feature is done, discard the destructive edits via Git.

### Prod solution

The same strategy applies to optimized production builds. The tool packages each cluster into external packs ("wet" versions) and replaces assets inside the project with stubs ("dry" versions). When player enters a room that should have clusters "Common" and "StageA" loaded in, the game checks which required assets are missing and dynamically loads them ("hydrates") from the external packs.

_Though for now I haven't bothered with explicit unloading logic when leaving clusters._

### Safety backbone (dependency linter)

What happens if a developer accidentally references a `StageB` sprite inside a `StageA` object? At runtime, entering Stage A would produce unexpected behavior (in current implementation, stub sprites are pink-black checkerboards).

To prevent this, a dependency linter is included. It builds dependency graph based on static `.gml` and meta file analysis. This results in sets of assets "referenced" (both directly and indirectly) in each room. The linter then yells at you if a room references something that it isn't explicitly marked to load.

## Prerequisites

0. Use this tool only if it's necessary.
    - Setting this up requires a fair bit of technical knowledge (about both GameMaker 8.2 and Python) and can be a headache. I would only recommend using this tool if your game eats more than 2 GB of RAM and your project takes more than 10 seconds to build.
1. Use Git - changes made by this tool are destructive and **will nuke your project** (that's literally what Clunkster is designed to do).
2. Follow good project keeping practices
   - Keep asset names clean (press 🧹 icon on IDE's top toolbar to run required checks)
   - Keep assets belonging to certain stage in that stage's folder
   - Do not reference things from `stageA` in `stageB` objects (unless such an object is only placed in a room that guarantees both stages loaded)
   - Reference Common objects in Stage-specific, not the other way around
     - If this is unavoidable (for example, when making stage-specific a movement gimmick), use "_guard scripts_" (`if room_is_stageA() { ... }`)
   - If an asset is shared between multiple stages, then it belongs in Common cluster
3. Follow good coding practices
    - no dynamic asset referencing tomfoolery (tool won't acknowledge those references when building dependency graph):
      - DON'T do math on asset IDs: `draw_sprite(sprSpikeUp+2, x, y)`
      - DON'T use string execution: `execute_string("instance_create(0, 0, obj_enemy_" + string(current_level) + ")")`
      - DON'T hide script calls behind variables: `script_execute(current_state_script)`

And some less ideological requirements:

4. Use the modern project format (`.gm82`)
5. Python 3.10+ (`uv` recommended)
6. Close IDE before running the tool (or you'll get annoying popup (gross))

## Workflow

This is the workflow that I used for the project that this tool was initially made for. As of now, each step of the workflow is represented as an example in [Examples](#examples) section. Examples without links are WIP.

### Preparation

Firstly, you should build the initial dependency scanning pipeline.

This starts with parsing `tree.yyd` files in order to discover assets and generate initial cluster map. Therefore, in this step your goal is to:
- ensure that stage assets are grouped in consistently named folders across all asset types
- make aliases for folders that don't represent actual clusters (such as "Tiles" backgrounds or "Killers" objects)

See examples: 
- [1](#example-1---finding-assets) setting up asset discovery
- [2](#example-2---external-assets-data) adding external assets (`data/`)
- [3](#example-3---generating-clusters) generating initial cluster map
- [4](#example-4---cluster-aliasing) fixing duplicate clusters via aliases

Next, you want to set up dependency scanning. For this, we use [`ahocorasick`](https://pypi.org/project/pyahocorasick/). In my testing, sync version takes around the same amount of time as multiprocessing, so no real difference here.

See examples:
- [5](#example-5---reference-scanning) simple references generator 
- [6](#example-6---reference-scanning-fancy) reference generator with better struct and progressbar :3
- [7](#example-7---reference-scanning-multiprocessing) multiprocessing reference generator

Once that is done you may start with some initial cleaning.

Preparation:
1. Parse `tree.yyd` files in order to discover assets and generate initial cluster map:
   - ensure that stage assets are grouped in consistently named folders across all asset types
   - make aliases for folders that don't represent an actual cluster (such as "Tiles" backgrounds or "Killers" objects)
   - see examples:
     - [1](#example-1---finding-assets) setting up asset discovery
     - [2](#example-2---external-assets-data) adding external assets (`data/`)
     - [3](#example-3---generating-clusters) generating initial cluster map
     - [4](#example-4---cluster-aliasing) fixing duplicate clusters via aliases
2. Build dependencies:
   - map out which clusters are referenced in each room
   - manually clean up any architectural issues or spaghetti code this reveals
   - setup rules for automatically expanding the map for any new rooms
   - see examples:
     - [5](#example-5---reference-scanning) simple references generator 
     - [6](#example-6---reference-scanning-fancy) reference generator with better struct and progressbar :3
     - [7](#example-7---reference-scanning-multiprocessing) multiprocessing reference generator
3. Setup depgraph linter:
   - bake finalized room-to-clusters map and feed into dependency linter
   - See examples ?
4. TODO setup stub resources and script generation

## Dehydration strategy for each asset type

Following terms are used:
- dehydrate: the process of stripping the asset from the project.
- store-dry: how the stripped asset is represented inside resuling build (stubs).
- store-wet: how the actual data is stored externally.
- hydrate: the process of dynamically loading wet assets back into memory at runtime.

___

**Backgrounds**: impactful, high priority.
- dehydrate: TODO find a way to generate `.gmbck` files
- store-dry: pink-black checkerboard with transparent padding
- store-wet: `.gmbck` files
- hydrate: use `background_replace_background` to load externally
____
**Fonts**: aren't numerous enough to be impactful, and difficult.
____
**Objects**: moderately impactful, risky (and difficult).
____
**Paths**: aren't impactful.
____
**Room**: impactful, risky.
- dehydrate: 
  - read instances.txt, tiles and each object creation code, 
  - turn them into scripts that add them back in via `room_instance_add` (don't forget their respective globalvars) 
  - and `room_tile_add`, 
  - generate objects for each room instance creation code to be run on room start.
- store-dry: blank room with a single stub object (to raise errors).
- store-wet: aforementioned script and object.
- hydrate: run the scripts, add the room start object as well.
____
**Scripts**: impossible to create dynamically.
____
**Sprites**: impactful, high priority.
- dehydrate: TODO find a way to generate `.gmspr` files
- store-dry: pink-black checkerboard with transparent padding
- store-wet: `.gmspr` files
- hydrate: use `sprite_replace_sprite` to load externally
____
**Sounds**: very impactful, TODO.
____
**Data**: Sounds and Music: impactful, high priority.
- dehydrate: 
  - iterate through all sounds, 
  - put sounds from same cluster-set into WASD packs, 
  - generate a script that loads every existing sound as `null.wav` (or `buzz.wav`) via `sound_add_ext`,
   generate a script that would load said WASD pack
- store-dry: those live as `null.wav` files.
- store-wet: WASD pack.
- hydrate: run the WASD loader script.

