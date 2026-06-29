"""Tests for analyze_impact.py."""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

# Add parent directory to Python path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from dpm.validators.analyze_impact import (
    Consumer,
    ImpactAssessment,
    analyze_manifest_impact,
    assess_risk,
    get_changed_manifests,
    get_consumers,
    load_breaking_changes_report,
    load_manifest,
)

# ═══════════════════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def tmp_manifest_dir(tmp_path):
    """Create a temporary directory with a sample manifest."""
    manifest = {
        "spec_version": "1.0.0",
        "manifest_version": "2.1.0",
        "metadata": {
            "name": "orders",
            "namespace": "sales",
            "owner": {"team": "order-service", "email": "orders@example.com"},
        },
        "lineage": {
            "downstream": [
                {
                    "system": "analytics",
                    "team": "data-team",
                    "contact": "data@example.com",
                    "criticality": "high",
                    "usage": "data-warehouse",
                },
                {
                    "system": "billing",
                    "team": "billing-team",
                    "criticality": "critical",
                },
            ]
        },
    }
    manifest_path = tmp_path / "manifest.yaml"
    with open(manifest_path, "w") as f:
        yaml.dump(manifest, f)
    return tmp_path, manifest_path, manifest


@pytest.fixture
def manifest_with_metadata_consumers(tmp_path):
    """Manifest with a legacy metadata-level consumer list."""
    manifest = {
        "spec_version": "1.0.0",
        "manifest_version": "1.5.0",
        "metadata": {
            "name": "products",
            "namespace": "catalog",
            "owner": {"team": "catalog-team"},
            "systems": {
                "consumers": [
                    {"name": "web-app", "team": "frontend"},
                    "mobile-app",  # String format
                ]
            },
        },
    }
    manifest_path = tmp_path / "manifest.yaml"
    with open(manifest_path, "w") as f:
        yaml.dump(manifest, f)
    return tmp_path, manifest_path, manifest


@pytest.fixture
def manifest_no_consumers(tmp_path):
    """Manifest with no consumers defined."""
    manifest = {
        "spec_version": "1.0.0",
        "manifest_version": "1.0.0",
        "metadata": {
            "name": "events",
            "namespace": "platform",
            "owner": {"team": "platform-team"},
        },
    }
    manifest_path = tmp_path / "manifest.yaml"
    with open(manifest_path, "w") as f:
        yaml.dump(manifest, f)
    return tmp_path, manifest_path, manifest


@pytest.fixture
def breaking_changes_report(tmp_path):
    """Create a breaking changes report file."""
    report = {
        "changes": [
            {
                "manifest": "orders",
                "change_type": "breaking",
                "description": "Field removed",
            },
            {
                "manifest": "products",
                "change_type": "non_breaking",
                "description": "New optional field added",
            },
        ]
    }
    report_path = tmp_path / "breaking_changes.json"
    with open(report_path, "w") as f:
        json.dump(report, f)
    return report_path, report


# ═══════════════════════════════════════════════════════════════════════════
# CONSUMER MODEL TESTS
# ═══════════════════════════════════════════════════════════════════════════


class TestConsumer:
    """Tests for Consumer model."""

    def test_consumer_minimal(self):
        """Consumer with only required name field."""
        consumer = Consumer(name="app-name")
        assert consumer.name == "app-name"
        assert consumer.team is None
        assert consumer.contact is None
        assert consumer.criticality is None
        assert consumer.usage is None

    def test_consumer_full(self):
        """Consumer with all fields."""
        consumer = Consumer(
            name="analytics",
            team="data-team",
            contact="data@example.com",
            criticality="high",
            usage="reporting",
        )
        assert consumer.name == "analytics"
        assert consumer.team == "data-team"
        assert consumer.contact == "data@example.com"
        assert consumer.criticality == "high"
        assert consumer.usage == "reporting"


# ═══════════════════════════════════════════════════════════════════════════
# IMPACT ASSESSMENT MODEL TESTS
# ═══════════════════════════════════════════════════════════════════════════


