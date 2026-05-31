"""Build cluster map out of tree data (minimalist version).

This script scans the project's ``tree.yyd`` files to automatically group
assets into clusters based on their top-level folder in the IDE.
Outputs a Python dictionary that you can inspect before moving on.
"""

import json
import sys
from pathlib import Path

from clunkster.asset import AssetType, asset_get_project_dir
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

# asset struct is omitted as it's not required until we actually scan
#  files contents


def main() -> None:
    project_root = Path(sys.argv[1])

    # map of cluster to its assets
    cluster_map: dict[str, list[str]] = {}

    for asset_type in CLUSTERABLE_ASSETS:
        asset_dir = project_root / asset_get_project_dir(asset_type)
        if not asset_dir.exists():
            continue

        tree_text = (asset_dir / 'tree.yyd').read_text(encoding='utf-8')
        for asset_name, path in tree.parse(tree_text.splitlines()):
            # if asset is in root, then it's common
            cluster_name = path[0] if path else 'Common'
            cluster_map.setdefault(cluster_name, []).append(asset_name)

    # json.dumps gives better formatting that pprint
    print(json.dumps(cluster_map, indent=4))


if __name__ == '__main__':
    main()
