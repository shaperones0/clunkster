"""Abstract asset type and builtin definitions."""

import collections.abc as col
import itertools as it
import pathlib as pl
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Self, override
import functools as ft

from clunkster.parse import index as my_parse_index
from clunkster.parse import kv as my_parse_kv
from clunkster.parse import tree as my_parse_tree
from clunkster.text import read as my_read


@dataclass(frozen=True, slots=True)
class SpriteMetadata:
    """GameMaker Sprite's metadata from ``sprite.txt``."""

    frames: int
    origin_x: int
    origin_y: int
    collision_shape: int
    alpha_tolerance: int
    per_frame_colliders: int
    bbox_type: int
    bbox_left: int
    bbox_top: int
    bbox_right: int
    bbox_bottom: int


@dataclass(frozen=True, slots=True)
class BackgroundMetadata:
    """GameMaker Background's metadata from ``<background_name>.txt``."""

    exists: int
    tileset: int
    tile_width: int
    tile_height: int
    tile_hoffset: int
    tile_voffset: int
    tile_hsep: int
    tile_vsep: int


@dataclass(frozen=True, slots=True)
class ObjectMetadata:
    """GameMaker Object's metadata from ``<object_name>.txt``."""

    sprite: str
    visible: int
    solid: int
    persistent: int
    depth: int
    parent: str
    mask: str


@dataclass(frozen=True, slots=True)
class RoomMetadata:
    """GameMaker Room's metadata from ``room.txt``."""

    # general
    caption: str
    width: int
    height: int
    snap_x: int
    snap_y: int
    isometric: int
    roomspeed: int
    roompersistent: int
    bg_color: int
    clear_screen: int
    clear_view: int

    # bgs
    bg_visible0: int
    bg_is_foreground0: int
    bg_source0: str
    bg_xoffset0: int
    bg_yoffset0: int
    bg_tile_h0: int
    bg_tile_v0: int
    bg_hspeed0: int
    bg_vspeed0: int
    bg_stretch0: int

    bg_visible1: int
    bg_is_foreground1: int
    bg_source1: str
    bg_xoffset1: int
    bg_yoffset1: int
    bg_tile_h1: int
    bg_tile_v1: int
    bg_hspeed1: int
    bg_vspeed1: int
    bg_stretch1: int

    bg_visible2: int
    bg_is_foreground2: int
    bg_source2: str
    bg_xoffset2: int
    bg_yoffset2: int
    bg_tile_h2: int
    bg_tile_v2: int
    bg_hspeed2: int
    bg_vspeed2: int
    bg_stretch2: int

    bg_visible3: int
    bg_is_foreground3: int
    bg_source3: str
    bg_xoffset3: int
    bg_yoffset3: int
    bg_tile_h3: int
    bg_tile_v3: int
    bg_hspeed3: int
    bg_vspeed3: int
    bg_stretch3: int

    bg_visible4: int
    bg_is_foreground4: int
    bg_source4: str
    bg_xoffset4: int
    bg_yoffset4: int
    bg_tile_h4: int
    bg_tile_v4: int
    bg_hspeed4: int
    bg_vspeed4: int
    bg_stretch4: int

    bg_visible5: int
    bg_is_foreground5: int
    bg_source5: str
    bg_xoffset5: int
    bg_yoffset5: int
    bg_tile_h5: int
    bg_tile_v5: int
    bg_hspeed5: int
    bg_vspeed5: int
    bg_stretch5: int

    bg_visible6: int
    bg_is_foreground6: int
    bg_source6: str
    bg_xoffset6: int
    bg_yoffset6: int
    bg_tile_h6: int
    bg_tile_v6: int
    bg_hspeed6: int
    bg_vspeed6: int
    bg_stretch6: int

    bg_visible7: int
    bg_is_foreground7: int
    bg_source7: str
    bg_xoffset7: int
    bg_yoffset7: int
    bg_tile_h7: int
    bg_tile_v7: int
    bg_hspeed7: int
    bg_vspeed7: int
    bg_stretch7: int

    # views
    views_enabled: int

    view_visible0: int
    view_xview0: int
    view_yview0: int
    view_wview0: int
    view_hview0: int
    view_xport0: int
    view_yport0: int
    view_wport0: int
    view_hport0: int
    view_fol_hbord0: int
    view_fol_vbord0: int
    view_fol_hspeed0: int
    view_fol_vspeed0: int
    view_fol_target0: str

    view_visible1: int
    view_xview1: int
    view_yview1: int
    view_wview1: int
    view_hview1: int
    view_xport1: int
    view_yport1: int
    view_wport1: int
    view_hport1: int
    view_fol_hbord1: int
    view_fol_vbord1: int
    view_fol_hspeed1: int
    view_fol_vspeed1: int
    view_fol_target1: str

    view_visible2: int
    view_xview2: int
    view_yview2: int
    view_wview2: int
    view_hview2: int
    view_xport2: int
    view_yport2: int
    view_wport2: int
    view_hport2: int
    view_fol_hbord2: int
    view_fol_vbord2: int
    view_fol_hspeed2: int
    view_fol_vspeed2: int
    view_fol_target2: str

    view_visible3: int
    view_xview3: int
    view_yview3: int
    view_wview3: int
    view_hview3: int
    view_xport3: int
    view_yport3: int
    view_wport3: int
    view_hport3: int
    view_fol_hbord3: int
    view_fol_vbord3: int
    view_fol_hspeed3: int
    view_fol_vspeed3: int
    view_fol_target3: str

    view_visible4: int
    view_xview4: int
    view_yview4: int
    view_wview4: int
    view_hview4: int
    view_xport4: int
    view_yport4: int
    view_wport4: int
    view_hport4: int
    view_fol_hbord4: int
    view_fol_vbord4: int
    view_fol_hspeed4: int
    view_fol_vspeed4: int
    view_fol_target4: str

    view_visible5: int
    view_xview5: int
    view_yview5: int
    view_wview5: int
    view_hview5: int
    view_xport5: int
    view_yport5: int
    view_wport5: int
    view_hport5: int
    view_fol_hbord5: int
    view_fol_vbord5: int
    view_fol_hspeed5: int
    view_fol_vspeed5: int
    view_fol_target5: str

    view_visible6: int
    view_xview6: int
    view_yview6: int
    view_wview6: int
    view_hview6: int
    view_xport6: int
    view_yport6: int
    view_wport6: int
    view_hport6: int
    view_fol_hbord6: int
    view_fol_vbord6: int
    view_fol_hspeed6: int
    view_fol_vspeed6: int
    view_fol_target6: str

    view_visible7: int
    view_xview7: int
    view_yview7: int
    view_wview7: int
    view_hview7: int
    view_xport7: int
    view_yport7: int
    view_wport7: int
    view_hport7: int
    view_fol_hbord7: int
    view_fol_vbord7: int
    view_fol_hspeed7: int
    view_fol_vspeed7: int
    view_fol_target7: str

    # ide
    remember: int
    editor_width: int
    editor_height: int
    show_grid: int
    show_objects: int
    show_tiles: int
    show_backgrounds: int
    show_foregrounds: int
    show_views: int
    delete_underlying_objects: int
    delete_underlying_tiles: int
    tab: int
    editor_x: int
    editor_y: int