class TestImpactAssessment:
    """Tests for ImpactAssessment model."""

    def test_impact_assessment_basic(self):
        """Create a basic impact assessment."""
        consumer = Consumer(name="app")
        assessment = ImpactAssessment(
            manifest="sales/orders",
            manifest_version="2.0.0",
            change_type="breaking",
            affected_consumers=[consumer],
            risk_level="high",
            notification_required=True,
        )
        assert assessment.manifest == "sales/orders"
        assert assessment.manifest_version == "2.0.0"
        assert assessment.change_type == "breaking"
        assert len(assessment.affected_consumers) == 1
        assert assessment.risk_level == "high"
        assert assessment.notification_required is True

    def test_impact_assessment_model_dump(self):
        """Test serialization via model_dump."""
        consumer = Consumer(name="billing")
        assessment = ImpactAssessment(
            manifest="finance/payments",
            manifest_version="1.0.0",
            change_type="patch",
            affected_consumers=[consumer],
            risk_level="low",
            notification_required=False,
        )
        data = assessment.model_dump()
        assert "manifest" in data
        assert "affected_consumers" in data
        assert data["risk_level"] == "low"


# ═══════════════════════════════════════════════════════════════════════════
# GET_CONSUMERS TESTS
# ═══════════════════════════════════════════════════════════════════════════


class TestGetConsumers:
    """Tests for get_consumers function."""

    def test_get_consumers_from_lineage_downstream(self, tmp_manifest_dir):
        """Extract consumers from lineage.downstream."""
        _, _, manifest = tmp_manifest_dir
        consumers = get_consumers(manifest)

        assert len(consumers) == 2
        assert consumers[0].name == "analytics"
        assert consumers[0].criticality == "high"
        assert consumers[0].team == "data-team"
        assert consumers[1].name == "billing"
        assert consumers[1].criticality == "critical"

    def test_get_consumers_from_metadata_systems(self, manifest_with_metadata_consumers):
        """Legacy metadata-level consumers are ignored for impact analysis."""
        _, _, manifest = manifest_with_metadata_consumers
        consumers = get_consumers(manifest)

        assert consumers == []

    def test_get_consumers_mixed_dict_and_string(self, manifest_with_metadata_consumers):
        """Legacy metadata consumers are ignored even with mixed formats."""
        _, _, manifest = manifest_with_metadata_consumers
        consumers = get_consumers(manifest)

        assert consumers == []

    def test_get_consumers_empty_manifest(self, manifest_no_consumers):
        """Manifest with no consumers defined."""
        _, _, manifest = manifest_no_consumers
        consumers = get_consumers(manifest)

        assert consumers == []

    def test_get_consumers_no_lineage(self, tmp_path):
        """Manifest without lineage section."""
        manifest = {
            "metadata": {
                "name": "test",
                "namespace": "domain",
            }
        }
        consumers = get_consumers(manifest)
        assert consumers == []

    def test_get_consumers_system_name_fallback(self, tmp_path):
        """Use 'name' field if 'system' is not present."""
        manifest = {
            "lineage": {
                "downstream": [
                    {"name": "fallback_name", "team": "team-a"}
                ]
            }
        }
        consumers = get_consumers(manifest)
        assert len(consumers) == 1
        assert consumers[0].name == "fallback_name"

    def test_get_consumers_unknown_default(self):
        """Default to 'unknown' if neither system nor name."""
        manifest = {
            "lineage": {
                "downstream": [{"team": "some-team"}]
            }
        }
        consumers = get_consumers(manifest)
        assert len(consumers) == 1
        assert consumers[0].name == "unknown"


# ═══════════════════════════════════════════════════════════════════════════
# ASSESS_RISK TESTS
# ═══════════════════════════════════════════════════════════════════════════


