"""Tests for validate_manifest.py."""

import json
import sys
from pathlib import Path

import pytest
import yaml

# Add the parent directory to the path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from dpm.manifest_loader import find_all_manifests
from dpm.validators.validate_manifest import (
    validate_manifest,
    validate_naming_conventions,
    validate_required_fields,
    validate_version_format,
    validate_yaml_syntax,
)

# ═══════════════════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def valid_avro_schema():
    """A valid Avro schema."""
    return {
        "type": "record",
        "name": "TestRecord",
        "namespace": "test",
        "fields": [
            {"name": "id", "type": "string", "doc": "Record ID"},
            {"name": "value", "type": "int", "doc": "Value"},
        ],
    }


@pytest.fixture
def valid_manifest_dir(tmp_path, valid_avro_schema):
    """A directory with a valid manifest and .avsc file."""
    manifest = {
        "spec_version": "1.0.0",
        "manifest_version": "1.0.0",
        "status": "active",
        "metadata": {
            "name": "test_entity",
            "namespace": "test_domain",
            "data_category": "transactional_data",
            "owner": {"team": "test-team", "email": "test@example.com"},
        },
        "schema": {"file": "./schema.avsc", "format": "avro"},
        "semantics": {"file": "./semantics.yml"},
        "quality_rules": {"file": "./quality_rules.yml"},
        "sla": {"file": "./sla.yml"},
        "lineage": {"upstream": [], "downstream": []},
        "changelog": [
            {
                "version": "1.0.0",
                "date": "2026-01-01",
                "changes": [{"type": "initial", "description": "Initial manifest"}],
            }
        ],
    }
    manifest_path = tmp_path / "manifest.yaml"
    with open(manifest_path, "w") as f:
        yaml.dump(manifest, f)

    schema_path = tmp_path / "schema.avsc"
    with open(schema_path, "w") as f:
        json.dump(valid_avro_schema, f)

    rules_path = tmp_path / "quality_rules.yml"
    with open(rules_path, "w") as f:
        yaml.dump({"version": "1.0", "rules": []}, f)

    semantics_path = tmp_path / "semantics.yml"
    with open(semantics_path, "w") as f:
        yaml.dump(
            {
                "version": "1.0",
                "business_terms": [
                    {
                        "name": "test_entity",
                        "definition": "Test entity",
                        "aliases": ["test"],
                        "owner": "test-team",
                    }
                ],
                "interpretation": {
                    "grain": "one record per test entity",
                    "time_basis": "created_at",
                    "known_limitations": [],
                    "do": ["Use for tests"],
                    "dont": ["Do not use as a business metric"],
                },
                "typical_questions": ["How many test records were created?"],
                "ai_hints": {
                    "default_time_field": "created_at",
                    "default_grain": "day",
                    "recommended_visualizations": ["table"],
                    "safe_aggregation_notes": ["Count records by id"],
                },
            },
            f,
        )

    sla_path = tmp_path / "sla.yml"
    with open(sla_path, "w") as f:
        yaml.dump({"availability": {"target": "99.9%"}}, f)

    return tmp_path, manifest_path, manifest


# ═══════════════════════════════════════════════════════════════════════════
# YAML SYNTAX
# ═══════════════════════════════════════════════════════════════════════════


class TestValidateYamlSyntax:
    """Tests for YAML syntax validation."""

    def test_valid_yaml(self, valid_manifest_dir):
        _, manifest_path, _ = valid_manifest_dir
        errors = validate_yaml_syntax(manifest_path)
        assert errors == []

    def test_invalid_yaml_syntax(self, tmp_path):
        file_path = tmp_path / "bad.yaml"
        file_path.write_text("key:\n  - item1\n item2\n")
        errors = validate_yaml_syntax(file_path)
        assert len(errors) > 0
        assert "YAML syntax error" in errors[0]

    def test_missing_file(self):
        errors = validate_yaml_syntax(Path("/nonexistent/file.yaml"))
        assert len(errors) > 0
        assert "Error reading file" in errors[0]


# ═══════════════════════════════════════════════════════════════════════════
# REQUIRED FIELDS
# ═══════════════════════════════════════════════════════════════════════════


