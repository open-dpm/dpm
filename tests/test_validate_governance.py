"""Tests for validate_governance.py."""

import json
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

from dpm.validators.validate_governance import (
    Finding,
    GovernanceValidator,
    Severity,
    ValidationReport,
)

# ═══════════════════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def validator(tmp_path):
    """Create a GovernanceValidator instance for testing."""
    return GovernanceValidator(manifests_base=tmp_path)


def _write_manifest(tmp_path, manifest_data):
    """Helper to write manifest YAML to file."""
    path = tmp_path / "manifest.yaml"
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(manifest_data, f)
    return path


def _minimal_valid_manifest():
    """
    Return a dict with all required fields filled in properly.

    This serves as the base for creating valid manifests with minimal fields.
    """
    return {
        "spec_version": "1.0.0",
        "manifest_version": "1.0.0",
        "metadata": {
            "name": "test_manifest",
            "namespace": "test_domain",
            "description": "This is a valid test manifest description",
            "owner": {
                "team": "test-team",
                "email": "team@example.com",
            },
            "pii": False,
            "tags": ["demo"],
            "systems": {"producer": "source-system"},
        },
        "schema": {"file": "schema.avsc"},
        "quality_rules": {"file": "rules.yaml"},
        "sla": {"file": "sla.md"},
        "lineage": {
            "upstream": ["source1"],
            "downstream": [
                {
                    "system": "consumer1",
                    "team": "consumer-team",
                    "contact": "consumer@example.com",
                    "objects": ["dashboards/consumer1"],
                }
            ],
        },
        "changelog": [
            {
                "version": "1.0.0",
                "date": "2024-01-01",
                "changes": ["Initial release"],
            },
        ],
    }


def _write_schema_with_pii_field(tmp_path):
    """Overwrite schema.avsc with a field annotated as PII."""
    schema_path = tmp_path / "schema.avsc"
    with open(schema_path, "w") as f:
        json.dump({
            "type": "record",
            "name": "TestRecord",
            "fields": [
                {"name": "id", "type": "string"},
                {"name": "email", "type": "string", "pii": True},
            ],
        }, f)


def _create_supporting_files(tmp_path):
    """Create supporting files (schema, rules, sla) that manifests reference."""
    # Create schema file
    schema_path = tmp_path / "schema.avsc"
    with open(schema_path, "w") as f:
        json.dump({
            "type": "record",
            "name": "TestRecord",
            "fields": [{"name": "id", "type": "string"}],
        }, f)

    # Create quality rules file
    rules_path = tmp_path / "rules.yaml"
    with open(rules_path, "w") as f:
        yaml.dump({"rules": [{"name": "test_rule", "condition": "not null"}]}, f)

    # Create SLA file
    sla_path = tmp_path / "sla.md"
    with open(sla_path, "w") as f:
        f.write("# SLA\n\nAvailability: 99.5%\n")


# ═══════════════════════════════════════════════════════════════════════════
# VERSION FIELD VALIDATION
# ═══════════════════════════════════════════════════════════════════════════


class TestVersionFieldValidation:
    """Tests for spec_version and manifest_version validation."""

    def test_missing_spec_version(self, validator, tmp_path):
        """Manifest without spec_version should produce ERROR finding."""
        manifest = _minimal_valid_manifest()
        del manifest["spec_version"]
        _create_supporting_files(tmp_path)

        manifest_path = _write_manifest(tmp_path, manifest)
        report = validator.validate_manifest(manifest_path)

        assert not report.passed
        assert report.error_count >= 1
        errors = [f for f in report.findings if f.rule == "version_spec"]
        assert len(errors) == 1
        assert errors[0].severity == Severity.ERROR
        assert "spec_version" in errors[0].message

    def test_missing_manifest_version(self, validator, tmp_path):
        """Manifest without manifest_version should produce ERROR finding."""
        manifest = _minimal_valid_manifest()
        del manifest["manifest_version"]
        _create_supporting_files(tmp_path)

        manifest_path = _write_manifest(tmp_path, manifest)
        report = validator.validate_manifest(manifest_path)

        assert not report.passed
        assert report.error_count >= 1
        errors = [f for f in report.findings if f.rule == "version_manifest"]
        assert len(errors) == 1
        assert errors[0].severity == Severity.ERROR

    def test_valid_semver_version(self, validator, tmp_path):
        """Manifest with valid SemVer version should pass version checks."""
        manifest = _minimal_valid_manifest()
        manifest["manifest_version"] = "2.3.4"
        _create_supporting_files(tmp_path)

        manifest_path = _write_manifest(tmp_path, manifest)
        report = validator.validate_manifest(manifest_path)

        semver_errors = [f for f in report.findings if f.rule == "version_semver"]
        assert len(semver_errors) == 0

    def test_invalid_semver_version(self, validator, tmp_path):
        """Manifest with invalid SemVer version should produce WARNING."""
        manifest = _minimal_valid_manifest()
        manifest["manifest_version"] = "1.2"  # Missing PATCH version
        _create_supporting_files(tmp_path)

        manifest_path = _write_manifest(tmp_path, manifest)
        report = validator.validate_manifest(manifest_path)

        warnings = [f for f in report.findings if f.rule == "version_semver"]
        assert len(warnings) == 1
        assert warnings[0].severity == Severity.WARNING
        assert "SemVer" in warnings[0].message


