"""Tests for the conformance graph builder and renderers (dpm.graph)."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from dpm.graph import (
    Edge,
    EntityNode,
    Graph,
    ProductNode,
    build_graph,
    render_json,
    render_mermaid,
)

# ── fixtures / builders ──────────────────────────────────────────────────────


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _entity(
    registry: Path,
    name: str,
    major: str,
    fields: list[dict],
    status: str = "active",
) -> None:
    """Create a canonical entity ``<registry>/<name>/v<major>/``."""
    base = registry / name / f"v{major}"
    manifest = {
        "kind": "canonical_entity",
        "status": status,
        "metadata": {"name": name, "namespace": "canon"},
        "schema": {"file": "./schema.avsc", "format": "avro"},
    }
    _write(base / "manifest.yaml", yaml.dump(manifest))
    schema = {"type": "record", "name": name, "fields": fields}
    _write(base / "schema.avsc", json.dumps(schema))


def _product(
    examples: Path,
    namespace: str,
    name: str,
    conforms_to: object = None,
    kind: object = None,
    metadata: object = "auto",
) -> None:
    """Create a product manifest ``<examples>/<namespace>/<name>/manifest.yaml``."""
    manifest: dict = {}
    if kind is not None:
        manifest["kind"] = kind
    if metadata == "auto":
        meta: dict = {"name": name, "namespace": namespace}
        if conforms_to is not None:
            meta["conforms_to"] = conforms_to
        manifest["metadata"] = meta
    elif metadata is not None:
        manifest["metadata"] = metadata
    _write(examples / namespace / name / "manifest.yaml", yaml.dump(manifest))


def _string_field(name: str) -> dict:
    return {"name": name, "type": "string"}


def _nullable_union_field(name: str) -> dict:
    return {"name": name, "type": ["null", "string"], "default": None}


def _required_false_field(name: str) -> dict:
    return {"name": name, "type": "string", "required": False}


# ── build_graph ──────────────────────────────────────────────────────────────


class TestBuildGraph:
    def test_two_entities_one_deprecated(self, tmp_path):
        registry = tmp_path / "canonical"
        _entity(registry, "customer", "1", [_string_field("id")])
        _entity(registry, "account", "1", [_string_field("iban")], status="deprecated")

        graph = build_graph(tmp_path / "examples", registry)

        by_key = {e.key: e for e in graph.entities}
        assert set(by_key) == {"customer@1", "account@1"}
        assert by_key["customer@1"].status == "active"
        assert by_key["account@1"].status == "deprecated"
        assert all(e.resolved for e in graph.entities)

    def test_mandatory_vs_optional_split(self, tmp_path):
        registry = tmp_path / "canonical"
        _entity(
            registry,
            "customer",
            "1",
            [
                _string_field("id"),  # mandatory
                _nullable_union_field("nickname"),  # optional (avro union)
                _required_false_field("note"),  # optional (required: false)
            ],
        )
        graph = build_graph(tmp_path / "examples", registry)
        entity = graph.entities[0]
        assert entity.mandatory == ["id"]
        assert sorted(entity.optional) == ["nickname", "note"]

    def test_product_with_conformance_and_rename(self, tmp_path):
        registry = tmp_path / "canonical"
        _entity(registry, "customer", "1", [_string_field("id")])
        examples = tmp_path / "examples"
        _product(
            examples,
            "sales",
            "orders",
            conforms_to=[{"entity": "customer@1", "rename": {"id": "cust_id"}}],
        )
        graph = build_graph(examples, registry)
        assert len(graph.edges) == 1
        edge = graph.edges[0]
        assert edge.entity == "customer@1"
        assert edge.rename == {"id": "cust_id"}

    def test_reference_to_entity_absent_from_registry_is_unresolved(self, tmp_path):
        registry = tmp_path / "canonical"
        _entity(registry, "customer", "1", [_string_field("id")])
        examples = tmp_path / "examples"
        _product(examples, "sales", "orders", conforms_to=[{"entity": "ghost@1"}])

        graph = build_graph(examples, registry)
        by_key = {e.key: e for e in graph.entities}
        assert by_key["ghost@1"].resolved is False
        assert by_key["customer@1"].resolved is True

    def test_different_major_does_not_collapse(self, tmp_path):
        registry = tmp_path / "canonical"
        _entity(registry, "customer", "1", [_string_field("id")])
        examples = tmp_path / "examples"
        _product(examples, "sales", "orders", conforms_to=[{"entity": "customer@2"}])

        graph = build_graph(examples, registry)
        by_key = {e.key: e for e in graph.entities}
        assert by_key["customer@1"].resolved is True
        assert by_key["customer@2"].resolved is False

    def test_malformed_conforms_to_is_skipped(self, tmp_path):
        examples = tmp_path / "examples"
        _product(examples, "a", "scalar_ct", conforms_to="customer@1")  # not a list
        _product(examples, "a", "entry_not_dict", conforms_to=["customer@1"])
        _product(examples, "a", "no_entity_key", conforms_to=[{"rename": {"x": "y"}}])
        _product(examples, "a", "bad_ref", conforms_to=[{"entity": "customer"}])  # no @N
        _product(examples, "a", "meta_scalar", metadata="oops")
        _product(examples, "a", "meta_null", metadata=None)

        graph = build_graph(examples, None)
        # None of these reference a well-formed entity, so no edges or entities.
        assert graph.edges == []
        assert graph.entities == []

    def test_rename_not_dict_yields_edge_without_rename(self, tmp_path):
        examples = tmp_path / "examples"
        _product(
            examples, "a", "p", conforms_to=[{"entity": "customer@1", "rename": "oops"}]
        )
        graph = build_graph(examples, None)
        assert len(graph.edges) == 1
        assert graph.edges[0].rename == {}

    def test_duplicate_conforms_to_deduped(self, tmp_path):
        examples = tmp_path / "examples"
        _product(
            examples,
            "a",
            "p",
            conforms_to=[
                {"entity": "customer@1", "rename": {"id": "a"}},
                {"entity": "customer@1", "rename": {"id": "b"}},
            ],
        )
        graph = build_graph(examples, None)
        assert len(graph.edges) == 1

    def test_canonical_manifest_not_a_product(self, tmp_path):
        # A canonical entity sitting under the scanned tree must not become a product.
        examples = tmp_path / "examples"
        _entity(examples / "canonical", "customer", "1", [_string_field("id")])
        graph = build_graph(examples, examples / "canonical")
        assert graph.products == []

    def test_registry_none_and_missing_path(self, tmp_path):
        examples = tmp_path / "examples"
        _product(examples, "a", "p", conforms_to=[{"entity": "customer@1"}])
        # None registry
        graph_none = build_graph(examples, None)
        assert graph_none.entities[0].resolved is False
        # non-existent registry path — no crash, empty registry
        graph_missing = build_graph(examples, tmp_path / "does_not_exist")
        assert graph_missing.entities[0].resolved is False

    def test_non_version_dir_skipped(self, tmp_path):
        registry = tmp_path / "canonical"
        # a v1 valid dir plus a bogus "vNext" and "latest" dir
        _entity(registry, "customer", "1", [_string_field("id")])
        _write(registry / "customer" / "vNext" / "manifest.yaml", yaml.dump({"kind": "canonical_entity"}))
        _write(registry / "customer" / "latest" / "manifest.yaml", yaml.dump({"kind": "canonical_entity"}))
        graph = build_graph(tmp_path / "examples", registry)
        assert {e.key for e in graph.entities} == {"customer@1"}

    def test_product_id_collision_distinct(self, tmp_path):
        # "sales/orders" and "sales_orders" sanitize to the same token; ids must differ.
        examples = tmp_path / "examples"
        _product(examples, "sales", "orders", conforms_to=[{"entity": "c@1"}])
        _product(examples, "sales_orders", "x", conforms_to=[{"entity": "c@1"}])
        graph = build_graph(examples, None)
        mermaid = render_mermaid(graph)
        assert "p_0[" in mermaid and "p_1[" in mermaid

    def test_determinism(self, tmp_path):
        registry = tmp_path / "canonical"
        _entity(registry, "customer", "1", [_string_field("id")])
        _entity(registry, "account", "1", [_string_field("iban")])
        examples = tmp_path / "examples"
        _product(examples, "z", "p2", conforms_to=[{"entity": "account@1"}])
        _product(examples, "a", "p1", conforms_to=[{"entity": "customer@1"}])
        first = render_mermaid(build_graph(examples, registry))
        second = render_mermaid(build_graph(examples, registry))
        assert first == second


# ── render_mermaid ───────────────────────────────────────────────────────────


class TestRenderMermaid:
    def _graph(self) -> Graph:
        return Graph(
            entities=[
                EntityNode("customer", "1", "active", True, ["id"], []),
                EntityNode("ghost", "1", "", False, [], []),
            ],
            products=[ProductNode("sales/orders", "sales", "m.yaml")],
            edges=[Edge("m.yaml", "customer@1", {"id": "cust_id"})],
        )

    def test_header_and_classdefs(self):
        out = render_mermaid(self._graph())
        assert out.startswith("graph LR")
        assert "classDef entity " in out
        assert "classDef entityDeprecated " in out
        assert "classDef entityUnresolved " in out
        assert "classDef product " in out

    def test_edge_with_rename_uses_unicode_arrow(self):
        out = render_mermaid(self._graph())
        assert '-->|"id→cust_id"|' in out
        assert "->|\"id->" not in out  # never the ascii arrow inside a label

    def test_edge_without_rename(self):
        graph = Graph(
            entities=[EntityNode("customer", "1", "active", True, ["id"], [])],
            products=[ProductNode("sales/orders", "sales", "m.yaml")],
            edges=[Edge("m.yaml", "customer@1", {})],
        )
        assert '-->|"conforms_to"|' in render_mermaid(graph)

    def test_unresolved_entity_styled(self):
        out = render_mermaid(self._graph())
        # ghost is the 2nd entity → e_1, unresolved class
        assert "class e_1 entityUnresolved;" in out
        assert "unresolved (not in registry)" in out

    def test_deprecated_entity_styled(self):
        graph = Graph(
            entities=[EntityNode("account", "1", "deprecated", True, [], [])],
            products=[],
            edges=[],
        )
        assert "class e_0 entityDeprecated;" in render_mermaid(graph)

    def test_label_quote_escaped(self):
        graph = Graph(
            entities=[],
            products=[ProductNode('weird"/name', "weird", "m.yaml")],
            edges=[],
        )
        out = render_mermaid(graph)
        assert '#quot;' in out
        assert '"weird"/name"' not in out  # raw quote must not leak into the label

    def test_empty_graph(self):
        out = render_mermaid(Graph([], [], []))
        assert out.startswith("graph LR")
        assert "empty graph" in out


# ── render_json ──────────────────────────────────────────────────────────────


class TestRenderJson:
    def test_shape_and_round_trip(self, tmp_path):
        registry = tmp_path / "canonical"
        _entity(registry, "customer", "1", [_string_field("id"), _nullable_union_field("nn")])
        examples = tmp_path / "examples"
        _product(examples, "sales", "orders", conforms_to=[{"entity": "customer@1"}])
        graph = build_graph(examples, registry)

        data = json.loads(render_json(graph))
        assert set(data) == {"entities", "products", "edges"}
        assert data["entities"][0]["name"] == "customer"
        assert data["entities"][0]["mandatory"] == ["id"]
        assert data["entities"][0]["optional"] == ["nn"]
        assert data["products"][0]["manifest"].endswith("manifest.yaml")
        assert data["edges"][0]["entity"] == "customer@1"

    def test_json_is_sorted_and_stable(self, tmp_path):
        examples = tmp_path / "examples"
        _product(examples, "a", "p", conforms_to=[{"entity": "customer@1"}])
        graph = build_graph(examples, None)
        assert render_json(graph) == render_json(graph)