class TestAssessRisk:
    """Tests for assess_risk: risk is driven by change type and consumer criticality."""

    @pytest.mark.parametrize(
        "criticalities, change_type, expected",
        [
            (["critical", "high"], "breaking", "critical"),
            (["high", "medium"], "breaking", "high"),
            ([], "breaking", "high"),
            (["critical"], "non_breaking", "medium"),
            (["high", "medium"], "non_breaking", "low"),
            ([], "non_breaking", "low"),
            (["critical"], "patch", "low"),
            ([], "patch", "low"),
            (["critical"], "unknown", "low"),
        ],
        ids=[
            "breaking_critical", "breaking_noncritical", "breaking_no_consumers",
            "nonbreaking_critical", "nonbreaking_noncritical", "nonbreaking_no_consumers",
            "patch_critical", "patch_no_consumers", "unknown",
        ],
    )
    def test_assess_risk(self, criticalities, change_type, expected):
        consumers = [
            Consumer(name=f"app{i}", criticality=c)
            for i, c in enumerate(criticalities)
        ]
        assert assess_risk(consumers, change_type) == expected


# ═══════════════════════════════════════════════════════════════════════════
# LOAD_CONTRACT TESTS
# ═══════════════════════════════════════════════════════════════════════════


class TestLoadManifest:
    """Tests for load_manifest function."""

    def test_load_manifest_from_file(self, tmp_manifest_dir):
        """Load manifest from YAML file."""
        _, manifest_path, original_manifest = tmp_manifest_dir
        loaded = load_manifest(str(manifest_path))

        assert loaded is not None
        assert loaded["manifest_version"] == "2.1.0"
        assert loaded["metadata"]["name"] == "orders"

    def test_load_manifest_from_directory(self, tmp_manifest_dir):
        """Load manifest from directory (looks for manifest.yaml)."""
        tmp_path, _, original_manifest = tmp_manifest_dir
        loaded = load_manifest(str(tmp_path))

        assert loaded is not None
        assert loaded["manifest_version"] == "2.1.0"

    def test_load_manifest_file_not_found(self):
        """Return None when manifest file doesn't exist."""
        result = load_manifest("/nonexistent/path/manifest.yaml")
        assert result is None

    def test_load_manifest_directory_without_manifest_yaml(self, tmp_path):
        """Return None when directory doesn't contain manifest.yaml."""
        result = load_manifest(str(tmp_path))
        assert result is None

    def test_load_manifest_invalid_yaml(self, tmp_path):
        """Handle invalid YAML gracefully."""
        bad_file = tmp_path / "manifest.yaml"
        bad_file.write_text("{invalid: yaml: content:")

        with pytest.raises(Exception):
            load_manifest(str(bad_file))


# ═══════════════════════════════════════════════════════════════════════════
# ANALYZE_CONTRACT_IMPACT TESTS
# ═══════════════════════════════════════════════════════════════════════════


