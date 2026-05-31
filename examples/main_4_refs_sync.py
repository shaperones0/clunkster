"""Simple scanner.

We compile Aho-Corasick automaton to quickly scan every text
(script or metadata file) in the project for asset references.

This code is done in a simple synchronous way, but it is possible to
run the search in threads or multiprocessing (done in later examples).
"""

import json
import sys
from dataclasses import dataclass
from pathlib import Path

from ahocorasick import Automaton  # ty: ignore[unresolved-import]

from clunkster.analyze import scan_dep
from clunkster.asset import (
    AssetType,
    asset_get_project_dir,
    asset_get_scannable_files,
)
from clunkster.parse import tree


@dataclass
class Asset:
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
    assets: list[Asset] = []

    cluster_map: dict[str, list[str]] = {}
    asset_to_cluster: dict[AssetType, list[str]] = {}

    # invert ALIAS
    cluster_to_name: dict[str, str] = {}
    for name, clusters in ALIAS.items():
        for cluster in clusters:
            if cluster in cluster_to_name:
                raise ValueError('Invalid cluster map (duplicate aliases)')
            cluster_to_name[cluster] = name

    # discover assets and assign clusters
    for asset_type in CLUSTERABLE_ASSETS:
        is_external = asset_type in (AssetType.DATA_SFX, AssetType.DATA_MUSIC)

        asset_dir = project_root / asset_get_project_dir(asset_type)
        if not asset_dir.exists():
            continue

        # asset iterator (asset_name, folder path)
        if is_external:
            asset_iter = (
                (f'"{file.stem}"', file.relative_to(asset_dir).parts[:-1])
                for file in asset_dir.rglob('*')
                if file.is_file()
            )
        else:
            tree_text = (asset_dir / 'tree.yyd').read_text(encoding='utf-8')
            asset_iter = tree.parse(tree_text.splitlines())

        cluster_set: set[str] = set()
        for asset_name, path in asset_iter:
            cluster_name = path[0] if path else 'Common'
            cluster_name = cluster_to_name.get(cluster_name, cluster_name)

            cluster_set.add(cluster_name)
            cluster_map.setdefault(cluster_name, []).append(asset_name)

            assets.append(
                Asset(
                    asset_type=asset_type,
                    name=asset_name,
                    cluster=cluster_name,
                    files_to_scan=asset_get_scannable_files(
                        asset_type, asset_name, project_root
                    ),
                )
            )
        asset_to_cluster[asset_type] = list(cluster_set)

    print(json.dumps(cluster_map, indent=4))

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
        print(f'{asset_get_project_dir(asset_type): >12}:', '|'.join(row))

    # sync scan
    automaton = Automaton()
    for asset in assets:
        automaton.add_word(asset.name, asset.name)
    automaton.make_automaton()
    total_matches = 0

    for asset in assets:
        for file_path in asset.files_to_scan:
            text = file_path.read_text(encoding='utf-8')
            matches: list[scan_dep.DependencyMatch] = list(
                scan_dep.scan(automaton, asset.name, file_path.name, text)
            )

            total_matches += len(matches)

            # print the first few matches just to prove it works
            if matches:
                for match in matches[:3]:
                    loc = match.location
                    print(
                        f'[{loc.asset_name}] '
                        f'-> {match.target_asset} '
                        f'({loc.file_name}:{loc.loc_line}:{loc.loc_column})'
                    )

    print(f'\nDone! Found {total_matches} total dependency references.')


if __name__ == '__main__':
    main()
