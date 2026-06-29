#!/usr/bin/env python3
"""
Unified module for loading and discovering data manifests.

Provides shared helpers for CI scripts:
- find_all_manifests() — discover manifest.yaml under examples/
- load_manifest() — load and parse YAML with caching
- load_avro_schema() — load an .avsc file

Removes the duplicated find_all_manifests in validate_manifest.py,
validate_governance.py, validate_quality_rules.py.
"""

import json
from pathlib import Path
from typing import Any

import yaml

__all__ = [
    "ManifestLoader",
    "find_all_manifests",
    "load_manifest",
    "load_avro_schema",
]


class ManifestLoader:
    """Manifest loader with caching.

    To cache across calls, create an instance explicitly.
    The module-level functions (find_all_manifests, load_manifest,
    load_avro_schema) create a fresh instance on each call and do not cache.

    Args:
        base_path: Project root directory (contains examples/).
    """

    def __init__(self, base_path: Path = Path(".")) -> None:
        self.base_path = base_path
        self._cache: dict[Path, dict[str, Any]] = {}

    def find_all_manifests(self, domain: str | None = None) -> list[Path]:
        """Find all manifest.yaml files.

        Looks inside an ``examples/`` subdirectory of base_path. If that
        subdirectory is absent (the typical user repository), manifests are
        searched directly under base_path, so ``--base-path`` can point at
        your own manifests directory.

        Args:
            domain: Filter by domain (e.g. 'sales'). None means all domains.

        Returns:
            Sorted list of paths to manifest.yaml files.
        """
        root = self.base_path / "examples"
        if not root.exists():
            root = self.base_path
        search_path = root / domain if domain else root
        if not search_path.exists():
            return []
        return sorted(search_path.rglob("manifest.yaml"))

    def load_manifest(self, path: Path) -> dict[str, Any]:
        """Load and parse a YAML manifest with caching.

        Args:
            path: Path to manifest.yaml.

        Returns:
            Parsed manifest dictionary.

        Raises:
            FileNotFoundError: File not found.
            yaml.YAMLError: Invalid YAML.
        """
        resolved = path.resolve()
        if resolved in self._cache:
            return self._cache[resolved]

        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if data is None:
            data = {}

        self._cache[resolved] = data
        return data

    def load_avro_schema(self, avsc_path: Path) -> dict[str, Any]:
        """Load an Avro schema (.avsc file).

        Args:
            avsc_path: Path to the .avsc file.

        Returns:
            Parsed JSON dictionary of the Avro schema.

        Raises:
            FileNotFoundError: File not found.
            json.JSONDecodeError: Invalid JSON.
        """
        with open(avsc_path, encoding="utf-8") as f:
            return json.load(f)

    def clear_cache(self) -> None:
        """Clear the cache of loaded manifests."""
        self._cache.clear()


# ═══════════════════════════════════════════════════════════════════════════
# Module-level functions (convenient API without instantiation)
# ═══════════════════════════════════════════════════════════════════════════


def find_all_manifests(
    base_path: Path = Path("."), domain: str | None = None
) -> list[Path]:
    """Find all manifest.yaml files under examples/.

    Args:
        base_path: Project root directory.
        domain: Filter by domain (e.g. 'sales'). None means all domains.

    Returns:
        Sorted list of paths to manifest.yaml.
    """
    loader = ManifestLoader(base_path=base_path)
    return loader.find_all_manifests(domain=domain)


def load_manifest(path: Path) -> dict[str, Any]:
    """Load and parse a YAML manifest.

    No caching. For caching, use ManifestLoader directly.

    Args:
        path: Path to manifest.yaml.

    Returns:
        Parsed manifest dictionary.

    Raises:
        FileNotFoundError: File not found.
        yaml.YAMLError: Invalid YAML.
    """
    loader = ManifestLoader()
    return loader.load_manifest(path)


def load_avro_schema(avsc_path: Path) -> dict[str, Any]:
    """Load an Avro schema (.avsc file).

    Args:
        avsc_path: Path to the .avsc file.

    Returns:
        Parsed JSON dictionary of the Avro schema.

    Raises:
        FileNotFoundError: File not found.
        json.JSONDecodeError: Invalid JSON.
    """
    loader = ManifestLoader()
    return loader.load_avro_schema(avsc_path)