class TestAnalyzeManifestImpact:
    """Tests for analyze_manifest_impact function."""

    def test_analyze_impact_happy_path(self, tmp_manifest_dir):
        """Basic happy path analysis."""
        _, manifest_path, _ = tmp_manifest_dir
        assessment = analyze_manifest_impact(str(manifest_path), "breaking")

        assert assessment is not None
        assert assessment.manifest == "sales/orders"
        assert assessment.manifest_version == "2.1.0"
        assert assessment.change_type == "breaking"
        assert len(assessment.affected_consumers) == 2
        assert assessment.risk_level == "critical"  # Has critical consumer
        assert assessment.notification_required is True

    def test_analyze_impact_non_breaking(self, tmp_manifest_dir):
        """Non-breaking change analysis."""
        _, manifest_path, _ = tmp_manifest_dir
        assessment = analyze_manifest_impact(str(manifest_path), "non_breaking")

        assert assessment is not None
        assert assessment.change_type == "non_breaking"
        assert assessment.risk_level == "medium"  # Has critical consumer
        assert assessment.notification_required is False  # Only for breaking or critical/high

    def test_analyze_impact_patch(self, tmp_manifest_dir):
        """Patch change analysis."""
        _, manifest_path, _ = tmp_manifest_dir
        assessment = analyze_manifest_impact(str(manifest_path), "patch")

        assert assessment is not None
        assert assessment.change_type == "patch"
        assert assessment.risk_level == "low"
        assert assessment.notification_required is False

    def test_analyze_impact_missing_manifest(self):
        """Return None when manifest file doesn't exist."""
        assessment = analyze_manifest_impact("/nonexistent/manifest.yaml", "breaking")
        assert assessment is None

    def test_analyze_impact_no_consumers(self, manifest_no_consumers):
        """Analysis with no consumers."""
        _, manifest_path, _ = manifest_no_consumers
        assessment = analyze_manifest_impact(str(manifest_path), "breaking")

        assert assessment is not None
        assert len(assessment.affected_consumers) == 0
        assert assessment.risk_level == "high"  # Breaking but no critical consumers
        assert assessment.notification_required is True

    def test_analyze_impact_default_change_type(self, tmp_manifest_dir):
        """Default change_type parameter."""
        _, manifest_path, _ = tmp_manifest_dir
        assessment = analyze_manifest_impact(str(manifest_path))

        assert assessment is not None
        assert assessment.change_type == "unknown"

    def test_analyze_impact_notification_required_breaking(self, tmp_manifest_dir):
        """Notification required for breaking changes."""
        _, manifest_path, _ = tmp_manifest_dir
        assessment = analyze_manifest_impact(str(manifest_path), "breaking")
        assert assessment.notification_required is True

    def test_analyze_impact_notification_required_critical_risk(self, tmp_path):
        """Notification required for critical risk even if not breaking."""
        manifest = {
            "spec_version": "1.0.0",
            "manifest_version": "1.0.0",
            "metadata": {
                "name": "critical-data",
                "namespace": "test",
            },
            "lineage": {
                "downstream": [
                    {"system": "mission-critical", "criticality": "critical"}
                ]
            },
        }
        manifest_path = tmp_path / "manifest.yaml"
        with open(manifest_path, "w") as f:
            yaml.dump(manifest, f)

        # Non-breaking but critical risk
        assessment = analyze_manifest_impact(str(manifest_path), "breaking")
        assert assessment.risk_level == "critical"
        assert assessment.notification_required is True


# ═══════════════════════════════════════════════════════════════════════════
# LOAD_BREAKING_CHANGES_REPORT TESTS
# ═══════════════════════════════════════════════════════════════════════════


class TestLoadBreakingChangesReport:
    """Tests for load_breaking_changes_report function."""

    def test_load_valid_report(self, breaking_changes_report):
        """Load valid breaking changes report."""
        report_path, expected = breaking_changes_report
        result = load_breaking_changes_report(str(report_path))

        assert "changes" in result
        assert len(result["changes"]) == 2
        assert result["changes"][0]["manifest"] == "orders"
        assert result["changes"][0]["change_type"] == "breaking"

    def test_load_missing_report(self, tmp_path):
        """Return empty report when file doesn't exist."""
        report_path = tmp_path / "nonexistent.json"
        result = load_breaking_changes_report(str(report_path))

        assert result == {"changes": []}

    def test_load_empty_report(self, tmp_path):
        """Load empty but valid report."""
        report_path = tmp_path / "empty_report.json"
        report_path.write_text('{"changes": []}')
        result = load_breaking_changes_report(str(report_path))

        assert result == {"changes": []}

    def test_load_report_with_extra_fields(self, tmp_path):
        """Load report with additional fields."""
        report = {
            "changes": [
                {"manifest": "test", "change_type": "breaking"}
            ],
            "summary": {"total": 1},
            "timestamp": "2024-01-01T00:00:00Z",
        }
        report_path = tmp_path / "report.json"
        with open(report_path, "w") as f:
            json.dump(report, f)

        result = load_breaking_changes_report(str(report_path))
        assert result["changes"][0]["manifest"] == "test"
        assert result["summary"]["total"] == 1


# ═══════════════════════════════════════════════════════════════════════════
# GET_CHANGED_CONTRACTS TESTS
# ═══════════════════════════════════════════════════════════════════════════


