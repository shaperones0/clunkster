"""Main pipeline, together with examples."""

import json
from dataclasses import dataclass
from pathlib import Path

from ahocorasick import Automaton  # ty: ignore[unresolved-import]

from clunkster.analyze import scan_dep as my_analyze_scan_dep
from clunkster.asset import AssetType
from clunkster.parse import tree as my_parse_tree

# --- COG_START: CLUSTERABLE_ASSETS ---
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
# --- COG_END: CLUSTERABLE_ASSETS ---

# those are used in starting examples
# --- COG_START: CLUSTERABLE_BUILTINS ---
CLUSTERABLE_BUILTINS: tuple[AssetType, ...] = (
    AssetType.SPRITE,
    AssetType.BACKGROUND,
    AssetType.SOUND,
    AssetType.PATH,
    AssetType.SCRIPT,
    AssetType.FONT,
    AssetType.OBJECT,
    AssetType.ROOM,
)
# --- COG_END: CLUSTERABLE_BUILTINS ---

# --- COG_START: CLUSTERABLE_EXTERNALS ---
CLUSTERABLE_EXTERNALS: tuple[AssetType, ...] = (
    AssetType.DATA_SFX,
    AssetType.DATA_MUSIC,
)
# --- COG_END: CLUSTERABLE_EXTERNALS ---

# --- COG_START: ALIAS ---
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
# --- COG_END: ALIAS ---

# --- COG_START: PROJECT ---
PROJECT = Path('path/to/the/project')
# --- COG_END: PROJECT ---


# --- COG_START: CLS_ASSET ---
@dataclass
class Asset:
    """Simple asset definition."""

    asset_type: AssetType
    name: str
    cluster: str
    files_to_scan: tuple[Path, ...]


# --- COG_END: CLS_ASSET ---


def main_ex_start() -> None:
    """First, we want to check that builtin assets get scanned correctly."""
    # --- COG_START: MAIN_EX_START ---

    assets: list[Asset] = []

    for asset_type in CLUSTERABLE_BUILTINS:
        # get project directory for the given asset type
        asset_dir = PROJECT / asset_type.get_dir()
        if not asset_dir.exists():
            continue

        # iterate through tree.yyd file of the asset type

        # we use tree.yyd as source of truth for later examples,
        #  however, undesired results happen if tree.yyd has duplicate assets,
        #  which it technically can have
        tree_text = (asset_dir / 'tree.yyd').read_text(encoding='utf-8')

        # parser for tree files is included (second argument is path to asset)
        for asset_name, _path in my_parse_tree.parse(tree_text.splitlines()):
            # we don't have clusters yet so we'll just set it to "Unknown"
            # also skip the scanning part
            assets.append(
                Asset(
                    asset_type=asset_type,
                    name=asset_name,
                    cluster='Unknown',
                    files_to_scan=tuple(
                        asset_type.get_scannables(asset_name, PROJECT)
                    ),
                )
            )

    # you should investigate the resulting array for inconsistencies
    print(f'Discovered {len(assets)} total assets.')
    # --- COG_END: MAIN_EX_START ---


def main_ex_start_externals() -> None:
    """Populate assets with externals.

    Some projects make use of external assets, such as for gm82snd.
    In case of gm82snd, I have hardcoded it to look for music in ``data/music``
    and for sounds in ``data/sounds``.
    """
    assets: list[Asset] = []

    for asset_type in CLUSTERABLE_BUILTINS:
        asset_dir = PROJECT / asset_type.get_dir()
        if not asset_dir.exists():
            continue

        tree_text = (asset_dir / 'tree.yyd').read_text(encoding='utf-8')
        for asset_name, _path in my_parse_tree.parse(tree_text.splitlines()):
            assets.append(
                Asset(
                    asset_type=asset_type,
                    name=asset_name,
                    cluster='Unknown',
                    files_to_scan=tuple(
                        asset_type.get_scannables(asset_name, PROJECT)
                    ),
                )
            )

    # --- COG_START: MAIN_EX_START_EXTERNALS_GIST ---
    # ...

    # add external data
    for asset_type in CLUSTERABLE_EXTERNALS:
        # you may want to manually map dir names if you don't use
        #  data/sounds for sfx and data/music for bgm
        asset_dir = PROJECT / asset_type.get_dir()
        if not asset_dir.exists():
            continue

        # you may also want to set up a better glob filter here
        for file in asset_dir.rglob('*'):
            if not file.is_file():
                continue

            # gm82snd references sounds by their file stems as strings
            asset_name = f'"{file.stem}"'
            assets.append(
                Asset(
                    asset_type=asset_type,
                    name=asset_name,
                    cluster='Unknown',
                    files_to_scan=tuple(
                        asset_type.get_scannables(asset_name, PROJECT)
                    ),
                )
            )

    # again, investigate the resulting array for inconsistencies
    print(f'Discovered {len(assets)} total assets.')
    # --- COG_END: MAIN_EX_START_EXTERNALS_GIST ---