# ═══════════════════════════════════════════════════════════════════════════
# METADATA VALIDATION
# ═══════════════════════════════════════════════════════════════════════════


class TestMetadataValidation:
    """Tests for metadata field validation."""

    @pytest.mark.parametrize("field_name", ["name", "namespace", "description", "owner"])
    def test_missing_required_metadata_field(self, validator, tmp_path, field_name):
        """Each missing required metadata field is reported as an ERROR."""
        manifest = _minimal_valid_manifest()
        del manifest["metadata"][field_name]
        _create_supporting_files(tmp_path)

        manifest_path = _write_manifest(tmp_path, manifest)
        report = validator.validate_manifest(manifest_path)

        assert not report.passed
        errors = [
            f
            for f in report.findings
            if f.rule == "metadata_required" and field_name in f.path
        ]
        assert len(errors) == 1
        assert errors[0].severity == Severity.ERROR

    def test_short_description(self, validator, tmp_path):
        """Description shorter than 20 chars should produce WARNING."""
        manifest = _minimal_valid_manifest()
        manifest["metadata"]["description"] = "Short desc"
        _create_supporting_files(tmp_path)

        manifest_path = _write_manifest(tmp_path, manifest)
        report = validator.validate_manifest(manifest_path)

        warnings = [f for f in report.findings if f.rule == "metadata_description"]
        assert len(warnings) == 1
        assert warnings[0].severity == Severity.WARNING
        assert "too short" in warnings[0].message.lower()

    def test_description_exactly_20_chars(self, validator, tmp_path):
        """Description with exactly 20 chars should pass."""
        manifest = _minimal_valid_manifest()
        manifest["metadata"]["description"] = "A" * 20
        _create_supporting_files(tmp_path)

        manifest_path = _write_manifest(tmp_path, manifest)
        report = validator.validate_manifest(manifest_path)

        warnings = [f for f in report.findings if f.rule == "metadata_description"]
        assert len(warnings) == 0

    def test_missing_tags(self, validator, tmp_path):
        """Missing metadata.tags should produce WARNING."""
        manifest = _minimal_valid_manifest()
        del manifest["metadata"]["tags"]
        _create_supporting_files(tmp_path)

        manifest_path = _write_manifest(tmp_path, manifest)
        report = validator.validate_manifest(manifest_path)

        warnings = [f for f in report.findings if f.rule == "metadata_tags"]
        assert len(warnings) == 1
        assert warnings[0].severity == Severity.WARNING

    def test_empty_tags_list(self, validator, tmp_path):
        """Empty tags list should produce WARNING."""
        manifest = _minimal_valid_manifest()
        manifest["metadata"]["tags"] = []
        _create_supporting_files(tmp_path)

        manifest_path = _write_manifest(tmp_path, manifest)
        report = validator.validate_manifest(manifest_path)

        warnings = [f for f in report.findings if f.rule == "metadata_tags"]
        assert len(warnings) == 1
        assert warnings[0].severity == Severity.WARNING


# ═══════════════════════════════════════════════════════════════════════════
# OWNER VALIDATION
# ═══════════════════════════════════════════════════════════════════════════


