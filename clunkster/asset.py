"""Abstract asset type and builtin definitions."""

import collections.abc as col
import pathlib as pl
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Self

from clunkster.parse import index as my_parse_index
from clunkster.parse import kv as my_parse_kv
from clunkster.parse import tree as my_parse_tree


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
class Asset(ABC):
    """Abstract asset."""

    name: str
    cluster: str

    @classmethod
    @abstractmethod
    def _type_name(cls) -> str:
        """Get internal name of this asset."""

    @classmethod
    def type_name(cls) -> str:
        """Type name getter."""
        return cls._type_name()

    @classmethod
    @abstractmethod
    def type_is_used(cls, project_root: pl.Path) -> bool:
        """Check whether this asset type is used in the project or not."""

    @classmethod
    @abstractmethod
    def type_iter_clusters(
        cls, project_root: pl.Path
    ) -> col.Iterator[tuple[str, str]]:
        """Iterate assets of this type and suggest a cluster for each.

        :param project_root: Project's root directory.
        :return: Iterator of (asset_name, suggested_cluster).
        """

    @classmethod
    @abstractmethod
    def type_iter(cls, project_root: pl.Path) -> col.Iterator[Self]:
        """Iterate assets of this type with suggested clusters.

        :param project_root: Project's root directory.
        :return: Iterator of discovered assets.
        """

    @classmethod
    def type_iter_names(cls, project_root: pl.Path) -> col.Iterator[str]:
        """Iterate raw asset names of this type."""
        return (name for name, _ in cls.type_iter_clusters(project_root))

    @abstractmethod
    def get_scannables(self, project_root: pl.Path) -> col.Iterator[pl.Path]:
        """Get paths of scannable .gml or .txt files in this asset type.

        Must fetch all text files which might include references to
        other assets.
        :param project_root: Project's root directory.
        :return: Iterator of scannable paths.
        """

    @abstractmethod
    def get_tree_path(self) -> tuple[str, ...]:
        """Get this asset's tree path for use in sorting or output."""

    @classmethod
    def type_to_str_linter(cls) -> str:
        """Descriptive asset repr to be used in linters."""
        return f'[{cls._type_name():^10}]'

    def to_str_linter(self) -> str:
        """Descriptive asset type repr to be used in linters."""
        return (
            f'[{type(self)._type_name():^10}]: '  # noqa: SLF001
            f'{"/".join(self.get_tree_path())}'
            f'/{self.name}'
        )


@dataclass(frozen=True, slots=True)
class AssetBuiltin(Asset, ABC):
    """Builtin asset."""

    tree_path: tuple[str, ...]

    @classmethod
    @abstractmethod
    def _type_get_dir_rel(cls) -> pl.Path:
        """Get directory of this asset type relative to project root."""

    @classmethod
    def type_get_dir_rel(cls) -> pl.Path:
        """Type's relative directory getter."""
        return cls._type_get_dir_rel()

    @classmethod
    def type_get_dir(cls, project_root: pl.Path) -> pl.Path:
        """Get directory of this asset type.

        :param project_root: Project's root directory.
        :return: pl.Path to directory of this asset type.
        """
        return project_root / cls._type_get_dir_rel()

    @classmethod
    def type_is_used(cls, project_root: pl.Path) -> bool:
        """Check whether this asset is used in the project or not."""
        return cls.type_get_dir(project_root).exists()

    @classmethod
    def _iter_tree(
        cls, project_root: pl.Path
    ) -> col.Iterator[my_parse_tree.TreeEntry]:
        """Iterate over this asset's tree structure.

        :param project_root: Project's root directory.
        :return: Iterator of (asset_name, tree_path);
          asset name is not appended to tree path.
        """
        tree_text = (cls.type_get_dir(project_root) / 'tree.yyd').read_text(
            encoding='utf-8'
        )
        return my_parse_tree.parse(tree_text.splitlines())

    @classmethod
    def type_iter_clusters(
        cls, project_root: pl.Path
    ) -> col.Iterator[tuple[str, str]]:
        """Discover and iterate assets with autosuggested clusters.

        :param project_root: Project's root directory.
        :return: Iterator of (asset_name, suggested_cluster)
        """
        return (
            (asset_name, path[0] if path else 'Common')
            for asset_name, path in cls._iter_tree(project_root)
        )

    @classmethod
    def type_iter(cls, project_root: pl.Path) -> col.Iterator[Self]:
        """Discover assets of this type.

        :param project_root: Project's root.
        :return: Iterator of discovered assets.
        """
        return (
            cls(
                name=name,
                cluster=path[0] if path else 'Common',
                tree_path=path,
            )
            for name, path in cls._iter_tree(project_root)
        )

    @classmethod
    def type_iter_names(cls, project_root: pl.Path) -> col.Iterator[str]:
        """Iterate raw asset names of this type."""
        return (name for name, _ in cls._iter_tree(project_root))

    @classmethod
    def type_file_tree(cls, project_root: pl.Path) -> pl.Path:
        """Get tree.yyd for this asset type."""
        return cls.type_get_dir(project_root) / 'tree.yyd'

    @classmethod
    def type_file_index(cls, project_root: pl.Path) -> pl.Path:
        """Get index.yyd for this asset type."""
        return cls.type_get_dir(project_root) / 'index.yyd'

    @classmethod
    def type_iter_index(cls, project_root: pl.Path) -> col.Iterator[str]:
        """Iterate over entries in index.yyd file of this asset type."""
        return my_parse_index.parse_skimmed(
            cls.type_file_index(project_root).read_text().splitlines()
        )

    def get_tree_path(self) -> tuple[str, ...]:
        """Get this asset's tree path for use in sorting or output."""
        return self.tree_path

    def get_scannables(self, project_root: pl.Path) -> col.Iterator[pl.Path]:
        """Get this asset's scannable files.

        Most builtin assets don't have scannable files.

        :param project_root: Project's root directory.
        :return: Iterator of scannable files.
        """
        yield from ()


