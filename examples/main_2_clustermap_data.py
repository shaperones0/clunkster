"""Populate clustermap with unconventional assets.

Some projects make use of external assets, such as for gm82snd.
In case of gm82snd, I have hardcoded it to look for music in ``data/music``
and for sounds in ``data/sounds``.
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

CLUSTERABLE_DATA: tuple[AssetType, ...] = (
    AssetType.DATA_SFX,
    AssetType.DATA_MUSIC,
)


def main() -> None:
    project_root = Path(sys.argv[1])

    cluster_map: dict[str, list[str]] = {}
    for asset_type in CLUSTERABLE_ASSETS:
        asset_dir = project_root / asset_type.get_dir()
        if not asset_dir.exists():
            continue

        tree_text = (asset_dir / 'tree.yyd').read_text(encoding='utf-8')
        for asset_name, path in tree.parse(tree_text.splitlines()):
            cluster_name = path[0] if path else 'Common'
            cluster_map.setdefault(cluster_name, []).append(asset_name)

    # add external data
    for asset_type in CLUSTERABLE_DATA:
        # you may want to manually map dir names if you don't use
        #  data/sounds for sfx and data/music for bgm
        asset_dir = project_root / asset_type.get_dir()
        if not asset_dir.exists():
            continue

        # you may also want to set up a better glob filter here
        for file in asset_dir.rglob('*'):
            # split relative path into folders
            path = file.relative_to(asset_dir).parts[:-1]
            cluster_name = path[0] if path else 'Common'
            # gm82snd uses file stems in quotes for referencing
            cluster_map.setdefault(cluster_name, []).append(f'"{file.stem}"')

    # json.dumps gives better formatting that pprint
    print(json.dumps(cluster_map, indent=4))


if __name__ == '__main__':
    main()