class TestValidateRequiredFields:
    """Tests for required-field validation."""

    def test_valid_manifest(self, valid_manifest_dir):
        _, manifest_path, _ = valid_manifest_dir
        errors = validate_required_fields(manifest_path)
        assert errors == []

    def test_missing_top_level_field(self, valid_manifest_dir):
        tmp_path, _, manifest = valid_manifest_dir
        del manifest["manifest_version"]
        file_path = tmp_path / "no_version.yaml"
        with open(file_path, "w") as f:
            yaml.dump(manifest, f)
        errors = validate_required_fields(file_path)
        assert any("manifest_version" in e for e in errors)

    def test_missing_metadata_owner(self, valid_manifest_dir):
        tmp_path, _, manifest = valid_manifest_dir
        del manifest["metadata"]["owner"]
        file_path = tmp_path / "no_owner.yaml"
        with open(file_path, "w") as f:
            yaml.dump(manifest, f)
        errors = validate_required_fields(file_path)
        assert any("owner" in e for e in errors)

    def test_missing_data_category(self, valid_manifest_dir):
        """Missing metadata.data_category is an error."""
        tmp_path, _, manifest = valid_manifest_dir
        del manifest["metadata"]["data_category"]
        file_path = tmp_path / "no_data_category.yaml"
        with open(file_path, "w") as f:
            yaml.dump(manifest, f)
        errors = validate_required_fields(file_path)
        assert any("data_category" in e for e in errors)

    def test_invalid_data_category(self, valid_manifest_dir):
        """An invalid metadata.data_category is an error."""
        tmp_path, _, manifest = valid_manifest_dir
        manifest["metadata"]["data_category"] = "app"
        file_path = tmp_path / "bad_data_category.yaml"
        with open(file_path, "w") as f:
            yaml.dump(manifest, f)
        errors = validate_required_fields(file_path)
        assert any("Invalid data_category" in e for e in errors)

    def test_missing_owner_email(self, valid_manifest_dir):
        tmp_path, _, manifest = valid_manifest_dir
        del manifest["metadata"]["owner"]["email"]
        file_path = tmp_path / "no_email.yaml"
        with open(file_path, "w") as f:
            yaml.dump(manifest, f)
        errors = validate_required_fields(file_path)
        assert any("email" in e for e in errors)

    def test_empty_manifest(self, tmp_path):
        file_path = tmp_path / "empty.yaml"
        file_path.write_text("---\n")
        errors = validate_required_fields(file_path)
        assert "Manifest is empty" in errors

    def test_missing_schema_file_reference(self, valid_manifest_dir):
        """A reference to a missing .avsc file."""
        tmp_path, _, manifest = valid_manifest_dir
        manifest["schema"]["file"] = "./nonexistent.avsc"
        file_path = tmp_path / "bad_ref.yaml"
        with open(file_path, "w") as f:
            yaml.dump(manifest, f)
        errors = validate_required_fields(file_path)
        assert any("not found" in e for e in errors)

    def test_invalid_avsc_json(self, valid_manifest_dir):
        """Invalid JSON in an .avsc file."""
        tmp_path, _, manifest = valid_manifest_dir
        (tmp_path / "schema.avsc").write_text("{invalid json")
        file_path = tmp_path / "manifest.yaml"
        with open(file_path, "w") as f:
            yaml.dump(manifest, f)
        errors = validate_required_fields(file_path)
        assert any("Invalid JSON" in e for e in errors)

    def test_avsc_missing_type(self, valid_manifest_dir):
        """An Avro schema without a type field."""
        tmp_path, _, manifest = valid_manifest_dir
        (tmp_path / "schema.avsc").write_text('{"name": "Test", "fields": []}')
        file_path = tmp_path / "manifest.yaml"
        with open(file_path, "w") as f:
            yaml.dump(manifest, f)
        errors = validate_required_fields(file_path)
        assert any("type" in e for e in errors)

    def test_schema_without_file_or_fields(self, valid_manifest_dir):
        """A schema with neither file nor fields."""
        tmp_path, _, manifest = valid_manifest_dir
        manifest["schema"] = {"format": "avro"}
        file_path = tmp_path / "no_schema.yaml"
        with open(file_path, "w") as f:
            yaml.dump(manifest, f)
        errors = validate_required_fields(file_path)
        assert any("file" in e or "fields" in e for e in errors)

    def test_missing_status(self, valid_manifest_dir):
        """Missing status is a manifest.yaml structure error."""
        tmp_path, _, manifest = valid_manifest_dir
        del manifest["status"]
        file_path = tmp_path / "no_status.yaml"
        with open(file_path, "w") as f:
            yaml.dump(manifest, f)
        errors = validate_required_fields(file_path)
        assert any("status" in e for e in errors)

    def test_invalid_status(self, valid_manifest_dir):
        """An invalid status is an error."""
        tmp_path, _, manifest = valid_manifest_dir
        manifest["status"] = "published"
        file_path = tmp_path / "bad_status.yaml"
        with open(file_path, "w") as f:
            yaml.dump(manifest, f)
        errors = validate_required_fields(file_path)
        assert any("Invalid status" in e for e in errors)

    def test_missing_quality_rules_file(self, valid_manifest_dir):
        """A quality_rules.yml reference is required."""
        tmp_path, _, manifest = valid_manifest_dir
        del manifest["quality_rules"]["file"]
        file_path = tmp_path / "no_rules_ref.yaml"
        with open(file_path, "w") as f:
            yaml.dump(manifest, f)
        errors = validate_required_fields(file_path)
        assert any("quality_rules" in e for e in errors)

    def test_missing_semantics_file(self, valid_manifest_dir):
        """A semantics.yml reference is required."""
        tmp_path, _, manifest = valid_manifest_dir
        del manifest["semantics"]["file"]
        file_path = tmp_path / "no_semantics_ref.yaml"
        with open(file_path, "w") as f:
            yaml.dump(manifest, f)
        errors = validate_required_fields(file_path)
        assert any("semantics" in e for e in errors)

    def test_invalid_semantics_yaml(self, valid_manifest_dir):
        """Invalid YAML in semantics.yml is an error."""
        tmp_path, manifest_path, _ = valid_manifest_dir
        (tmp_path / "semantics.yml").write_text("business_terms:\n  - name: test\n bad\n")
        errors = validate_required_fields(manifest_path)
        assert any("Invalid YAML in semantics file" in e for e in errors)

    def test_unknown_semantics_metrics_section(self, valid_manifest_dir):
        """'metrics' is rejected as an unknown semantics.yml section."""
        tmp_path, manifest_path, _ = valid_manifest_dir
        with open(tmp_path / "semantics.yml", "w") as f:
            yaml.dump({"version": "1.0", "metrics": []}, f)
        errors = validate_required_fields(manifest_path)
        assert any("Unknown semantics section 'metrics'" in e for e in errors)

    def test_unknown_semantics_field_semantics_section(self, valid_manifest_dir):
        """'field_semantics' is rejected as an unknown semantics.yml section."""
        tmp_path, manifest_path, _ = valid_manifest_dir
        with open(tmp_path / "semantics.yml", "w") as f:
            yaml.dump({"version": "1.0", "field_semantics": {}}, f)
        errors = validate_required_fields(manifest_path)
        assert any("Unknown semantics section 'field_semantics'" in e for e in errors)

    def test_unknown_semantics_section(self, valid_manifest_dir):
        """Any extra top-level semantics.yml section is an error."""
        tmp_path, manifest_path, _ = valid_manifest_dir
        with open(tmp_path / "semantics.yml", "w") as f:
            yaml.dump({"version": "1.0", "custom_section": {}}, f)
        errors = validate_required_fields(manifest_path)
        assert any("Unknown semantics section 'custom_section'" in e for e in errors)

    def test_invalid_semantics_section_type(self, valid_manifest_dir):
        """Known semantics.yml sections must have the expected type."""
        tmp_path, manifest_path, _ = valid_manifest_dir
        with open(tmp_path / "semantics.yml", "w") as f:
            yaml.dump({"version": "1.0", "business_terms": {}}, f)
        errors = validate_required_fields(manifest_path)
        assert any("Invalid semantics section 'business_terms'" in e for e in errors)

    def test_missing_lineage_downstream(self, valid_manifest_dir):
        """lineage.downstream is required as a list."""
        tmp_path, _, manifest = valid_manifest_dir
        del manifest["lineage"]["downstream"]
        file_path = tmp_path / "no_downstream.yaml"
        with open(file_path, "w") as f:
            yaml.dump(manifest, f)
        errors = validate_required_fields(file_path)
        assert any("lineage" in e and "downstream" in e for e in errors)

    def test_missing_changelog_entries(self, valid_manifest_dir):
        """changelog must contain at least one entry."""
        tmp_path, _, manifest = valid_manifest_dir
        manifest["changelog"] = []
        file_path = tmp_path / "empty_changelog.yaml"
        with open(file_path, "w") as f:
            yaml.dump(manifest, f)
        errors = validate_required_fields(file_path)
        assert any("changelog" in e.lower() for e in errors)


