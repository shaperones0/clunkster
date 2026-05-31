"""Asset shims."""

from enum import Enum, auto
from pathlib import Path


class AssetType(Enum):
    """GameMaker8.2 asset type."""

    BACKGROUND = auto()
    FONT = auto()
    OBJECT = auto()
    PATH = auto()
    ROOM = auto()
    SCRIPT = auto()
    SPRITE = auto()
    SOUND = auto()

    DATA_SFX = auto()
    DATA_MUSIC = auto()


def asset_get_project_dir(asset_type: AssetType) -> str:
    """Get directory name for given asset type.

    :return: Dir name.
    """
    return {
        AssetType.BACKGROUND: 'backgrounds',
        AssetType.FONT: 'fonts',
        AssetType.OBJECT: 'objects',
        AssetType.PATH: 'paths',
        AssetType.ROOM: 'rooms',
        AssetType.SCRIPT: 'scripts',
        AssetType.SPRITE: 'sprites',
        AssetType.SOUND: 'sounds',
        AssetType.DATA_SFX: 'data/sounds',
        AssetType.DATA_MUSIC: 'data/music',
    }[asset_type]


def asset_get_scannable_files(
    asset_type: AssetType, asset_name: str, project_root: Path
) -> tuple[Path, ...]:
    """Get scannable files for given asset type.

    :param asset_type: Asset type.
    :param asset_name: Name of the asset.
    :param project_root: Project root dir.
    :return: List of scannable file paths.
    """
    asset_dir = project_root / asset_get_project_dir(asset_type)
    match asset_type:
        case AssetType.SCRIPT:
            file_gml = asset_dir / f'{asset_name}.gml'
            return (file_gml,)  # must exist

        case AssetType.OBJECT:
            file_meta = asset_dir / f'{asset_name}.txt'
            file_gml = asset_dir / f'{asset_name}.gml'
            return file_meta, file_gml  # both must exist

        case AssetType.ROOM:
            dir_room = asset_dir / asset_name

            return tuple(dir_room.glob('*.txt')) + tuple(
                dir_room.glob('*.gml')
            )

    return ()