class TestOwnerValidation:
    """Tests for owner field validation."""

    @pytest.mark.parametrize("field_name", ["team", "email"])
    def test_missing_required_owner_field(self, validator, tmp_path, field_name):
        """Each missing required owner field is reported as an ERROR."""
        manifest = _minimal_valid_manifest()
        del manifest["metadata"]["owner"][field_name]
        _create_supporting_files(tmp_path)

        manifest_path = _write_manifest(tmp_path, manifest)
        report = validator.validate_manifest(manifest_path)

        assert not report.passed
        errors = [
            f
            for f in report.findings
            if f.rule == "owner_required" and field_name in f.path
        ]
        assert len(errors) == 1
        assert errors[0].severity == Severity.ERROR

    def test_missing_mattermost_channel(self, validator, tmp_path):
        """Missing mattermost channel should produce WARNING (not error)."""
        manifest = _minimal_valid_manifest()
        # Don't include mattermost field
        if "mattermost" in manifest["metadata"]["owner"]:
            del manifest["metadata"]["owner"]["mattermost"]
        _create_supporting_files(tmp_path)

        manifest_path = _write_manifest(tmp_path, manifest)
        report = validator.validate_manifest(manifest_path)

        # Should still pass (WARNING, not ERROR)
        warnings = [f for f in report.findings if f.rule == "owner_mattermost"]
        assert len(warnings) == 1
        assert warnings[0].severity == Severity.WARNING

    def test_critical_manifest_without_oncall(self, validator, tmp_path):
        """Critical manifest without on_call should produce WARNING."""
        manifest = _minimal_valid_manifest()
        manifest["metadata"]["tags"] = ["critical", "no-pii"]
        # No on_call field
        _create_supporting_files(tmp_path)

        manifest_path = _write_manifest(tmp_path, manifest)
        report = validator.validate_manifest(manifest_path)

        warnings = [f for f in report.findings if f.rule == "owner_oncall"]
        assert len(warnings) == 1
        assert warnings[0].severity == Severity.WARNING

    def test_critical_manifest_with_oncall(self, validator, tmp_path):
        """Critical manifest with on_call should pass on_call check."""
        manifest = _minimal_valid_manifest()
        manifest["metadata"]["tags"] = ["critical", "no-pii"]
        manifest["metadata"]["owner"]["on_call"] = "https://example.com/oncall"
        _create_supporting_files(tmp_path)

        manifest_path = _write_manifest(tmp_path, manifest)
        report = validator.validate_manifest(manifest_path)

        warnings = [f for f in report.findings if f.rule == "owner_oncall"]
        assert len(warnings) == 0

    def test_non_critical_manifest_without_oncall(self, validator, tmp_path):
        """Non-critical manifest without on_call should not produce oncall warning."""
        manifest = _minimal_valid_manifest()
        # no-pii is not in critical tags
        _create_supporting_files(tmp_path)

        manifest_path = _write_manifest(tmp_path, manifest)
        report = validator.validate_manifest(manifest_path)

        warnings = [f for f in report.findings if f.rule == "owner_oncall"]
        assert len(warnings) == 0


# ═══════════════════════════════════════════════════════════════════════════
# PII TAGGING VALIDATION
# ═══════════════════════════════════════════════════════════════════════════


class TestPIIValidation:
    """Tests for the metadata.pii flag and its consistency with the schema."""

    def test_pii_false_passes(self, validator, tmp_path):
        """pii: false with no PII fields in the schema should pass."""
        manifest = _minimal_valid_manifest()
        manifest["metadata"]["pii"] = False
        _create_supporting_files(tmp_path)

        manifest_path = _write_manifest(tmp_path, manifest)
        report = validator.validate_manifest(manifest_path)

        pii_findings = [f for f in report.findings if f.rule.startswith("pii")]
        assert pii_findings == []

    def test_pii_true_with_pii_field_passes(self, validator, tmp_path):
        """pii: true with a PII-annotated schema field should pass."""
        manifest = _minimal_valid_manifest()
        manifest["metadata"]["pii"] = True
        _create_supporting_files(tmp_path)
        _write_schema_with_pii_field(tmp_path)

        manifest_path = _write_manifest(tmp_path, manifest)
        report = validator.validate_manifest(manifest_path)

        pii_findings = [f for f in report.findings if f.rule.startswith("pii")]
        assert pii_findings == []

    def test_missing_pii_flag(self, validator, tmp_path):
        """A manifest without metadata.pii should produce an ERROR."""
        manifest = _minimal_valid_manifest()
        manifest["metadata"].pop("pii", None)
        _create_supporting_files(tmp_path)

        manifest_path = _write_manifest(tmp_path, manifest)
        report = validator.validate_manifest(manifest_path)

        assert not report.passed
        errors = [f for f in report.findings if f.rule == "pii_flag"]
        assert len(errors) == 1
        assert errors[0].severity == Severity.ERROR

    def test_pii_not_boolean(self, validator, tmp_path):
        """A non-boolean metadata.pii should produce an ERROR."""
        manifest = _minimal_valid_manifest()
        manifest["metadata"]["pii"] = "yes"
        _create_supporting_files(tmp_path)

        manifest_path = _write_manifest(tmp_path, manifest)
        report = validator.validate_manifest(manifest_path)

        assert not report.passed
        errors = [f for f in report.findings if f.rule == "pii_flag"]
        assert len(errors) == 1
        assert errors[0].severity == Severity.ERROR

    def test_pii_false_but_schema_has_pii_field(self, validator, tmp_path):
        """pii: false while the schema marks a field as PII is a conflict ERROR."""
        manifest = _minimal_valid_manifest()
        manifest["metadata"]["pii"] = False
        _create_supporting_files(tmp_path)
        _write_schema_with_pii_field(tmp_path)

        manifest_path = _write_manifest(tmp_path, manifest)
        report = validator.validate_manifest(manifest_path)

        assert not report.passed
        errors = [f for f in report.findings if f.rule == "pii_conflict"]
        assert len(errors) == 1
        assert errors[0].severity == Severity.ERROR

    def test_pii_true_but_no_pii_field_warns(self, validator, tmp_path):
        """pii: true with no PII-annotated field produces a WARNING."""
        manifest = _minimal_valid_manifest()
        manifest["metadata"]["pii"] = True
        _create_supporting_files(tmp_path)

        manifest_path = _write_manifest(tmp_path, manifest)
        report = validator.validate_manifest(manifest_path)

        warnings = [f for f in report.findings if f.rule == "pii_unmarked_fields"]
        assert len(warnings) == 1
        assert warnings[0].severity == Severity.WARNING