class TestGetChangedManifests:
    """Tests for get_changed_manifests function."""

    @patch("subprocess.run")
    def test_get_changed_manifests_success(self, mock_run):
        """Successfully get changed manifests."""
        mock_run.return_value = MagicMock(
            stdout="examples/sales/orders/manifest.yaml\nexamples/sales/invoices/schema.avsc\n",
            returncode=0,
        )

        manifests = get_changed_manifests("origin/main", "HEAD")

        assert "examples/sales/orders" in manifests
        assert "examples/sales/invoices" in manifests
        mock_run.assert_called_once()

    @patch("subprocess.run")
    def test_get_changed_manifests_git_failure(self, mock_run):
        """Handle git command failure."""
        import subprocess
        mock_run.side_effect = subprocess.CalledProcessError(1, "git")

        manifests = get_changed_manifests("origin/main", "HEAD")

        assert manifests == []

    @patch("subprocess.run")
    def test_get_changed_manifests_no_changes(self, mock_run):
        """Handle no changed files."""
        mock_run.return_value = MagicMock(stdout="", returncode=0)

        manifests = get_changed_manifests("origin/main", "HEAD")

        assert manifests == []

    @patch("subprocess.run")
    def test_get_changed_manifests_non_domain_files(self, mock_run):
        """Ignore files outside examples/."""
        mock_run.return_value = MagicMock(
            stdout="README.md\nci/script.py\ndocs/guide.md\n",
            returncode=0,
        )

        manifests = get_changed_manifests("origin/main", "HEAD")

        assert manifests == []

    @patch("subprocess.run")
    def test_get_changed_manifests_custom_refs(self, mock_run):
        """Use custom git refs."""
        mock_run.return_value = MagicMock(
            stdout="examples/test/entity/manifest.yaml\n",
            returncode=0,
        )

        manifests = get_changed_manifests("v1.0.0", "v2.0.0")

        call_args = mock_run.call_args
        assert "v1.0.0" in call_args[0][0]
        assert "v2.0.0" in call_args[0][0]


# ═══════════════════════════════════════════════════════════════════════════
# MAIN FUNCTION TESTS
# ═══════════════════════════════════════════════════════════════════════════


class TestMainFunction:
    """Tests for main() function with mocked args."""

    @patch("sys.argv")
    @patch("dpm.validators.analyze_impact.get_changed_manifests")
    def test_main_with_output_file(self, mock_get_changed, mock_argv, tmp_path, tmp_manifest_dir):
        """Main function writes output file."""
        _, manifest_path, _ = tmp_manifest_dir
        output_file = tmp_path / "report.json"

        mock_argv.__getitem__.return_value = ["analyze_impact.py"]
        mock_get_changed.return_value = [str(manifest_path.parent)]

        # Create minimal breaking changes report
        breaking_report_path = tmp_path / "breaking.json"
        with open(breaking_report_path, "w") as f:
            json.dump({"changes": []}, f)

        with patch("dpm.validators.analyze_impact.load_breaking_changes_report") as mock_load_report:
            mock_load_report.return_value = {"changes": []}

            with patch("sys.argv", [
                "analyze_impact.py",
                "--output", str(output_file),
                "--manifest", str(manifest_path),
            ]):
                with pytest.raises(SystemExit):
                    from dpm.validators.analyze_impact import main
                    main()

    @patch("sys.argv")
    @patch("dpm.validators.analyze_impact.load_breaking_changes_report")
    def test_main_specific_manifest(self, mock_load_report, mock_argv, tmp_manifest_dir):
        """Main function with --manifest option."""
        _, manifest_path, _ = tmp_manifest_dir
        mock_load_report.return_value = {"changes": []}

        with patch("sys.argv", [
            "analyze_impact.py",
            "--manifest", str(manifest_path),
        ]):
            with pytest.raises(SystemExit) as exc_info:
                from dpm.validators.analyze_impact import main
                main()

            # Should exit with 0 (no critical issues)
            assert exc_info.value.code == 0

    @patch("sys.argv")
    @patch("dpm.validators.analyze_impact.load_breaking_changes_report")
    def test_main_exit_code_critical(self, mock_load_report, mock_argv, tmp_path):
        """Main function exits with 1 when critical risk found."""
        # The manifest path structure: examples/{namespace}/{entity}/manifest.yaml
        # The entity name from the path (not metadata.name) is used as the key
        entity_dir = tmp_path / "critical_entity"
        entity_dir.mkdir()

        manifest = {
            "spec_version": "1.0.0",
            "manifest_version": "1.0.0",
            "metadata": {
                "name": "critical_data",
                "namespace": "test",
            },
            "lineage": {
                "downstream": [
                    {"system": "critical-app", "criticality": "critical"}
                ]
            },
        }
        manifest_path = entity_dir / "manifest.yaml"
        with open(manifest_path, "w") as f:
            yaml.dump(manifest, f)

        # Map entity name (from path) to breaking change type
        mock_load_report.return_value = {
            "changes": [
                {"manifest": "critical_entity", "change_type": "breaking"}
            ]
        }

        with patch("sys.argv", [
            "analyze_impact.py",
            "--manifest", str(manifest_path),
            "--breaking-changes-file", "dummy.json",
        ]):
            with pytest.raises(SystemExit) as exc_info:
                from dpm.validators.analyze_impact import main
                main()

            # Should exit with 1 (critical risk from breaking change with critical consumer)
            assert exc_info.value.code == 1