def main_ex_clusters() -> None:
    """Autogenerate clusters for the assets.

    Now that assets discovering works, we may generate clusters.
    """
    # --- COG_START: MAIN_EX_CLUSTERS ---
    assets: list[Asset] = []

    # cluster -> its assets
    cluster_map: dict[str, list[str]] = {}
    # asset type -> found clusters (useful for initial cleanup)
    asset_to_cluster: dict[AssetType, list[str]] = {}
    for asset_type in CLUSTERABLE_ASSETS:
        # we merge logic for both builtins and externals into one loop
        asset_dir = PROJECT / asset_type.get_dir()
        if not asset_dir.exists():
            continue

        # fill in set of clusters associated with this asset type
        cluster_set: set[str] = set()
        # create asset iterator (asset_name, folder path)
        if asset_type.is_builtin():
            tree_text = (asset_dir / 'tree.yyd').read_text(encoding='utf-8')
            asset_iter = my_parse_tree.parse(tree_text.splitlines())
        else:
            asset_iter = (
                (f'"{file.stem}"', file.relative_to(asset_dir).parts[:-1])
                for file in asset_dir.rglob('*')
                if file.is_file()
            )

        # iterate them assets
        for asset_name, path in asset_iter:
            # use base folder as cluster name
            cluster_name = path[0] if path else 'Common'
            cluster_set.add(cluster_name)
            cluster_map.setdefault(cluster_name, []).append(asset_name)

            assets.append(
                Asset(
                    asset_type=asset_type,
                    name=asset_name,
                    cluster=cluster_name,
                    files_to_scan=tuple(
                        asset_type.get_scannables(asset_name, PROJECT)
                    ),
                )
            )
        asset_to_cluster[asset_type] = list(cluster_set)

    # print the asset type to cluster table
    # (helps to find duplicates)
    clusters_all = sorted(
        {name for clusters in asset_to_cluster.values() for name in clusters}
    )
    print('All clusters:', *clusters_all)
    for asset_type, clusters in asset_to_cluster.items():
        cluster_set = set(clusters)
        row = [
            col if col in cluster_set else ' ' * len(col)
            for col in clusters_all
        ]
        print(f'{asset_type.get_dir(): >12}:', '|'.join(row))

    # MD: There's a chance of duplicates in result. Also, some of those
    # MD: "clusters" (like Backgrounds, or World, etc.) should be a part of
    # MD: Common cluster.
    # --- COG_END: MAIN_EX_CLUSTERS ---


def stage_discover_assets() -> list[Asset]:
    """Asset discovery pipeline stage.

    :return: List of found assets.
    """
    assets: list[Asset] = []

    # --- COG_START: MAIN_EX_ALIAS_GIST_INVERT ---
    # invert ALIAS
    cluster_to_name: dict[str, str] = {}
    for name, clusters in ALIAS.items():
        for cluster in clusters:
            if cluster in cluster_to_name:
                raise ValueError('Invalid ALIAS (duplicate aliases)')
            cluster_to_name[cluster] = name
    # --- COG_END: MAIN_EX_ALIAS_GIST_INVERT ---

    for asset_type in CLUSTERABLE_ASSETS:
        asset_dir = PROJECT / asset_type.get_dir()
        if not asset_dir.exists():
            continue

        if asset_type.is_builtin():
            tree_text = (asset_dir / 'tree.yyd').read_text(encoding='utf-8')
            asset_iter = my_parse_tree.parse(tree_text.splitlines())
        else:
            asset_iter = (
                (f'"{file.stem}"', file.relative_to(asset_dir).parts[:-1])
                for file in asset_dir.rglob('*')
                if file.is_file()
            )

        for asset_name, path in asset_iter:
            # --- COG_START: MAIN_EX_ALIAS_GIST_ALIAS ---
            # MD: Then we apply aliasing in the asset iteration loop.
            cluster_name = path[0] if path else 'Common'
            # replace clusters with aliases
            if cluster_name in cluster_to_name:
                cluster_name = cluster_to_name[cluster_name]
            # MD: Keep using the table thing until all aliases are gone.
            # --- COG_END: MAIN_EX_ALIAS_GIST_ALIAS ---

            assets.append(
                Asset(
                    asset_type=asset_type,
                    name=asset_name,
                    cluster=cluster_name,
                    files_to_scan=tuple(
                        asset_type.get_scannables(asset_name, PROJECT)
                    ),
                )
            )
    return assets


