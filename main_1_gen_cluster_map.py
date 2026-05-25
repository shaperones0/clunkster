"""Example: Generating an initial Cluster Map.

This script scans the project's tree.yyd files to automatically group
assets into clusters based on their top-level folder in the IDE.
Outputs a Python dictionary that you can edit and copy into later scripts.
"""

import json
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


def main(project_path: str) -> None:
    """Program entry.

    :param project_path: GM82 project path.
    """
    project_root = Path(project_path)
    cluster_map: dict[str, list[str]] = {}

    for asset_type in CLUSTERABLE_ASSETS:
        asset_dir = project_root / asset_type.get_dir()
        if not asset_dir.exists():
            continue

        tree_text = (asset_dir / 'tree.yyd').read_text(encoding='utf-8')
        for asset_name, path in tree.parse(tree_text.splitlines()):
            cluster_name = path[0] if path else 'Common'
            cluster_map.setdefault(cluster_name, []).append(asset_name)

    # json.dumps gives better formatting that pprint
    print(json.dumps(cluster_map, indent=4))


if __name__ == '__main__':
    import sys

    main(sys.argv[1])