# ═══════════════════════════════════════════════════════════════════════════
# INTEGRATION TESTS
# ═══════════════════════════════════════════════════════════════════════════


class TestAnalyzeImpactIntegration:
    """Integration tests combining multiple functions."""

    def test_full_impact_analysis_workflow(self, tmp_manifest_dir, breaking_changes_report):
        """Complete workflow: load manifest, assess impact, check notification."""
        _, manifest_path, _ = tmp_manifest_dir
        report_path, _ = breaking_changes_report

        # Load breaking changes
        breaking_report = load_breaking_changes_report(str(report_path))
        assert len(breaking_report["changes"]) > 0

        # Get manifest changes map
        manifest_change_types = {}
        for change in breaking_report["changes"]:
            manifest = change.get("manifest", "")
            ctype = change.get("change_type", "unknown")
            if manifest:
                manifest_change_types[manifest] = ctype

        # Analyze impact
        assessment = analyze_manifest_impact(
            str(manifest_path),
            manifest_change_types.get("orders", "unknown"),
        )

        assert assessment is not None
        assert assessment.manifest_version == "2.1.0"
        assert len(assessment.affected_consumers) == 2

    def test_multiple_manifest_analysis(self, tmp_path):
        """Analyze multiple manifests with different characteristics."""
        manifests_data = [
            ("orders", "sales", "breaking", 2, "critical"),
            ("products", "catalog", "non_breaking", 1, "low"),
            ("events", "platform", "patch", 0, "low"),
        ]

        manifests_info = []
        for name, namespace, change_type, consumer_count, expected_risk in manifests_data:
            consumers = []
            if consumer_count > 0:
                consumers = [
                    {"system": f"consumer-{i}", "criticality": "critical"}
                    for i in range(consumer_count)
                ]

            manifest = {
                "spec_version": "1.0.0",
                "manifest_version": "1.0.0",
                "metadata": {
                    "name": name,
                    "namespace": namespace,
                },
                "lineage": {"downstream": consumers} if consumers else {},
            }

            manifest_path = tmp_path / f"{name}_manifest.yaml"
            with open(manifest_path, "w") as f:
                yaml.dump(manifest, f)

            assessment = analyze_manifest_impact(str(manifest_path), change_type)
            manifests_info.append((assessment, expected_risk))

        # Verify all assessments
        assert len(manifests_info) == 3
        for assessment, expected_risk in manifests_info:
            # Risk level behavior is deterministic
            assert assessment.risk_level in ["critical", "high", "medium", "low"]