@dataclass(frozen=True, slots=True)
class AssetExt(Asset, ABC):
    """Abstract external asset."""

    file: pl.Path
    dir_path: tuple[str, ...]

    @classmethod
    @abstractmethod
    def _type_get_dir_rel(cls) -> pl.Path:
        """Get directory of this asset type relative to project root."""

    @classmethod
    def type_get_dir_rel(cls) -> pl.Path:
        """Type's relative directory getter."""
        return cls._type_get_dir_rel()

    @classmethod
    def type_get_dir(cls, project_root: pl.Path) -> pl.Path:
        """Get directory of this asset type.

        :param project_root: Project's root directory.
        :return: pl.Path to directory of this asset type.
        """
        return project_root / cls._type_get_dir_rel()

    @classmethod
    def type_is_used(cls, project_root: pl.Path) -> bool:
        """Whether this asset type is used in the project."""
        return cls.type_get_dir(project_root).exists()

    @classmethod
    def _iter_dirs(
        cls, project_root: pl.Path
    ) -> col.Iterator[tuple[pl.Path, my_parse_tree.TreeEntry]]:
        """Iterate external asset's directory structure.

        :param project_root: Project's root directory.
        :return: Iterator of (asset_name, tree_path);
          asset name is not appended to tree path.
        """
        asset_dir = cls.type_get_dir(project_root)
        return (
            (file, (f'"{file.stem}"', file.relative_to(asset_dir).parts[:-1]))
            for file in asset_dir.rglob('*')
            if file.is_file()
        )

    @classmethod
    def type_iter_clusters(
        cls, project_root: pl.Path
    ) -> col.Iterator[tuple[str, str]]:
        """Discover assets and suggest clusters.

        :param project_root: Project's root directory.
        :return: Iterator of (asset_name, suggested_cluster)
        """
        return (
            (asset_name, path[0] if path else 'Common')
            for _, (asset_name, path) in cls._iter_dirs(project_root)
        )

    @classmethod
    def type_iter(cls, project_root: pl.Path) -> col.Iterator[Self]:
        """Discover assets of this type."""
        return (
            cls(
                name=asset_name,
                cluster=path[0] if path else 'Common',
                dir_path=path,
                file=file,
            )
            for file, (asset_name, path) in cls._iter_dirs(project_root)
        )

    @classmethod
    def type_iter_names(cls, project_root: pl.Path) -> col.Iterator[str]:
        """Iterate raw asset names of this type."""
        return (name for _, (name, _) in cls._iter_dirs(project_root))

    def get_tree_path(self) -> tuple[str, ...]:
        """Get this asset's tree path for use in sorting or output."""
        return self.dir_path

    def get_scannables(self, project_root: pl.Path) -> col.Iterator[pl.Path]:
        """Get scannable files of this asset.

        Most external assets don't provide scannable files.
        :param project_root: Project's root directory.
        :return: Iterator of found scannable files.
        """
        yield from ()


@dataclass(frozen=True, slots=True)
class Background(AssetBuiltin):
    """GameMaker Background asset."""

    @classmethod
    def _type_name(cls) -> str:
        return 'BACKGROUND'

    @classmethod
    def _type_get_dir_rel(cls) -> pl.Path:
        return pl.Path('backgrounds')

    def get_background_metadata(
        self, project_root: pl.Path
    ) -> BackgroundMetadata:
        """Get background's metadata."""
        file = type(self).type_get_dir(project_root) / f'{self.name}.txt'
        with file.open('r', encoding='utf-8') as f:
            return my_parse_kv.parse_dataclass(BackgroundMetadata, f)

    def get_background_image(self, project_root: pl.Path) -> pl.Path:
        """Get background's image."""
        file = type(self).type_get_dir(project_root) / f'{self.name}.png'
        assert file.is_file()
        return file