@dataclass(frozen=True, slots=True)
class Asset(ABC):
    """Abstract asset."""

    # name is the identifier by which the asset is referenced in GML code;
    #  it is also used as a primary key of the asset, so unique assets
    #  must have unique names
    name: str

    @classmethod
    @abstractmethod
    def type_name(cls) -> str:
        """Internal name of this asset type."""


    @classmethod
    @abstractmethod
    def type_is_used(cls, project_root: pl.Path) -> bool:
        """Check whether this asset type is used in the project or not."""

    @classmethod
    @abstractmethod
    def type_discover_all(cls, project_root: pl.Path) -> col.Iterator[Self]:
        """Iterate through assets of this type."""

    @classmethod
    def type_discover_names(cls, project_root: pl.Path) -> col.Iterator[str]:
        """Iterate through asset names of this type.

        Default implementation uses ``type_discover_all``, however, for
        things like builtin should use ``index.yyd`` files.
        """
        return (asset.name for asset in cls.type_discover_all(project_root))



@dataclass(frozen=True, slots=True)
class AssetHasPath(Asset, ABC):
    """Asset mixin: asset has a tree-like path."""

    tree_path: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AssetHasDir(Asset, ABC):
    """Asset mixin: type has a file directory in the project.

    Existence of this asset type in the project by presence of its directory.
    """

    @classmethod
    @abstractmethod
    def type_get_dir_rel(cls) -> pl.Path:
        """Get directory of this asset type relative to project root."""

    @classmethod
    def type_get_dir(cls, project_root: pl.Path) -> pl.Path:
        """Get directory of this asset type.

        :param project_root: Project's root directory.
        :return: pl.Path to directory of this asset type.
        """
        return project_root / cls.type_get_dir_rel()

    @override
    @classmethod
    def type_is_used(cls, project_root: pl.Path) -> bool:
        return cls.type_get_dir(project_root).exists()