# ═══════════════════════════════════════════════════════════════════════════
# SCHEMA VALIDATION
# ═══════════════════════════════════════════════════════════════════════════


class TestSchemaValidation:
    """Tests for schema reference validation."""

    def test_missing_schema_file_reference(self, validator, tmp_path):
        """Manifest without schema.file should produce ERROR."""
        manifest = _minimal_valid_manifest()
        del manifest["schema"]
        _create_supporting_files(tmp_path)

        manifest_path = _write_manifest(tmp_path, manifest)
        report = validator.validate_manifest(manifest_path)

        assert not report.passed
        errors = [f for f in report.findings if f.rule == "schema_reference"]
        assert len(errors) == 1
        assert errors[0].severity == Severity.ERROR

    def test_schema_file_not_found(self, validator, tmp_path):
        """Manifest with non-existent schema file should produce ERROR."""
        manifest = _minimal_valid_manifest()
        manifest["schema"]["file"] = "nonexistent_schema.avsc"
        _create_supporting_files(tmp_path)

        manifest_path = _write_manifest(tmp_path, manifest)
        report = validator.validate_manifest(manifest_path)

        assert not report.passed
        errors = [f for f in report.findings if f.rule == "schema_exists"]
        assert len(errors) == 1
        assert errors[0].severity == Severity.ERROR
        assert "not found" in errors[0].message

    def test_schema_file_exists(self, validator, tmp_path):
        """Manifest with existing schema file should pass schema checks."""
        manifest = _minimal_valid_manifest()
        _create_supporting_files(tmp_path)

        manifest_path = _write_manifest(tmp_path, manifest)
        report = validator.validate_manifest(manifest_path)

        errors = [f for f in report.findings if f.rule in ["schema_reference", "schema_exists"]]
        assert len(errors) == 0


# ═══════════════════════════════════════════════════════════════════════════
# QUALITY RULES VALIDATION
# ═══════════════════════════════════════════════════════════════════════════


class TestQualityRulesValidation:
    """Tests for quality rules validation."""

    def test_missing_quality_rules_file_reference(self, validator, tmp_path):
        """Manifest without quality_rules.file should produce WARNING."""
        manifest = _minimal_valid_manifest()
        del manifest["quality_rules"]
        _create_supporting_files(tmp_path)

        manifest_path = _write_manifest(tmp_path, manifest)
        report = validator.validate_manifest(manifest_path)

        warnings = [f for f in report.findings if f.rule == "quality_rules_reference"]
        assert len(warnings) == 1
        assert warnings[0].severity == Severity.WARNING

    def test_pii_manifest_without_quality_rules(self, validator, tmp_path):
        """PII manifest without quality_rules should still produce WARNING (not error)."""
        manifest = _minimal_valid_manifest()
        manifest["metadata"]["pii"] = True
        del manifest["quality_rules"]
        _create_supporting_files(tmp_path)

        manifest_path = _write_manifest(tmp_path, manifest)
        report = validator.validate_manifest(manifest_path)

        warnings = [f for f in report.findings if f.rule == "quality_rules_reference"]
        assert len(warnings) == 1
        assert warnings[0].severity == Severity.WARNING

    def test_quality_rules_file_not_found(self, validator, tmp_path):
        """Manifest with non-existent quality_rules file should produce ERROR."""
        manifest = _minimal_valid_manifest()
        manifest["quality_rules"]["file"] = "nonexistent_rules.yaml"
        _create_supporting_files(tmp_path)

        manifest_path = _write_manifest(tmp_path, manifest)
        report = validator.validate_manifest(manifest_path)

        assert not report.passed
        errors = [f for f in report.findings if f.rule == "quality_rules_exists"]
        assert len(errors) == 1
        assert errors[0].severity == Severity.ERROR

    def test_quality_rules_file_empty(self, validator, tmp_path):
        """Quality rules file with no rules should produce WARNING."""
        manifest = _minimal_valid_manifest()
        _create_supporting_files(tmp_path)

        # Create empty rules file
        rules_path = tmp_path / "rules.yaml"
        with open(rules_path, "w") as f:
            yaml.dump({"rules": []}, f)

        manifest_path = _write_manifest(tmp_path, manifest)
        report = validator.validate_manifest(manifest_path)

        warnings = [f for f in report.findings if f.rule == "quality_rules_empty"]
        assert len(warnings) == 1
        assert warnings[0].severity == Severity.WARNING

    def test_quality_rules_file_exists(self, validator, tmp_path):
        """Manifest with valid quality_rules file should pass checks."""
        manifest = _minimal_valid_manifest()
        _create_supporting_files(tmp_path)

        manifest_path = _write_manifest(tmp_path, manifest)
        report = validator.validate_manifest(manifest_path)

        errors = [f for f in report.findings if f.rule in ["quality_rules_reference", "quality_rules_exists"]]
        assert len(errors) == 0


