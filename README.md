# Clunkster

Split assets into clusters (or chunks, packs, or whatever) to lighten the load. 

You probably don't need assets from area A while playing or working on area B.

Given the many different circumstances of the projects this tool might be used on, it was organized as a set of "examples" that can be copied and modified for best effect. Useful functions that facilitate the core logic are provided as well.

However, you might want to address [Rationale](#rationale) to see if the tool fits your needs and your project.

Planned tools:
- [x] Asset clusterizer based on folders in `tree.yyd` files (mostly helps other tools).
- [ ] Dependency graph builder (constructs the list of assets that are "potentially used" in each room).
- [ ] Dependency linter (things in a room from chunk A should not require things bound to chunk B).
- [ ] Project crippler (replace assets with lightweight dummies for faster development)
- [ ] Externator (generate external versions of assets and generate code for their loading)
- [ ] Game splitter (run Externator, ensure rooms will have assets from their chunks loaded)

## Examples

The following examples represent actual workflows. Copy and modify as needed.

### Example 1 - Generating an initial Cluster Map.


<!--[[[cog
import sys
sys.path.append("scripts")
from readme_example import example_inject

example_inject("examples/main_1_gen_cluster_map.py")
]]]-->
Build cluster map out of tree data.

This script scans the project's `tree.yyd` files to automatically group
assets into clusters based on their top-level folder in the IDE.
Outputs a Python dictionary that you can edit and copy into later scripts.

It also outputs a table of cluster names, so you can pinpoint cases like
separate clusters "StageA" and "stage_a" when they should be the same thing.

```python
import json
import sys
from pathlib import Path

from clunkster.asset import AssetType
from clunkster.parse import tree

CLUSTERABLE_ASSETS: tuple[AssetType, ...] = (
    AssetType.SPRITE,
    AssetType.BACKGROUND,
    AssetType.SOUND,
    AssetType.PATH,
    AssetType.SCRIPT,
    AssetType.FONT,
    AssetType.OBJECT,
    AssetType.ROOM,
)

project_root = Path(sys.argv[1])

# map of cluster to its assets
cluster_map: dict[str, list[str]] = {}
# map of asset type to clusters (useful for initial cleanup)
asset_to_cluster: dict[AssetType, list[str]] = {}

for asset_type in CLUSTERABLE_ASSETS:
    asset_dir = project_root / asset_type.get_dir()
    if not asset_dir.exists():
        continue

    tree_text = (asset_dir / 'tree.yyd').read_text(encoding='utf-8')
    cluster_set: set[str] = set()
    for asset_name, path in tree.parse(tree_text.splitlines()):
        cluster_name = path[0] if path else 'Common'
        cluster_set.add(cluster_name)
        cluster_map.setdefault(cluster_name, []).append(asset_name)
    asset_to_cluster[asset_type] = list(cluster_set)

# json.dumps gives better formatting that pprint
print(json.dumps(cluster_map, indent=4))

# print the asset type to cluster
# (visually set up to help finding missing ones)
clusters_all = sorted(
    {name for clusters in asset_to_cluster.values() for name in clusters}
)
print('All clusters:', *clusters_all)
for asset_type, clusters in asset_to_cluster.items():
    cluster_set = set(clusters)
    row: list[str] = []
    for col in clusters_all:
        if col in cluster_set:
            row.append(col)
        else:
            row.append(' ' * len(col))
    print(f'{asset_type.get_dir(): >12}:', '|'.join(row))
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

### Workflow

This is the workflow that I used for the project that this tool was initially made for. As of now, each step of the workflow is represented as an example in [Examples](#examples) section. Examples without links are WIP.

Preparation:
1. Parse `tree.yyd` files in order to generate initial cluster map:
   - ensure that stage assets are grouped in consistently named folders across all asset types
   - make aliases for folders that don't represent an actual cluster (such as "Tiles" backgrounds or "Killers" objects)
   - see [Example 1](#example-1---generating-an-initial-cluster-map) & Example 2
2. Build depgraph:
   - map out which clusters are referenced in each room
   - manually clean up any architectural issues or spaghetti code this reveals
   - setup rules for automatically expanding the map for any new rooms
   - see Example 3
3. Setup depgraph linter:
   - bake finalized room-to-clusters map and feed into dependency linter
   - See Example 4
4. TODO setup stub resources and script generation

### Prerequisites

TODO

### Dehydration strategy for each asset type

Following terms are used:
- dehydrate: the process of stripping the asset from the project.
- store-dry: how the stripped asset is represented inside resuling build (stubs)
- store-wet: how the actual data is stored externally.
- hydrate: the process of dynamically loading wet assets back into memory at runtime

___

**Backgrounds**: impactful, high priority.
- dehydrate: TODO find a way to generate `.gmbck` files
- store-dry: pink-black checkerboard with transparent padding
- store-wet: `.gmbck` files
- hydrate: use `background_replace_background` to load externally
____
**Fonts**: aren't numerous enough, and difficult.
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

