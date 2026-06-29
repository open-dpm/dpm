"""Tests for conformance_impact.py."""

import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

from dpm.validators.conformance_impact import conforms_to_entity, find_conformers


def _make_product(directory: Path, name: str, conforms_to, owner=None) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    manifest = {
        "metadata": {
            "name": name,
            "namespace": "aviation",
            "owner": owner or {"team": "t", "email": f"{name}@example.com"},
            "conforms_to": conforms_to,
        },
    }
    (directory / "manifest.yaml").write_text(yaml.dump(manifest), encoding="utf-8")


class TestConformsToEntity:
    @pytest.mark.parametrize(
        "ref, entity, major, expected",
        [
            ("customer@1", "customer", "1", True),
            ("customer@2", "customer", "1", False),
            ("account@1", "customer", "1", False),
            ("customer", "customer", "1", False),  # malformed ref never matches
        ],
    )
    def test_matching(self, ref, entity, major, expected):
        manifest = {"metadata": {"conforms_to": [{"entity": ref}]}}
        assert conforms_to_entity(manifest, entity, major) is expected

    def test_no_conforms_to(self):
        assert conforms_to_entity({"metadata": {}}, "customer", "1") is False

    def test_multiple_entities(self):
        manifest = {"metadata": {"conforms_to": [{"entity": "a@1"}, {"entity": "customer@1"}]}}
        assert conforms_to_entity(manifest, "customer", "1") is True


class TestFindConformers:
    def test_finds_only_matching(self, tmp_path):
        base = tmp_path / "examples"
        _make_product(base / "aviation" / "flights", "flights", [{"entity": "aircraft_observation@1"}])
        _make_product(base / "aviation" / "weather", "weather", [{"entity": "aircraft_observation@2"}])
        _make_product(base / "sales" / "orders", "orders", [{"entity": "order@1"}])

        conformers = find_conformers(tmp_path, "aircraft_observation", "1")
        names = {c["name"] for c in conformers}
        assert names == {"aviation/flights"}
        assert conformers[0]["email"] == "flights@example.com"

    def test_empty_when_none_match(self, tmp_path):
        base = tmp_path / "examples"
        _make_product(base / "sales" / "orders", "orders", [{"entity": "order@1"}])
        assert find_conformers(tmp_path, "customer", "1") == []
