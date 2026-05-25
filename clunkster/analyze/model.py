"""Structs for scan jobs."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ScanTask:
    """Scan task.

    Represents a file to scan.
    """

    file_path: str
    asset_name: str
    gml_text: str


@dataclass(frozen=True, slots=True)
class DependencyEdge:
    """Dependency graph edge.

    Contexts contain all the `if script() { ... }` blocks, guarding
    given dependency.
    """

    source_asset: str
    target_asset: str
    contexts: tuple[str, ...]
