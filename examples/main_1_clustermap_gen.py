"""Build cluster map out of tree data (minimalist version).

This script scans the project's ``tree.yyd`` files to automatically group
assets into clusters based on their top-level folder in the IDE.
Outputs a Python dictionary that you can inspect, before moving
onto next examples.
"""

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


def main() -> None:
    project_root = Path(sys.argv[1])

    # map of cluster to its assets
    cluster_map: dict[str, list[str]] = {}

    # iterate through all clusterable assets to check their tree.yyd
    for asset_type in CLUSTERABLE_ASSETS:
        asset_dir = project_root / asset_type.get_dir()
        # skip assets that are not present in the project
        if not asset_dir.exists():
            continue

        # read tree.yyd
        tree_text = (asset_dir / 'tree.yyd').read_text(encoding='utf-8')
        # run parsing
        for asset_name, path in tree.parse(tree_text.splitlines()):
            # if asset is in asset type root, then its common
            cluster_name = path[0] if path else 'Common'
            # fill in the map
            cluster_map.setdefault(cluster_name, []).append(asset_name)

    # json.dumps gives better formatting that pprint
    print(json.dumps(cluster_map, indent=4))


if __name__ == '__main__':
    main()