# ═══════════════════════════════════════════════════════════════════════════
# SLA VALIDATION
# ═══════════════════════════════════════════════════════════════════════════


class TestSLAValidation:
    """Tests for SLA validation."""

    def test_missing_sla_file_reference(self, validator, tmp_path):
        """Manifest without sla.file should produce INFO (lowest severity)."""
        manifest = _minimal_valid_manifest()
        del manifest["sla"]
        _create_supporting_files(tmp_path)

        manifest_path = _write_manifest(tmp_path, manifest)
        report = validator.validate_manifest(manifest_path)

        # Report should still pass (INFO severity)
        assert report.passed
        infos = [f for f in report.findings if f.rule == "sla_reference"]
        assert len(infos) == 1
        assert infos[0].severity == Severity.INFO

    def test_sla_file_not_found(self, validator, tmp_path):
        """Manifest with non-existent SLA file should produce WARNING."""
        manifest = _minimal_valid_manifest()
        manifest["sla"]["file"] = "nonexistent_sla.md"
        _create_supporting_files(tmp_path)

        manifest_path = _write_manifest(tmp_path, manifest)
        report = validator.validate_manifest(manifest_path)

        # Should still pass (WARNING severity)
        assert report.passed
        warnings = [f for f in report.findings if f.rule == "sla_exists"]
        assert len(warnings) == 1
        assert warnings[0].severity == Severity.WARNING

    def test_sla_file_exists(self, validator, tmp_path):
        """Manifest with existing SLA file should pass SLA checks."""
        manifest = _minimal_valid_manifest()
        _create_supporting_files(tmp_path)

        manifest_path = _write_manifest(tmp_path, manifest)
        report = validator.validate_manifest(manifest_path)

        errors = [f for f in report.findings if f.rule in ["sla_reference", "sla_exists"]]
        assert len(errors) == 0


# ═══════════════════════════════════════════════════════════════════════════
# LINEAGE VALIDATION
# ═══════════════════════════════════════════════════════════════════════════


class TestLineageValidation:
    """Tests for lineage validation."""

    def test_missing_lineage(self, validator, tmp_path):
        """Manifest without lineage should produce WARNING."""
        manifest = _minimal_valid_manifest()
        del manifest["lineage"]
        _create_supporting_files(tmp_path)

        manifest_path = _write_manifest(tmp_path, manifest)
        report = validator.validate_manifest(manifest_path)

        # Should still pass (WARNING severity)
        assert report.passed
        warnings = [f for f in report.findings if f.rule == "lineage_missing"]
        assert len(warnings) == 1
        assert warnings[0].severity == Severity.WARNING

    def test_missing_upstream_lineage(self, validator, tmp_path):
        """Manifest without upstream lineage should produce WARNING."""
        manifest = _minimal_valid_manifest()
        manifest["lineage"] = {
            "downstream": [
                {
                    "system": "consumer1",
                    "team": "consumer-team",
                    "contact": "consumer@example.com",
                    "objects": ["dashboards/consumer1"],
                }
            ]
        }
        _create_supporting_files(tmp_path)

        manifest_path = _write_manifest(tmp_path, manifest)
        report = validator.validate_manifest(manifest_path)

        assert report.passed
        warnings = [f for f in report.findings if f.rule == "lineage_upstream"]
        assert len(warnings) == 1
        assert warnings[0].severity == Severity.WARNING

    def test_missing_downstream_lineage(self, validator, tmp_path):
        """Manifest without downstream lineage should produce INFO."""
        manifest = _minimal_valid_manifest()
        manifest["lineage"] = {"upstream": ["source1"]}
        _create_supporting_files(tmp_path)

        manifest_path = _write_manifest(tmp_path, manifest)
        report = validator.validate_manifest(manifest_path)

        assert report.passed
        infos = [f for f in report.findings if f.rule == "lineage_downstream"]
        assert len(infos) == 1
        assert infos[0].severity == Severity.INFO

    def test_complete_lineage(self, validator, tmp_path):
        """Manifest with both upstream and downstream should pass lineage checks."""
        manifest = _minimal_valid_manifest()
        _create_supporting_files(tmp_path)

        manifest_path = _write_manifest(tmp_path, manifest)
        report = validator.validate_manifest(manifest_path)

        errors = [f for f in report.findings if "lineage" in f.rule]
        assert len(errors) == 0


