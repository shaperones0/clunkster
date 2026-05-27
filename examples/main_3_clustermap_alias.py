"""Manually fix inconsistencies in cluster map.

After we did initial scan, you may encounter inconsistencies like different
clusters ``"StageA"`` and ``"stage_a"`` (project didn't follow strict naming),
as well as a bunch of things that should belong to Common cluster
(Backgrounds, Game, etc.).

That's why we added a few trinkets to the script:
1. alias system.
2. table like output, so you can easily sort out most duplicates.
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
    # merged those 2 into all, added explicit logic later down the line.
    AssetType.DATA_SFX,
    AssetType.DATA_MUSIC,
)

# now we have the alias dictionary
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


def main() -> None:
    project_root = Path(sys.argv[1])

    # map of cluster to its assets
    cluster_map: dict[str, list[str]] = {}
    # map of asset type to clusters (useful for initial cleanup)
    asset_to_cluster: dict[AssetType, list[str]] = {}
    # build cluster to name (process ALIAS dict)
    cluster_to_name: dict[str, str] = {}
    for name, clusters in ALIAS.items():
        for cluster in clusters:
            if cluster in cluster_to_name:
                raise ValueError('Invalid cluster map (duplicate aliases)')
            cluster_to_name[cluster] = name

    for asset_type in CLUSTERABLE_ASSETS:
        # this one assumes same search logic for all external assets
        is_external = asset_type in (AssetType.DATA_SFX, AssetType.DATA_MUSIC)

        asset_dir = project_root / asset_type.get_dir()
        if not asset_dir.exists():
            continue

        # fill in set of clusters associated with this asset type
        cluster_set: set[str] = set()
        # create asset iterator (asset_name, folder path)
        if is_external:
            asset_iter = (
                (f'"{file.stem}"', file.relative_to(asset_dir).parts[:-1])
                for file in asset_dir.rglob('*')
            )
        else:
            tree_text = (asset_dir / 'tree.yyd').read_text(encoding='utf-8')
            asset_iter = tree.parse(tree_text.splitlines())

        # iterate them assets
        for asset_name, path in asset_iter:
            cluster_name = path[0] if path else 'Common'
            if cluster_name in cluster_to_name:
                cluster_name = cluster_to_name[cluster_name]

            cluster_set.add(cluster_name)
            cluster_map.setdefault(cluster_name, []).append(asset_name)
        asset_to_cluster[asset_type] = list(cluster_set)

    print(json.dumps(cluster_map, indent=4))

    # print the asset type to cluster
    # (visually set up to help finding duplicates)
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


if __name__ == '__main__':
    main()