def main_ex_aliases() -> None:
    """Manually fix inconsistencies in cluster map.

    After we did initial scan, you may encounter inconsistencies like different
    clusters ``"StageA"`` and ``"stage_a"`` (project didn't follow strict
    naming), as well as a bunch of things that should belong to Common cluster
    (Backgrounds, Game, etc.).

    Which is easily fixed by a simple alias system for clusters.
    """
    # see stage_discover_assets


def main_ex_scan_sync(assets: list[Asset]) -> None:
    """Simple scanner.

    Before running dependency builder we need to set up scanning
    for the actual dependencies.

    We compile Aho-Corasick automaton to quickly scan every text
    (script or metadata file) in the project for asset references.

    This is a simple synchronous code, but in real projects scanning
    might take up 5-10 seconds.

    Multiprocessing version is available in later examples.
    """
    # --- COG_START: MAIN_EX_SCAN_SYNC ---
    automaton = Automaton()
    for asset in assets:
        automaton.add_word(asset.name, asset.name)
    automaton.make_automaton()

    total_matches = 0
    for asset in assets:
        for file_path in asset.files_to_scan:
            matches: list[my_analyze_scan_dep.DependencyMatch] = list(
                my_analyze_scan_dep.scan(
                    automaton, file_path.read_text(encoding='utf-8')
                )
            )

            total_matches += len(matches)

            # print the first few matches just to prove it works
            if total_matches > 100:  # noqa: PLR2004
                continue
            for match in matches[:3]:
                loc = match.location
                print(
                    f'[{asset.name}] -> {match.target_asset} '
                    f'({file_path.name}:{loc.loc_line}:{loc.loc_column})'
                )

    print(f'\nDone! Found {total_matches} total dependency references.')
    # --- COG_END: MAIN_EX_SCAN_SYNC ---


def _run_tutorials() -> None:
    main_ex_start()
    main_ex_start_externals()
    main_ex_clusters()
    main_ex_aliases()

    assets = stage_discover_assets()
    main_ex_scan_sync(assets)


def test_tutorials() -> None:
    """Ensure the tutorial snippets don't rot."""
    global PROJECT
    dummy_proj = Path(__file__).parent / 'tests' / 'dummy_project'
    if not dummy_proj.exists():
        return  # skip if dummy project isn't set up yet
    PROJECT = dummy_proj

    # TODO dummy config and dummy aliases

    _run_tutorials()


def main() -> None:
    """Pipeline entrypoint."""
    assets = stage_discover_assets()

    main_ex_scan_sync(assets)


if __name__ == '__main__':
    import sys

    _file_private_config = Path('input/config.json')
    if not _file_private_config.exists():
        raise FileNotFoundError(
            f'Config file not found: {_file_private_config}'
        )

    _private_config = json.loads(
        _file_private_config.read_text(encoding='utf-8')
    )
    PROJECT = Path(_private_config['project'])

    _file_private_alias = Path('input/alias.json')
    if _file_private_alias.exists():
        ALIAS = json.loads(_file_private_alias.read_text(encoding='utf-8'))

    # allow testing tutorials on private data as well
    is_test = False
    if len(sys.argv) > 1 and sys.argv[1] == 'test':
        is_test = True

    if is_test:
        _run_tutorials()
    else:
        main()