# ═══════════════════════════════════════════════════════════════════════════
# CHANGELOG VALIDATION
# ═══════════════════════════════════════════════════════════════════════════


class TestChangelogValidation:
    """Tests for changelog validation."""

    def test_missing_changelog(self, validator, tmp_path):
        """Manifest without changelog should produce WARNING."""
        manifest = _minimal_valid_manifest()
        del manifest["changelog"]
        _create_supporting_files(tmp_path)

        manifest_path = _write_manifest(tmp_path, manifest)
        report = validator.validate_manifest(manifest_path)

        assert report.passed
        warnings = [f for f in report.findings if f.rule == "changelog_missing"]
        assert len(warnings) == 1
        assert warnings[0].severity == Severity.WARNING

    def test_empty_changelog(self, validator, tmp_path):
        """Manifest with empty changelog should produce WARNING."""
        manifest = _minimal_valid_manifest()
        manifest["changelog"] = []
        _create_supporting_files(tmp_path)

        manifest_path = _write_manifest(tmp_path, manifest)
        report = validator.validate_manifest(manifest_path)

        assert report.passed
        warnings = [f for f in report.findings if f.rule == "changelog_missing"]
        assert len(warnings) == 1
        assert warnings[0].severity == Severity.WARNING

    def test_changelog_version_mismatch(self, validator, tmp_path):
        """Changelog latest version not matching manifest version should produce WARNING."""
        manifest = _minimal_valid_manifest()
        manifest["manifest_version"] = "2.0.0"
        manifest["changelog"] = [
            {"version": "1.0.0", "date": "2024-01-01", "changes": ["Old version"]},
        ]
        _create_supporting_files(tmp_path)

        manifest_path = _write_manifest(tmp_path, manifest)
        report = validator.validate_manifest(manifest_path)

        assert report.passed
        warnings = [f for f in report.findings if f.rule == "changelog_version_mismatch"]
        assert len(warnings) == 1
        assert warnings[0].severity == Severity.WARNING
        assert "2.0.0" in warnings[0].message
        assert "1.0.0" in warnings[0].message

    def test_changelog_version_matches(self, validator, tmp_path):
        """Changelog latest version matching manifest version should pass."""
        manifest = _minimal_valid_manifest()
        manifest["manifest_version"] = "1.0.0"
        manifest["changelog"] = [
            {"version": "1.0.0", "date": "2024-01-01", "changes": ["Initial"]},
        ]
        _create_supporting_files(tmp_path)

        manifest_path = _write_manifest(tmp_path, manifest)
        report = validator.validate_manifest(manifest_path)

        assert report.passed
        errors = [f for f in report.findings if f.rule == "changelog_version_mismatch"]
        assert len(errors) == 0


# ═══════════════════════════════════════════════════════════════════════════
# CRITICAL CONTRACT VALIDATION
# ═══════════════════════════════════════════════════════════════════════════