# ═══════════════════════════════════════════════════════════════════════════
# NAMING CONVENTIONS
# ═══════════════════════════════════════════════════════════════════════════


class TestValidateNamingConventions:
    """Tests for naming-convention validation."""

    def test_valid_names(self, valid_manifest_dir):
        _, manifest_path, _ = valid_manifest_dir
        errors = validate_naming_conventions(manifest_path)
        assert errors == []

    def test_invalid_name_uppercase(self, valid_manifest_dir):
        tmp_path, _, manifest = valid_manifest_dir
        manifest["metadata"]["name"] = "BadName"
        file_path = tmp_path / "bad_name.yaml"
        with open(file_path, "w") as f:
            yaml.dump(manifest, f)
        errors = validate_naming_conventions(file_path)
        assert any("lowercase" in e for e in errors)

    def test_invalid_namespace_special_chars(self, valid_manifest_dir):
        tmp_path, _, manifest = valid_manifest_dir
        manifest["metadata"]["namespace"] = "bad-namespace!"
        file_path = tmp_path / "bad_ns.yaml"
        with open(file_path, "w") as f:
            yaml.dump(manifest, f)
        errors = validate_naming_conventions(file_path)
        assert any("snake_case" in e for e in errors)


# ═══════════════════════════════════════════════════════════════════════════
# VERSION FORMAT
# ═══════════════════════════════════════════════════════════════════════════