@dataclass(frozen=True, slots=True)
class AssetBuiltin(AssetHasPath, AssetHasDir, ABC):
    """Abstract builtin asset."""

    @classmethod
    def type_get_tree_file(cls, project_root: pl.Path) -> pl.Path:
        return cls.type_get_dir(project_root) / 'tree.yyd'

    @classmethod
    def type_get_index_file(cls, project_root: pl.Path) -> pl.Path:
        return cls.type_get_dir(project_root) / 'index.yyd'

    @override
    @classmethod
    def type_discover_all(cls, project_root: pl.Path) -> col.Iterator[Self]:
        tree_file = cls.type_get_tree_file(project_root)
        tree_lines = my_read.lines(tree_file)
        return (
            cls(
                name=asset_name,
                tree_path=path
            )
            for asset_name, path in my_parse_tree.parse(tree_lines)
        )

    @override
    @classmethod
    def type_discover_names(cls, project_root: pl.Path) -> col.Iterator[str]:
        index_file = cls.type_get_index_file(project_root)
        index_lines = my_read.lines(index_file)
        return my_parse_index.parse_skimmed(index_lines)


@dataclass(frozen=True, slots=True)
class AssetSingleFile(AssetHasPath, AssetHasDir, ABC):
    """Abstract external asset, represented by a single file."""

    file: pl.Path

    @classmethod
    @abstractmethod
    def type_globs(cls) -> col.Iterable[str]:
        """Get globs of the asset files."""
        return '*'

    @classmethod
    def type_file_to_asset_name(cls, file: pl.Path) -> str:
        """Convert file path to asset name.

        Assumes string filename.
        """
        return f'"{file.stem}"'

    @property
    def name_clean(self) -> str:
        return self.name[1:-1]

    @classmethod
    def type_file_to_tree_path(cls, project_root: pl.Path, file: pl.Path) -> tuple[str, ...]:
        """Convert file to path."""
        return file.relative_to(cls.type_get_dir(project_root)).parts[:-1]

    @override
    @classmethod
    def type_discover_all(cls, project_root: pl.Path) -> col.Iterator[Self]:
        asset_dir = cls.type_get_dir(project_root)

        file_iterator: col.Iterable[pl.Path] = it.chain.from_iterable(
            asset_dir.rglob(rglob) for rglob in cls.type_globs()
        )
        return (
            cls(
                name=cls.type_file_to_asset_name(file),
                tree_path=cls.type_file_to_tree_path(project_root, file),
                file=file
            )
            for file in file_iterator
            if file.is_file()
        )


@dataclass(frozen=True, slots=True)
class Background(AssetBuiltin):

    @override
    @classmethod
    def type_name(cls) -> str:
        return 'BACKGROUND'

    @override
    @classmethod
    def type_get_dir_rel(cls) -> pl.Path:
        return pl.Path('backgrounds')

    def get_background_metadata_file(self, project_root: pl.Path) -> pl.Path:
        """Get background's metadata (``.txt``) file."""
        return type(self).type_get_dir(project_root) / f'{self.name}.txt'

    @ft.lru_cache()
    def get_background_metadata(
        self, project_root: pl.Path
    ) -> BackgroundMetadata:
        """Get background's metadata."""
        file = self.get_background_metadata_file(project_root)
        with file.open('r', encoding='utf-8') as f:
            return my_parse_kv.parse_dataclass(BackgroundMetadata, f)

    def get_background_image(self, project_root: pl.Path) -> pl.Path:
        """Get background's image."""
        return type(self).type_get_dir(project_root) / f'{self.name}.png'


@dataclass(frozen=True, slots=True)
class Sound(AssetBuiltin):
    """GameMaker Sound asset."""

    @override
    @classmethod
    def type_name(cls) -> str:
        return 'SOUND'

    @override
    @classmethod
    def type_get_dir_rel(cls) -> pl.Path:
        return pl.Path('sounds')


@dataclass(frozen=True, slots=True)
class Font(AssetBuiltin):
    """GameMaker Font asset."""

    @override
    @classmethod
    def type_name(cls) -> str:
        return 'FONT'

    @override
    @classmethod
    def type_get_dir_rel(cls) -> pl.Path:
        return pl.Path('fonts')


