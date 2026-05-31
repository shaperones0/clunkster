"""Before we do clusters, check that all assets actually get scanned."""

import sys
from dataclasses import dataclass
from pathlib import Path

from clunkster.asset import (
    AssetType,
    asset_get_project_dir,
    asset_get_scannable_files,
)
from clunkster.parse import tree


# asset struct is left to be made (and filled with all needed data) by user
@dataclass
class Asset:
    asset_type: AssetType
    name: str
    cluster: str
    files_to_scan: tuple[Path, ...]


# filter out clusters that you don't wanna even consider for clusterization
# (like paths or fonts)
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
    assets: list[Asset] = []

    for asset_type in CLUSTERABLE_ASSETS:
        # get project directory for the given asset type
        asset_dir = project_root / asset_get_project_dir(asset_type)
        if not asset_dir.exists():
            continue

        # iterate through tree.yyd file for given asset.
        # we use tree.yyd as source of truth for later examples,
        #  however, undesired results happen if tree.yyd has duplicate assets,
        #  which it totally can have
        tree_text = (asset_dir / 'tree.yyd').read_text(encoding='utf-8')

        # parser for tree files is included (second argument is path to asset)
        for asset_name, _path in tree.parse(tree_text.splitlines()):
            # we don't have clusters yet so we'll just set it to "Unknown"
            assets.append(
                Asset(
                    asset_type=asset_type,
                    name=asset_name,
                    cluster='Unknown',
                    files_to_scan=asset_get_scannable_files(
                        asset_type, asset_name, project_root
                    ),
                )
            )

    # you might want to inspect the resulting array to check for
    #  any inconsistencies
    print(f'Discovered {len(assets)} total assets.')


if __name__ == '__main__':
    main()
