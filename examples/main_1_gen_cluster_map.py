"""Build cluster map out of tree data.

This script scans the project's ``tree.yyd`` files to automatically group
assets into clusters based on their top-level folder in the IDE.
Outputs a Python dictionary that you can edit and copy into later scripts.
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
    for asset_type, clusters in asset_to_cluster.items():
        cluster_set = set(clusters)
        row: list[str] = []
        for col in clusters_all:
            if col in cluster_set:
                row.append(col)
            else:
                row.append(' ' * len(col))
        print(f'{asset_type.get_dir(): >15}:', *row)


if __name__ == '__main__':
    main()