@dataclass(frozen=True, slots=True)
class Object(AssetBuiltin):
    """GameMaker Object asset."""

    @override
    @classmethod
    def type_name(cls) -> str:
        return 'OBJECT'

    @override
    @classmethod
    def type_get_dir_rel(cls) -> pl.Path:
        return pl.Path('objects')

    def get_object_metadata_file(self, project_root: pl.Path) -> pl.Path:
        """Get object's metadata (``.txt``) file."""
        return type(self).type_get_dir(project_root) / f'{self.name}.txt'

    @ft.lru_cache()
    def get_object_metadata(self, project_root: pl.Path) -> ObjectMetadata:
        """Get object's metadata."""
        file = self.get_object_metadata_file(project_root)
        with file.open('r', encoding='utf-8') as f:
            return my_parse_kv.parse_dataclass(ObjectMetadata, f)

    def get_object_gml_file(self, project_root: pl.Path) -> pl.Path:
        """Get object's gml file."""
        return type(self).type_get_dir(project_root) / f'{self.name}.gml'


@dataclass(frozen=True, slots=True)
class Path(AssetBuiltin):
    """GameMaker Path asset."""

    @override
    @classmethod
    def type_name(cls) -> str:
        return 'PATH'

    @override
    @classmethod
    def type_get_dir_rel(cls) -> pl.Path:
        return pl.Path('paths')


@dataclass(frozen=True, slots=True)
class Room(AssetBuiltin):
    """GameMaker Room asset."""

    @override
    @classmethod
    def type_name(cls) -> str:
        return 'ROOM'

    @override
    @classmethod
    def type_get_dir_rel(cls) -> pl.Path:
        return pl.Path('rooms')

    def get_room_folder(self, project_root: pl.Path) -> pl.Path:
        """Get room's folder."""
        return type(self).type_get_dir(project_root) / self.name

    def get_room_metadata_file(self, project_root: pl.Path) -> pl.Path:
        """Get room's metadata (``.txt``) file."""
        return self.get_room_folder(project_root) / 'room.txt'

    @ft.lru_cache()
    def get_room_metadata(self, project_root: pl.Path) -> RoomMetadata:
        """Get room's metadata."""
        file = self.get_room_metadata_file(project_root)
        with file.open('r', encoding='utf-8') as f:
            return my_parse_kv.parse_dataclass(RoomMetadata, f)

    def get_room_gml_file(self, project_root: pl.Path) -> pl.Path:
        """Get room's gml file."""
        return self.get_room_folder(project_root) / 'code.gml'


@dataclass(frozen=True, slots=True)
class Script(AssetBuiltin):
    """GameMaker Script asset."""

    @override
    @classmethod
    def type_name(cls) -> str:
        return 'SCRIPT'

    @override
    @classmethod
    def type_get_dir_rel(cls) -> pl.Path:
        return pl.Path('scripts')

    def get_script_gml_file(self, project_root: pl.Path) -> pl.Path:
        return type(self).type_get_dir(project_root) / f'{self.name}.gml'

@dataclass(frozen=True, slots=True)
class Sprite(AssetBuiltin):
    """GameMaker Sprite asset."""

    @override
    @classmethod
    def type_name(cls) -> str:
        return 'SPRITE'

    @override
    @classmethod
    def type_get_dir_rel(cls) -> pl.Path:
        return pl.Path('sprites')

    def get_sprite_folder(self, project_root: pl.Path) -> pl.Path:
        """Get sprite's folder with .pngs and .txt metadata."""
        return type(self).type_get_dir(project_root) / self.name

    def get_sprite_metadata_file(self, project_root: pl.Path) -> pl.Path:
        """Get sprite's metadata file."""
        return self.get_sprite_folder(project_root) / 'sprite.txt'

    @ft.lru_cache()
    def get_sprite_metadata(self, project_root: pl.Path) -> SpriteMetadata:
        """Get sprite's metadata."""
        file = self.get_sprite_metadata_file(project_root)
        with file.open('r', encoding='utf-8') as f:
            return my_parse_kv.parse_dataclass(SpriteMetadata, f)

    def get_sprite_image(self, project_root: pl.Path, frame: int) -> pl.Path:
        """Get sprite's images."""
        return self.get_sprite_folder(project_root) / f'{frame}.png'