class TestCriticalManifestValidation:
    """Tests for critical manifest requirements."""

    def test_critical_manifest_without_runbook(self, validator, tmp_path):
        """Critical manifest without runbook should produce ERROR."""
        manifest = _minimal_valid_manifest()
        manifest["metadata"]["tags"] = ["critical", "no-pii"]
        # Don't include runbook
        _create_supporting_files(tmp_path)

        manifest_path = _write_manifest(tmp_path, manifest)
        report = validator.validate_manifest(manifest_path)

        assert not report.passed
        errors = [f for f in report.findings if f.rule == "critical_runbook"]
        assert len(errors) == 1
        assert errors[0].severity == Severity.ERROR

    def test_tier1_manifest_without_runbook(self, validator, tmp_path):
        """Tier-1 manifest without runbook should produce ERROR."""
        manifest = _minimal_valid_manifest()
        manifest["metadata"]["tags"] = ["tier-1", "no-pii"]
        _create_supporting_files(tmp_path)

        manifest_path = _write_manifest(tmp_path, manifest)
        report = validator.validate_manifest(manifest_path)

        assert not report.passed
        errors = [f for f in report.findings if f.rule == "critical_runbook"]
        assert len(errors) == 1
        assert errors[0].severity == Severity.ERROR

    def test_critical_manifest_with_runbook(self, validator, tmp_path):
        """Critical manifest with runbook reference should pass runbook check."""
        manifest = _minimal_valid_manifest()
        manifest["metadata"]["tags"] = ["critical", "no-pii"]
        manifest["runbook"] = {"file": "runbook.md"}
        _create_supporting_files(tmp_path)

        # Create runbook file
        runbook_path = tmp_path / "runbook.md"
        with open(runbook_path, "w") as f:
            f.write("# Runbook\n")

        manifest_path = _write_manifest(tmp_path, manifest)
        report = validator.validate_manifest(manifest_path)

        errors = [f for f in report.findings if f.rule == "critical_runbook"]
        assert len(errors) == 0

    def test_critical_manifest_without_downstream(self, validator, tmp_path):
        """Critical manifest without downstream consumers should produce WARNING."""
        manifest = _minimal_valid_manifest()
        manifest["metadata"]["tags"] = ["critical", "no-pii"]
        manifest["runbook"] = {"file": "runbook.md"}
        manifest["lineage"]["downstream"] = []
        _create_supporting_files(tmp_path)

        # Create runbook file
        runbook_path = tmp_path / "runbook.md"
        with open(runbook_path, "w") as f:
            f.write("# Runbook\n")

        manifest_path = _write_manifest(tmp_path, manifest)
        report = validator.validate_manifest(manifest_path)

        # Should still pass (WARNING)
        assert report.passed
        warnings = [f for f in report.findings if f.rule == "critical_consumers"]
        assert len(warnings) == 1
        assert warnings[0].severity == Severity.WARNING

    def test_critical_manifest_with_downstream(self, validator, tmp_path):
        """Critical manifest with downstream documented should pass consumers check."""
        manifest = _minimal_valid_manifest()
        manifest["metadata"]["tags"] = ["critical", "no-pii"]
        manifest["runbook"] = {"file": "runbook.md"}
        _create_supporting_files(tmp_path)

        # Create runbook file
        runbook_path = tmp_path / "runbook.md"
        with open(runbook_path, "w") as f:
            f.write("# Runbook\n")

        manifest_path = _write_manifest(tmp_path, manifest)
        report = validator.validate_manifest(manifest_path)

        warnings = [f for f in report.findings if f.rule == "critical_consumers"]
        assert len(warnings) == 0

    def test_non_critical_manifest_no_runbook_required(self, validator, tmp_path):
        """Non-critical manifest without runbook should not produce error."""
        manifest = _minimal_valid_manifest()
        # tags is just ["no-pii"], not critical
        _create_supporting_files(tmp_path)

        manifest_path = _write_manifest(tmp_path, manifest)
        report = validator.validate_manifest(manifest_path)

        errors = [f for f in report.findings if f.rule == "critical_runbook"]
        assert len(errors) == 0


# ═══════════════════════════════════════════════════════════════════════════
# VALIDATION REPORT DATA STRUCTURE
# ═══════════════════════════════════════════════════════════════════════════


class TestValidationReportStructure:
    """Tests for ValidationReport dataclass and properties."""

    def test_report_initialization(self):
        """ValidationReport should initialize with defaults."""
        report = ValidationReport(manifest_path="/path/to/manifest.yaml")

        assert report.manifest_path == "/path/to/manifest.yaml"
        assert report.findings == []
        assert report.passed is True
        assert report.error_count == 0
        assert report.warning_count == 0
        assert report.info_count == 0

    def test_add_error_finding_changes_passed_status(self):
        """Adding an ERROR finding should set passed to False."""
        report = ValidationReport(manifest_path="/path/to/manifest.yaml")

        finding = Finding(
            rule="test_rule",
            severity=Severity.ERROR,
            message="Test error",
        )
        report.add_finding(finding)

        assert not report.passed
        assert report.error_count == 1

    def test_add_warning_finding_keeps_passed_status(self):
        """Adding a WARNING finding should keep passed as True."""
        report = ValidationReport(manifest_path="/path/to/manifest.yaml")

        finding = Finding(
            rule="test_rule",
            severity=Severity.WARNING,
            message="Test warning",
        )
        report.add_finding(finding)

        assert report.passed
        assert report.warning_count == 1

    def test_add_info_finding_keeps_passed_status(self):
        """Adding an INFO finding should keep passed as True."""
        report = ValidationReport(manifest_path="/path/to/manifest.yaml")

        finding = Finding(
            rule="test_rule",
            severity=Severity.INFO,
            message="Test info",
        )
        report.add_finding(finding)

        assert report.passed
        assert report.info_count == 1

    def test_error_count_property(self):
        """error_count should count only ERROR findings."""
        report = ValidationReport(manifest_path="/path/to/manifest.yaml")

        report.add_finding(Finding(rule="r1", severity=Severity.ERROR, message="e1"))
        report.add_finding(Finding(rule="r2", severity=Severity.ERROR, message="e2"))
        report.add_finding(Finding(rule="r3", severity=Severity.WARNING, message="w1"))
        report.add_finding(Finding(rule="r4", severity=Severity.INFO, message="i1"))

        assert report.error_count == 2

    def test_warning_count_property(self):
        """warning_count should count only WARNING findings."""
        report = ValidationReport(manifest_path="/path/to/manifest.yaml")

        report.add_finding(Finding(rule="r1", severity=Severity.ERROR, message="e1"))
        report.add_finding(Finding(rule="r2", severity=Severity.WARNING, message="w1"))
        report.add_finding(Finding(rule="r3", severity=Severity.WARNING, message="w2"))
        report.add_finding(Finding(rule="r4", severity=Severity.INFO, message="i1"))

        assert report.warning_count == 2

    def test_info_count_property(self):
        """info_count should count only INFO findings."""
        report = ValidationReport(manifest_path="/path/to/manifest.yaml")

        report.add_finding(Finding(rule="r1", severity=Severity.ERROR, message="e1"))
        report.add_finding(Finding(rule="r2", severity=Severity.WARNING, message="w1"))
        report.add_finding(Finding(rule="r3", severity=Severity.INFO, message="i1"))
        report.add_finding(Finding(rule="r4", severity=Severity.INFO, message="i2"))

        assert report.info_count == 2

    def test_finding_structure(self):
        """Finding should support all required fields."""
        finding = Finding(
            rule="test_rule",
            severity=Severity.ERROR,
            message="Test message",
            path="metadata.name",
            suggestion="Add the field",
        )

        assert finding.rule == "test_rule"
        assert finding.severity == Severity.ERROR
        assert finding.message == "Test message"
        assert finding.path == "metadata.name"
        assert finding.suggestion == "Add the field"

    def test_finding_default_path_and_suggestion(self):
        """Finding should have default empty path and suggestion."""
        finding = Finding(
            rule="test_rule",
            severity=Severity.WARNING,
            message="Test message",
        )

        assert finding.path == ""
        assert finding.suggestion == ""


