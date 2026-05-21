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
    """GameMaker8.2 asset type.

    =========================================
    Dehydration strategy for each asset type
    =========================================

    Backgrounds: impactful, high priority.

    * dehydrate: TODO find a way to generate .gmbck files
    * store-dry: pink-black checkerboard with transparent padding
    * store-wet: .gmbck files
    * hydrate: use ``background_replace_background`` to load externally

    ____

    Fonts: aren't numerous enough, and difficult.

    ____

    Objects: moderately impactful, but risky (and difficult).

    ____

    Paths: aren't impactful.

    ____

    Room: those are quite impactful, but also pretty risky.

    * dehydrate: read instances.txt, tiles and each object creation code,
      turn them into scripts that add them back in via ``room_instance_add``
      (don't forget their respective globalvars) and ``room_tile_add``,
      generate objects for each room instance creation code to be ran on
      room start.
    * store-dry: blank room with a single stub object (to raise errors).
    * store-wet: aforementioned script and object.
    * hydrate: run the scripts, add the room start object as well.

    ____

    Scripts: impossible to create dynamically.

    ____

    Sprites: impactful, high priority.

    * dehydrate: TODO find a way to generate .gmspr files
    * store-dry: pink-black checkerboard with transparent padding
    * store-wet: .gmspr files
    * hydrate: use ``sprite_replace_sprite`` to load externally

    ____

    Sounds: very impactful, TODO.

    ____

    Data: Sounds and Music: impactful, high priority.

    * dehydrate: iterate through all sounds, put sounds from same cluster-set
      into WASD packs, generate a script that loads every existing sound
      as ``null.wav`` (or ``buzz.wav``) via ``sound_add_ext``,
      generate a script that would load said WASD pack
    * store-dry: those live as ``null.wav`` files.
    * store-wet: WASD pack.
    * hydrate: run the WASD loader script.

    """

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