class TestValidateVersionFormat:
    """Tests for version-format validation."""

    def test_valid_semver(self, valid_manifest_dir):
        _, manifest_path, _ = valid_manifest_dir
        errors = validate_version_format(manifest_path)
        assert errors == []

    def test_invalid_spec_version(self, valid_manifest_dir):
        tmp_path, _, manifest = valid_manifest_dir
        manifest["spec_version"] = "v1"
        file_path = tmp_path / "bad_ver.yaml"
        with open(file_path, "w") as f:
            yaml.dump(manifest, f)
        errors = validate_version_format(file_path)
        assert any("spec_version" in e for e in errors)

    def test_invalid_manifest_version(self, valid_manifest_dir):
        tmp_path, _, manifest = valid_manifest_dir
        manifest["manifest_version"] = "1.0"
        file_path = tmp_path / "bad_cv.yaml"
        with open(file_path, "w") as f:
            yaml.dump(manifest, f)
        errors = validate_version_format(file_path)
        assert any("manifest_version" in e for e in errors)


# ═══════════════════════════════════════════════════════════════════════════
# INTEGRATION: validate_manifest
# ═══════════════════════════════════════════════════════════════════════════


class TestValidateManifest:
    """Integration tests for full manifest validation."""

    def test_valid_manifest(self, valid_manifest_dir):
        _, manifest_path, _ = valid_manifest_dir
        errors = validate_manifest(manifest_path)
        assert errors == []

    def test_invalid_manifest_returns_errors(self, valid_manifest_dir):
        tmp_path, _, manifest = valid_manifest_dir
        del manifest["metadata"]["owner"]
        file_path = tmp_path / "invalid.yaml"
        with open(file_path, "w") as f:
            yaml.dump(manifest, f)
        # Create schema.avsc alongside
        (tmp_path / "schema.avsc").write_text(
            '{"type":"record","name":"T","fields":[]}'
        )
        errors = validate_manifest(file_path)
        assert len(errors) > 0

    def test_broken_yaml_stops_early(self, tmp_path):
        """Invalid YAML returns a syntax error immediately."""
        file_path = tmp_path / "broken.yaml"
        file_path.write_text("{{invalid yaml}}")
        errors = validate_manifest(file_path)
        assert len(errors) > 0
        assert "YAML syntax error" in errors[0]


# ═══════════════════════════════════════════════════════════════════════════
# find_all_manifests
# ═══════════════════════════════════════════════════════════════════════════


class TestFindAllManifests:
    """Tests for manifest discovery."""

    def test_finds_manifests_in_domains(self, tmp_path):
        domains = tmp_path / "examples" / "test" / "entity"
        domains.mkdir(parents=True)
        (domains / "manifest.yaml").write_text("spec_version: '1.0.0'")
        manifests = find_all_manifests(tmp_path)
        assert len(manifests) == 1

    def test_no_domains_directory(self, tmp_path):
        manifests = find_all_manifests(tmp_path)
        assert manifests == []