# ═══════════════════════════════════════════════════════════════════════════
# PARSE ERROR HANDLING
# ═══════════════════════════════════════════════════════════════════════════


class TestParseErrorHandling:
    """Tests for handling manifest file parsing errors."""

    def test_invalid_yaml_produces_error(self, validator, tmp_path):
        """Manifest with invalid YAML should produce ERROR finding."""
        bad_yaml_path = tmp_path / "manifest.yaml"
        with open(bad_yaml_path, "w") as f:
            f.write("metadata:\n  - item1\n item2\n")  # Invalid indentation

        report = validator.validate_manifest(bad_yaml_path)

        assert not report.passed
        assert report.error_count >= 1
        errors = [f for f in report.findings if f.rule == "parse_manifest"]
        assert len(errors) == 1
        assert errors[0].severity == Severity.ERROR
        assert "parsing" in errors[0].message.lower()

    def test_missing_manifest_file(self, validator, tmp_path):
        """Non-existent manifest file should produce ERROR."""
        missing_path = tmp_path / "missing.yaml"

        report = validator.validate_manifest(missing_path)

        assert not report.passed
        errors = [f for f in report.findings if f.rule == "parse_manifest"]
        assert len(errors) == 1
        assert errors[0].severity == Severity.ERROR


# ═══════════════════════════════════════════════════════════════════════════
# INTEGRATION TESTS
# ═══════════════════════════════════════════════════════════════════════════


class TestIntegration:
    """Integration tests for complete manifest validation."""

    def test_valid_minimal_manifest(self, validator, tmp_path):
        """Minimal valid manifest should pass all checks."""
        manifest = _minimal_valid_manifest()
        _create_supporting_files(tmp_path)

        manifest_path = _write_manifest(tmp_path, manifest)
        report = validator.validate_manifest(manifest_path)

        assert report.passed
        assert report.error_count == 0
        # May have info about missing things, but no errors or warnings
        errors = [f for f in report.findings if f.severity == Severity.ERROR]
        assert len(errors) == 0

    def test_manifest_with_multiple_errors(self, validator, tmp_path):
        """Manifest with multiple errors should report all of them."""
        manifest = {
            # Missing spec_version
            "manifest_version": "1.0.0",
            "metadata": {
                # Missing name, namespace, description
                "owner": {
                    # Missing team and email
                },
                # Missing tags (PII status)
            },
            # Missing schema
        }
        _create_supporting_files(tmp_path)

        manifest_path = _write_manifest(tmp_path, manifest)
        report = validator.validate_manifest(manifest_path)

        assert not report.passed
        assert report.error_count >= 5  # Multiple missing required fields

    def test_manifest_with_mixed_severities(self, validator, tmp_path):
        """Manifest should report errors, warnings, and info separately."""
        manifest = _minimal_valid_manifest()
        manifest["metadata"]["description"] = "Short"  # Too short -> WARNING
        manifest["lineage"] = {"upstream": []}  # Missing downstream -> INFO
        del manifest["sla"]  # Missing SLA -> INFO
        _create_supporting_files(tmp_path)

        manifest_path = _write_manifest(tmp_path, manifest)
        report = validator.validate_manifest(manifest_path)

        assert report.passed
        assert report.error_count == 0
        assert report.warning_count > 0
        assert report.info_count > 0
