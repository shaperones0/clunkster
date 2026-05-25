"""Cluster management."""

import collections.abc as col


def clusterset_group(
    clustersets: dict[str, col.Iterable[str]],
) -> col.Iterator[tuple[tuple[str, ...], tuple[str, ...]]]:
    """Groups clustersets.

    Typically, "clusterset" is a room (which, canonically, can reference
    multiple clusters), so, realistically, input dict would look like this:
    ::
        {
            "roomA1": ["Common", "StageA"],
            "roomA2": ["Common", "StageA"],
            "roomHub": ["Common", "StageA", "StageB"],
        }
    and therefore, output dict for this one would look like this:
    ::
        {
            ("Common", "StageA"): (
                "roomA1",
                "roomA2",
            ),
            ("Common", "StageA", "StageB"): (
                "roomHub"
            )
        }
    :param clustersets: Map of clusterset names to their clusters.
    :return: Iterator of pairs of cluster sets to their clusterset.
    """
    grouped_rooms: dict[frozenset[str], list[str]] = {}
    for room, clusters in clustersets.items():
        cluster_set = frozenset(clusters)
        grouped_rooms.setdefault(cluster_set, []).append(room)
    return (
        (tuple(cluster_set), tuple(rooms))
        for cluster_set, rooms in grouped_rooms.items()
    )
