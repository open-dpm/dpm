"""Tests for validate_conformance.py."""

import json
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

from dpm.validators.validate_conformance import ConformanceValidator

# ═══════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════

ENTITY_FIELDS = [
    {"name": "icao24", "type": "string"},
    {"name": "latitude", "type": "double"},
    {"name": "longitude", "type": "double"},
    {"name": "observed_at", "type": {"type": "long", "logicalType": "timestamp-millis"}},
    {"name": "callsign", "type": ["null", "string"], "default": None},  # optional
]


def _write_avsc(path: Path, fields: list[dict]) -> None:
    path.write_text(
        json.dumps({"type": "record", "name": "R", "fields": fields}),
        encoding="utf-8",
    )


def _make_entity(
    registry: Path,
    name: str = "aircraft_observation",
    major: int = 1,
    status: str = "active",
    fields: list[dict] | None = None,
    deprecation: dict | None = None,
) -> None:
    """Create a canonical entity at registry/<name>/v<major>/."""
    entity_dir = registry / name / f"v{major}"
    entity_dir.mkdir(parents=True, exist_ok=True)
    _write_avsc(entity_dir / "schema.avsc", fields if fields is not None else ENTITY_FIELDS)
    manifest = {
        "kind": "canonical_entity",
        "spec_version": "1.0.0",
        "manifest_version": f"{major}.0.0",
        "status": status,
        "metadata": {"name": name, "namespace": "aviation"},
        "schema": {"file": "./schema.avsc", "format": "avro"},
    }
    if deprecation:
        manifest["deprecation"] = deprecation
    (entity_dir / "manifest.yaml").write_text(yaml.dump(manifest), encoding="utf-8")


def _make_product(
    product_dir: Path,
    conforms_to=None,
    fields: list[dict] | None = None,
    kind: str | None = None,
) -> Path:
    """Create a product manifest and return its path."""
    product_dir.mkdir(parents=True, exist_ok=True)
    default_fields = [
        {"name": "icao24", "type": "string"},
        {"name": "latitude", "type": "double"},
        {"name": "longitude", "type": "double"},
        {"name": "timestamp", "type": {"type": "long", "logicalType": "timestamp-millis"}},
    ]
    _write_avsc(product_dir / "schema.avsc", fields if fields is not None else default_fields)
    manifest: dict = {
        "metadata": {"name": "flights", "namespace": "aviation"},
        "schema": {"file": "./schema.avsc"},
    }
    if kind:
        manifest["kind"] = kind
    if conforms_to is not None:
        manifest["metadata"]["conforms_to"] = conforms_to
    path = product_dir / "manifest.yaml"
    path.write_text(yaml.dump(manifest), encoding="utf-8")
    return path


def _rules(report) -> list[str]:
    return [f.rule for f in report.findings]


# ═══════════════════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def registry(tmp_path) -> Path:
    reg = tmp_path / "registry"
    _make_entity(reg)
    return reg


@pytest.fixture
def validator(registry) -> ConformanceValidator:
    return ConformanceValidator(registry)


# ═══════════════════════════════════════════════════════════════════════════
# TESTS: opt-in behaviour
# ═══════════════════════════════════════════════════════════════════════════


class TestOptIn:
    def test_no_conforms_to_is_noop(self, validator, tmp_path):
        """A product without conforms_to is outside the EDM: no findings."""
        path = _make_product(tmp_path / "p")
        report = validator.validate_manifest(path)
        assert report.passed
        assert report.findings == []

    def test_entity_manifest_is_skipped(self, validator, tmp_path):
        """A canonical_entity manifest does not conform to anything."""
        path = _make_product(
            tmp_path / "p", conforms_to=[{"entity": "aircraft_observation@1"}], kind="canonical_entity"
        )
        report = validator.validate_manifest(path)
        assert report.passed
        assert report.findings == []


# ═══════════════════════════════════════════════════════════════════════════
# TESTS: conformance checking
# ═══════════════════════════════════════════════════════════════════════════


