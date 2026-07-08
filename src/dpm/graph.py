#!/usr/bin/env python3
"""
Render the conformance graph: data products <-> canonical entities.

DPM models exactly one cross-artifact relationship — a data product declares
``metadata.conforms_to: [{entity: name@major}]`` to state that it publishes a
canonical entity of the Enterprise Data Model. This module turns that
relationship into a picture:

- **entity** nodes come from the canonical registry (``<entity>/v<major>/``),
  plus any entity merely referenced by a product but absent from the registry
  (marked *unresolved*);
- **product** nodes come from scanning manifests under a base path;
- **edges** are ``product -> entity`` conformance links, labelled with the
  attribute rename map when present.

This is read-only: git stays the single source of truth, the graph is just a
projection of it. There are no entity-to-entity (ER/foreign-key) relationships
in DPM, so none are drawn.

Output is Mermaid (default; GitLab and GitHub render it inline in Markdown) or
JSON (a machine-readable model for a future viewer).

Usage:
    python graph.py --base-path . --registry-path examples/canonical
    python graph.py --base-path . --registry-path examples/canonical --format json
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from dpm.manifest_loader import find_all_manifests, load_avro_schema
from dpm.validators.detect_breaking_changes import is_avro_nullable
from dpm.validators.validate_conformance import ENTITY_REF_RE
from dpm.validators.validate_manifest import CANONICAL_ENTITY_KIND

# A canonical version directory is exactly ``v<MAJOR>`` — ``vNext``/``latest``
# are not versions and must not be int-cast.
VERSION_DIR_RE = re.compile(r"^v(\d+)$")


@dataclass
class EntityNode:
    """A canonical entity, pinned to a major version."""

    name: str
    major: str
    status: str  # "active" / "deprecated" / ... or "" when unknown/unresolved
    resolved: bool  # True if found in the registry, False if only referenced
    mandatory: list[str]
    optional: list[str]

    @property
    def key(self) -> str:
        """Stable identity: ``name@major``."""
        return f"{self.name}@{self.major}"


@dataclass
class ProductNode:
    """A data product. Its identity is the manifest path (guaranteed unique)."""

    name: str  # "namespace/name" display label
    namespace: str
    manifest: str

    @property
    def key(self) -> str:
        """Stable identity: the manifest path."""
        return self.manifest


@dataclass
class Edge:
    """A conformance edge from a product to a canonical entity."""

    product: str  # ProductNode.key
    entity: str  # EntityNode.key
    rename: dict[str, str]


@dataclass
class Graph:
    """The full conformance graph."""

    entities: list[EntityNode]
    products: list[ProductNode]
    edges: list[Edge]


def _load_entity_attributes(
    entity_manifest: dict[str, Any], manifest_path: Path
) -> tuple[list[str], list[str]]:
    """Return (mandatory, optional) attribute names from the entity's Avro schema.

    Mirrors ``ConformanceValidator._load_schema_fields``: the schema file is
    ``manifest["schema"]["file"]`` relative to the manifest directory; a
    missing/unreadable schema yields empty lists. Mandatory attributes are the
    non-nullable fields.
    """
    schema_block = entity_manifest.get("schema")
    if not isinstance(schema_block, dict):
        return [], []
    schema_file = schema_block.get("file")
    if not isinstance(schema_file, str):
        return [], []
    schema_path = manifest_path.parent / schema_file
    try:
        schema = load_avro_schema(schema_path)
    except (OSError, json.JSONDecodeError):
        return [], []
    fields = schema.get("fields", [])
    if not isinstance(fields, list):
        return [], []
    mandatory: list[str] = []
    optional: list[str] = []
    for fld in fields:
        if not isinstance(fld, dict):
            continue
        fname = fld.get("name")
        if not isinstance(fname, str):
            continue
        (optional if is_avro_nullable(fld) else mandatory).append(fname)
    return mandatory, optional


def _discover_registry_entities(registry_path: Path) -> dict[tuple[str, str], EntityNode]:
    """Discover canonical entities under ``<registry>/<entity>/v<major>/``.

    Keyed by ``(directory_name, major)`` — the directory name is what a
    product's ``conforms_to`` reference resolves against (see
    ``ConformanceValidator._validate_entry``), not the manifest's display name.
    """
    entities: dict[tuple[str, str], EntityNode] = {}
    for manifest_path in sorted(registry_path.glob("*/v*/manifest.yaml")):
        version_match = VERSION_DIR_RE.match(manifest_path.parent.name)
        if not version_match:
            continue
        major = version_match.group(1)
        try:
            with open(manifest_path, encoding="utf-8") as f:
                manifest = yaml.safe_load(f) or {}
        except (OSError, yaml.YAMLError):
            continue
        if not isinstance(manifest, dict) or manifest.get("kind") != CANONICAL_ENTITY_KIND:
            continue
        name = manifest_path.parent.parent.name
        status = manifest.get("status")
        mandatory, optional = _load_entity_attributes(manifest, manifest_path)
        entities[(name, major)] = EntityNode(
            name=name,
            major=major,
            status=status if isinstance(status, str) else "",
            resolved=True,
            mandatory=mandatory,
            optional=optional,
        )
    return entities


def build_graph(base_path: Path, registry_path: Path | None) -> Graph:
    """Build the conformance graph from manifests under base_path and a registry."""
    entity_map: dict[tuple[str, str], EntityNode] = {}
    if registry_path is not None:
        entity_map = _discover_registry_entities(registry_path)
        if not entity_map:
            print(
                f"warning: no canonical entities found under {registry_path}",
                file=sys.stderr,
            )

    products: list[ProductNode] = []
    edges: dict[tuple[str, str], Edge] = {}

    for manifest_path in find_all_manifests(base_path):
        try:
            with open(manifest_path, encoding="utf-8") as f:
                manifest = yaml.safe_load(f) or {}
        except (OSError, yaml.YAMLError):
            continue
        if not isinstance(manifest, dict):
            continue
        # Canonical entities are drawn from the registry, not as products.
        if manifest.get("kind") == CANONICAL_ENTITY_KIND:
            continue
        metadata = manifest.get("metadata")
        if not isinstance(metadata, dict):
            continue

        name = metadata.get("name")
        namespace = metadata.get("namespace")
        product = ProductNode(
            name=f"{namespace if isinstance(namespace, str) else '?'}/"
            f"{name if isinstance(name, str) else '?'}",
            namespace=namespace if isinstance(namespace, str) else "?",
            manifest=str(manifest_path),
        )
        products.append(product)

        conforms_to = metadata.get("conforms_to")
        if not isinstance(conforms_to, list):
            continue
        for entry in conforms_to:
            if not isinstance(entry, dict) or "entity" not in entry:
                continue
            match = ENTITY_REF_RE.match(str(entry.get("entity", "")))
            if not match:
                continue
            ent_key = (match.group("name"), match.group("major"))
            raw_rename = entry.get("rename")
            rename = (
                {str(k): str(v) for k, v in raw_rename.items()}
                if isinstance(raw_rename, dict)
                else {}
            )
            if ent_key not in entity_map:
                entity_map[ent_key] = EntityNode(
                    name=ent_key[0],
                    major=ent_key[1],
                    status="",
                    resolved=False,
                    mandatory=[],
                    optional=[],
                )
            entity_id = f"{ent_key[0]}@{ent_key[1]}"
            edges[(product.key, entity_id)] = Edge(
                product=product.key, entity=entity_id, rename=rename
            )

    return Graph(
        entities=sorted(entity_map.values(), key=lambda e: (e.name, e.major)),
        products=sorted(products, key=lambda p: p.manifest),
        edges=sorted(edges.values(), key=lambda e: (e.product, e.entity)),
    )


def _escape_label(text: str) -> str:
    """Escape a string for use inside a quoted Mermaid label."""
    return text.replace('"', "#quot;")


def render_mermaid(graph: Graph) -> str:
    """Render the graph as a Mermaid ``graph LR`` flowchart."""
    lines: list[str] = ["graph LR"]
    if not graph.entities and not graph.products:
        lines.append("  %% empty graph: no entities or products found")
        return "\n".join(lines)

    entity_ids: dict[str, str] = {}
    product_ids: dict[str, str] = {}

    for index, entity in enumerate(graph.entities):
        node_id = f"e_{index}"
        entity_ids[entity.key] = node_id
        if entity.resolved:
            label = (
                f"{entity.key}<br/>canonical · {entity.status or 'unknown'}"
                f"<br/>{len(entity.mandatory)} mandatory"
            )
        else:
            label = f"{entity.key}<br/>unresolved (not in registry)"
        lines.append(f'  {node_id}["{_escape_label(label)}"]')

    for index, product in enumerate(graph.products):
        node_id = f"p_{index}"
        product_ids[product.key] = node_id
        lines.append(f'  {node_id}["{_escape_label(product.name)}"]')

    for edge in graph.edges:
        product_id = product_ids.get(edge.product)
        entity_id = entity_ids.get(edge.entity)
        if product_id is None or entity_id is None:
            continue
        if edge.rename:
            label = _escape_label(
                ", ".join(f"{k}→{v}" for k, v in sorted(edge.rename.items()))
            )
        else:
            label = "conforms_to"
        lines.append(f'  {product_id} -->|"{label}"| {entity_id}')

    lines.append("  classDef entity fill:#dbeafe,stroke:#1e40af,color:#1e3a8a;")
    lines.append("  classDef entityDeprecated fill:#fee2e2,stroke:#991b1b,color:#7f1d1d;")
    lines.append(
        "  classDef entityUnresolved fill:#f3f4f6,stroke:#6b7280,color:#374151,"
        "stroke-dasharray:4;"
    )
    lines.append("  classDef product fill:#dcfce7,stroke:#166534,color:#14532d;")

    for entity in graph.entities:
        if not entity.resolved:
            css = "entityUnresolved"
        elif entity.status == "deprecated":
            css = "entityDeprecated"
        else:
            css = "entity"
        lines.append(f"  class {entity_ids[entity.key]} {css};")
    for product in graph.products:
        lines.append(f"  class {product_ids[product.key]} product;")

    return "\n".join(lines)


def render_json(graph: Graph) -> str:
    """Render the graph as deterministic JSON."""
    return json.dumps(
        dataclasses.asdict(graph), indent=2, ensure_ascii=False, sort_keys=True
    )


def main() -> None:
    """Entry point."""
    parser = argparse.ArgumentParser(
        description="Render the conformance graph (products <-> canonical entities)"
    )
    parser.add_argument(
        "--base-path", default=".", help="Base path to scan for product manifests"
    )
    parser.add_argument(
        "--registry-path", help="Path to the canonical registry (optional but recommended)"
    )
    parser.add_argument(
        "--format", choices=["mermaid", "json"], default="mermaid", help="Output format"
    )
    parser.add_argument("--output", help="Write output to a file instead of stdout")

    args = parser.parse_args()
    registry_path = Path(args.registry_path) if args.registry_path else None
    graph = build_graph(Path(args.base_path), registry_path)
    output = render_json(graph) if args.format == "json" else render_mermaid(graph)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output + "\n")
        print(f"Graph written to: {args.output}")
    else:
        print(output)

    sys.exit(0)


if __name__ == "__main__":
    main()
