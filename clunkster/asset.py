"""Clunkster models."""

import collections.abc as col
from concurrent import futures
from enum import Enum, auto
from pathlib import Path


def _file_read_single(path_abs: Path) -> str:
    """Read file.

    Brought into a separate function to quickly fix format issues.

    :param path_abs: File path.
    :return: File contents.
    """
    # potentially errors="replace"
    return path_abs.read_text(encoding='utf-8')


class Project:
    """GameMaker8.2 project."""

    def __init__(self, pth_root: Path) -> None:
        """Initialize project.

        :param pth_root: Path to the folder, that contains
          project's ``.gm82`` file.
        """
        self.pth_root = pth_root
        self._cache_file: dict[str, str] = {}

    def read(self, pth_rel: Path) -> str:
        """Read a text file in the project.

        Caches the results indefinitely,
        don't mutate projects before finishing reading.
        :param pth_rel: Path to the file, relative to the project root.
        :return: File contents.
        """
        pth_str = str(pth_rel)
        if pth_str in self._cache_file:
            return self._cache_file[pth_str]
        pth_abs = self.pth_root / pth_str
        text = _file_read_single(pth_abs)
        self._cache_file[pth_str] = text
        return text

    def preload(self, pths_rel: col.Iterable[Path]) -> None:
        """Preload a collection of files.

        Uses ThreadPoolExecutor.
        :param pths_rel: Collection of relative paths to files.
        """
        with futures.ThreadPoolExecutor() as executor:
            for path, content in executor.map(_file_read_single, pths_rel):
                self._cache_file[str(path)] = content


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

    def get_dir(self) -> str:
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
        }[self]


class Asset:
    """GameMaker8.2 asset."""

    tree_path: str
    asset_type: AssetType