class TestConformance:
    def test_conforming_product_with_rename_passes(self, validator, tmp_path):
        path = _make_product(
            tmp_path / "p",
            conforms_to=[{"entity": "aircraft_observation@1", "rename": {"observed_at": "timestamp"}}],
        )
        report = validator.validate_manifest(path)
        assert report.passed, _rules(report)
        assert report.findings == []

    def test_missing_mandatory_attribute(self, validator, tmp_path):
        path = _make_product(
            tmp_path / "p",
            conforms_to=[{"entity": "aircraft_observation@1", "rename": {"observed_at": "timestamp"}}],
            fields=[
                {"name": "icao24", "type": "string"},
                {"name": "longitude", "type": "double"},
                {"name": "timestamp", "type": {"type": "long", "logicalType": "timestamp-millis"}},
            ],
        )
        report = validator.validate_manifest(path)
        assert not report.passed
        assert "conformance_missing_attribute" in _rules(report)

    def test_missing_attribute_without_rename_uses_canonical_name(self, validator, tmp_path):
        """Without a rename, the product must use the canonical attribute name."""
        path = _make_product(
            tmp_path / "p",
            conforms_to=[{"entity": "aircraft_observation@1"}],  # no rename
        )
        report = validator.validate_manifest(path)
        # product has 'timestamp', canonical wants 'observed_at' -> missing
        assert "conformance_missing_attribute" in _rules(report)

    def test_type_mismatch(self, validator, tmp_path):
        path = _make_product(
            tmp_path / "p",
            conforms_to=[{"entity": "aircraft_observation@1", "rename": {"observed_at": "timestamp"}}],
            fields=[
                {"name": "icao24", "type": "string"},
                {"name": "latitude", "type": "string"},  # should be double
                {"name": "longitude", "type": "double"},
                {"name": "timestamp", "type": {"type": "long", "logicalType": "timestamp-millis"}},
            ],
        )
        report = validator.validate_manifest(path)
        assert not report.passed
        assert "conformance_type_mismatch" in _rules(report)

    def test_compatible_promotion_passes(self, validator, tmp_path):
        """A product int satisfies a canonical double (int promotes to double)."""
        _make_entity(
            validator.registry_base,
            name="metric",
            fields=[{"name": "value", "type": "double"}],
        )
        path = _make_product(
            tmp_path / "p",
            conforms_to=[{"entity": "metric@1"}],
            fields=[{"name": "value", "type": "int"}],
        )
        report = validator.validate_manifest(path)
        assert report.passed, _rules(report)

    def test_nullable_field_for_mandatory_attribute_is_error(self, validator, tmp_path):
        """A mandatory attribute cannot be satisfied by a nullable product field."""
        path = _make_product(
            tmp_path / "p",
            conforms_to=[{"entity": "aircraft_observation@1", "rename": {"observed_at": "timestamp"}}],
            fields=[
                {"name": "icao24", "type": ["null", "string"], "default": None},  # nullable
                {"name": "latitude", "type": "double"},
                {"name": "longitude", "type": "double"},
                {"name": "timestamp", "type": {"type": "long", "logicalType": "timestamp-millis"}},
            ],
        )
        report = validator.validate_manifest(path)
        assert not report.passed
        assert "conformance_nullable_attribute" in _rules(report)

    def test_optional_canonical_attribute_not_required(self, validator, tmp_path):
        """The optional 'callsign' attribute is not required for conformance."""
        path = _make_product(
            tmp_path / "p",
            conforms_to=[{"entity": "aircraft_observation@1", "rename": {"observed_at": "timestamp"}}],
        )
        report = validator.validate_manifest(path)
        assert report.passed


# ═══════════════════════════════════════════════════════════════════════════
# TESTS: malformed references and resolution
# ═══════════════════════════════════════════════════════════════════════════


class TestResolution:
    @pytest.mark.parametrize(
        "conforms_to",
        [
            "aircraft_observation@1",  # not a list
            [{"entity": "aircraft_observation"}],  # no @major
            [{"entity": "aircraft_observation@"}],  # empty major
            [{"entity": "aircraft_observation@1.0.0"}],  # full semver not allowed
            [{"rename": {}}],  # missing 'entity'
            [{"entity": "aircraft_observation@1", "rename": ["bad"]}],  # rename not a dict
        ],
    )
    def test_malformed(self, validator, tmp_path, conforms_to):
        path = _make_product(tmp_path / "p", conforms_to=conforms_to)
        report = validator.validate_manifest(path)
        assert not report.passed
        assert "conforms_to_malformed" in _rules(report)

    def test_unknown_entity(self, validator, tmp_path):
        path = _make_product(tmp_path / "p", conforms_to=[{"entity": "customer@1"}])
        report = validator.validate_manifest(path)
        assert "conforms_to_unknown_entity" in _rules(report)

    def test_unresolved_version(self, validator, tmp_path):
        """Entity exists but the requested major (e.g. sunset v2) does not."""
        path = _make_product(tmp_path / "p", conforms_to=[{"entity": "aircraft_observation@2"}])
        report = validator.validate_manifest(path)
        assert "conforms_to_unresolved_version" in _rules(report)

    def test_deprecated_entity_warns_but_passes(self, tmp_path):
        reg = tmp_path / "registry"
        _make_entity(reg, status="deprecated", deprecation={"sunset_date": "2026-12-01"})
        validator = ConformanceValidator(reg)
        path = _make_product(
            tmp_path / "p",
            conforms_to=[{"entity": "aircraft_observation@1", "rename": {"observed_at": "timestamp"}}],
        )
        report = validator.validate_manifest(path)
        assert report.passed  # warning only, no error
        assert "conforms_to_deprecated" in _rules(report)
