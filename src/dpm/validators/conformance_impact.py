#!/usr/bin/env python3
"""
List data products that conform to a given canonical entity version.

Before bumping a canonical entity to a new major (or sunsetting an old one),
the entity owner needs to know which products still declare conformance to the
affected version, so they can be notified to migrate. Conformers are declared
in their own manifests (``metadata.conforms_to``), so this is a manifest scan.

Limitation: the result is only as complete as the manifests visible under
``--base-path``. In a multi-repo setup, products live in many domain repos, so
this should run against an aggregated checkout (or a central catalog) to be
exhaustive. With a single repo it covers exactly that repo.

Usage:
    python conformance_impact.py --entity customer --version 1 --base-path .
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml

from dpm.manifest_loader import find_all_manifests

ENTITY_REF_RE = re.compile(r"^(?P<name>[a-z][a-z0-9_]*)@(?P<major>\d+)$")


def conforms_to_entity(manifest: dict[str, Any], entity: str, major: str) -> bool:
    """Return True if the manifest declares conformance to ``entity@major``."""
    conforms_to = manifest.get("metadata", {}).get("conforms_to")
    if not isinstance(conforms_to, list):
        return False
    for entry in conforms_to:
        if not isinstance(entry, dict):
            continue
        match = ENTITY_REF_RE.match(str(entry.get("entity", "")))
        if match and match.group("name") == entity and match.group("major") == major:
            return True
    return False


def find_conformers(base_path: Path, entity: str, major: str) -> list[dict[str, str]]:
    """Find all products conforming to ``entity@major`` under base_path."""
    conformers: list[dict[str, str]] = []
    for manifest_path in find_all_manifests(base_path):
        try:
            with open(manifest_path, encoding="utf-8") as f:
                manifest = yaml.safe_load(f) or {}
        except Exception:
            continue
        if not conforms_to_entity(manifest, entity, major):
            continue
        metadata = manifest.get("metadata", {})
        owner = metadata.get("owner", {})
        conformers.append(
            {
                "manifest": str(manifest_path),
                "name": f"{metadata.get('namespace', '?')}/{metadata.get('name', '?')}",
                "team": owner.get("team", ""),
                "email": owner.get("email", ""),
            }
        )
    return conformers


def main() -> None:
    """Entry point."""
    parser = argparse.ArgumentParser(
        description="List data products conforming to a canonical entity version"
    )
    parser.add_argument("--entity", required=True, help="Canonical entity name (e.g. customer)")
    parser.add_argument("--version", required=True, help="Major version (e.g. 1)")
    parser.add_argument("--base-path", default=".", help="Base path to scan for manifests")
    parser.add_argument("--output", help="Save the JSON report to a file")

    args = parser.parse_args()
    major = str(args.version).split(".")[0]  # tolerate "1" or "1.0.0"

    conformers = find_conformers(Path(args.base_path), args.entity, major)

    print(f"\n{'=' * 60}")
    print(f"Conformers of {args.entity}@{major}: {len(conformers)}")
    print(f"{'=' * 60}")
    for c in conformers:
        contact = c["email"] or c["team"] or "no contact"
        print(f"  - {c['name']}  ({contact})")
        print(f"      {c['manifest']}")
    if not conformers:
        print("  none found in the scanned manifests")

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(
                {"entity": args.entity, "major": major, "conformers": conformers},
                f,
                indent=2,
                ensure_ascii=False,
            )
        print(f"\nJSON report saved to: {args.output}")

    sys.exit(0)


if __name__ == "__main__":
    main()