@dataclass(frozen=True, slots=True)
class Sound(AssetBuiltin):
    """GameMaker Sound asset."""

    @classmethod
    def _type_name(cls) -> str:
        return 'SOUND'

    @classmethod
    def _type_get_dir_rel(cls) -> pl.Path:
        return pl.Path('sounds')


@dataclass(frozen=True, slots=True)
class Font(AssetBuiltin):
    """GameMaker Font asset."""

    @classmethod
    def _type_name(cls) -> str:
        return 'FONT'

    @classmethod
    def _type_get_dir_rel(cls) -> pl.Path:
        return pl.Path('fonts')


@dataclass(frozen=True, slots=True)
class Object(AssetBuiltin):
    """GameMaker Object asset."""

    @classmethod
    def _type_name(cls) -> str:
        return 'OBJECT'

    @classmethod
    def _type_get_dir_rel(cls) -> pl.Path:
        return pl.Path('objects')

    def get_scannables(self, project_root: pl.Path) -> col.Iterator[pl.Path]:
        """Get scannable files of this object.

        Returns metadata file (.txt) and code file (.gml).
        :param project_root: Project's root directory.
        :return: Iterator of scannable files.
        """
        asset_dir = type(self).type_get_dir(project_root)
        file_meta = asset_dir / f'{self.name}.txt'
        file_gml = asset_dir / f'{self.name}.gml'
        yield file_meta
        yield file_gml  # both guaranteed to exist


@dataclass(frozen=True, slots=True)
class Path(AssetBuiltin):
    """GameMaker Path asset."""

    @classmethod
    def _type_name(cls) -> str:
        return 'PATH'

    @classmethod
    def _type_get_dir_rel(cls) -> pl.Path:
        return pl.Path('paths')


@dataclass(frozen=True, slots=True)
class Room(AssetBuiltin):
    """GameMaker Room asset."""

    @classmethod
    def _type_name(cls) -> str:
        return 'ROOM'

    @classmethod
    def _type_get_dir_rel(cls) -> pl.Path:
        return pl.Path('rooms')

    def get_scannables(self, project_root: pl.Path) -> col.Iterator[pl.Path]:
        """Get this room's scannable files.

        Since rooms usually have a lot of files, this iterator
        returns globs for .txt files (layers.txt, instances.txt,
        room.txt metadata, etc.) and .gml files (instance creation code,
        room creation code).
        :param project_root: Project's root directory.
        :return: Iterator of scannable files.
        """
        dir_room = type(self).type_get_dir(project_root) / self.name
        yield from dir_room.glob('*.txt')
        yield from dir_room.glob('*.gml')


@dataclass(frozen=True, slots=True)
class Script(AssetBuiltin):
    """GameMaker Script asset."""

    @classmethod
    def _type_name(cls) -> str:
        return 'SCRIPT'

    @classmethod
    def _type_get_dir_rel(cls) -> pl.Path:
        return pl.Path('scripts')

    def get_scannables(self, project_root: pl.Path) -> col.Iterator[pl.Path]:
        """Get scannable files of this script.

        Script's only scannable file is the script itself.
        :param project_root: Project's root directory.
        :return: The iterator of one script file.
        """
        file_gml = type(self).type_get_dir(project_root) / f'{self.name}.gml'
        yield file_gml  # guaranteed to exist


@dataclass(frozen=True, slots=True)
class Sprite(AssetBuiltin):
    """GameMaker Sprite asset."""

    @classmethod
    def _type_name(cls) -> str:
        return 'SPRITE'

    @classmethod
    def _type_get_dir_rel(cls) -> pl.Path:
        return pl.Path('sprites')

    def get_sprite_folder(self, project_root: pl.Path) -> pl.Path:
        """Get sprite's folder with .pngs and .txt metadata."""
        folder = type(self).type_get_dir(project_root) / self.name
        assert folder.is_dir()
        return folder

    def get_sprite_metadata(self, project_root: pl.Path) -> SpriteMetadata:
        """Get sprite's metadata."""
        file = self.get_sprite_folder(project_root) / 'sprite.txt'
        with file.open('r', encoding='utf-8') as f:
            return my_parse_kv.parse_dataclass(SpriteMetadata, f)

    def get_sprite_images(
        self, project_root: pl.Path, frames: int
    ) -> col.Iterator[pl.Path]:
        """Get sprite's images."""
        folder = self.get_sprite_folder(project_root)
        for i in range(frames):
            img = folder / f'{i}.png'
            assert img.is_file()
            yield img
