"""Tests for suggest_version.py."""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

# Add parent directory to Python path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from dpm.lib.common import bump_version, parse_version
from dpm.validators.suggest_version import (
    VersionSuggestion,
    determine_bump_type,
    get_changed_manifests,
    load_breaking_changes,
    suggest_for_manifest,
)

# ═══════════════════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def manifest_v1_0_0(tmp_path):
    """Manifest at version 1.0.0."""
    manifest = {
        "spec_version": "1.0.0",
        "manifest_version": "1.0.0",
        "metadata": {
            "name": "orders",
            "namespace": "sales",
            "owner": {"team": "order-team"},
        },
        "schema": {"format": "avro", "fields": []},
    }
    manifest_path = tmp_path / "manifest.yaml"
    with open(manifest_path, "w") as f:
        yaml.dump(manifest, f)
    return tmp_path, manifest_path, manifest


@pytest.fixture
def manifest_v2_1_5(tmp_path):
    """Manifest at version 2.1.5."""
    manifest = {
        "spec_version": "1.0.0",
        "manifest_version": "2.1.5",
        "metadata": {
            "name": "products",
            "namespace": "catalog",
            "owner": {"team": "catalog-team"},
        },
        "schema": {"format": "avro", "fields": []},
    }
    manifest_path = tmp_path / "manifest.yaml"
    with open(manifest_path, "w") as f:
        yaml.dump(manifest, f)
    return tmp_path, manifest_path, manifest


@pytest.fixture
def breaking_changes_report(tmp_path):
    """Fixture for breaking changes report."""
    report = {
        "changes": [
            {
                "manifest": "orders",
                "change_type": "breaking",
                "description": "Field 'customer_id' removed",
            },
            {
                "manifest": "products",
                "change_type": "non_breaking",
                "description": "Added optional field 'sku'",
            },
            {
                "manifest": "inventory",
                "change_type": "patch",
                "description": "Updated documentation",
            },
        ]
    }
    report_path = tmp_path / "breaking_changes.json"
    with open(report_path, "w") as f:
        json.dump(report, f)
    return report_path, report


@pytest.fixture
def empty_breaking_changes_report(tmp_path):
    """Fixture for empty breaking changes report."""
    report = {"changes": [], "has_breaking_changes": False}
    report_path = tmp_path / "empty_report.json"
    with open(report_path, "w") as f:
        json.dump(report, f)
    return report_path, report


# ═══════════════════════════════════════════════════════════════════════════
# VERSION SUGGESTION MODEL TESTS
# ═══════════════════════════════════════════════════════════════════════════


class TestVersionSuggestion:
    """Tests for VersionSuggestion model."""

    def test_version_suggestion_creation(self):
        """Create a basic version suggestion."""
        suggestion = VersionSuggestion(
            manifest="sales/orders",
            current_version="1.0.0",
            suggested_version="2.0.0",
            bump_type="major",
            reasons=["Field removed"],
        )
        assert suggestion.manifest == "sales/orders"
        assert suggestion.current_version == "1.0.0"
        assert suggestion.suggested_version == "2.0.0"
        assert suggestion.bump_type == "major"
        assert len(suggestion.reasons) == 1

    def test_version_suggestion_no_bump(self):
        """Version suggestion with no bump needed."""
        suggestion = VersionSuggestion(
            manifest="catalog/products",
            current_version="1.5.0",
            suggested_version="1.5.0",
            bump_type="none",
            reasons=["Version already bumped"],
        )
        assert suggestion.bump_type == "none"
        assert suggestion.suggested_version == suggestion.current_version

    def test_version_suggestion_multiple_reasons(self):
        """Version suggestion with multiple reasons."""
        reasons = [
            "Field removed",
            "Type changed from string to int",
            "Required field added",
        ]
        suggestion = VersionSuggestion(
            manifest="sales/orders",
            current_version="1.0.0",
            suggested_version="2.0.0",
            bump_type="major",
            reasons=reasons,
        )
        assert len(suggestion.reasons) == 3
        assert suggestion.reasons == reasons

    def test_version_suggestion_model_dump(self):
        """Test serialization via model_dump."""
        suggestion = VersionSuggestion(
            manifest="sales/orders",
            current_version="1.0.0",
            suggested_version="2.0.0",
            bump_type="major",
            reasons=["Breaking change"],
        )
        data = suggestion.model_dump()
        assert "manifest" in data
        assert "current_version" in data
        assert "suggested_version" in data
        assert "bump_type" in data
        assert "reasons" in data


# ═══════════════════════════════════════════════════════════════════════════
# PARSE_VERSION TESTS (from lib.common)
# ═══════════════════════════════════════════════════════════════════════════


class TestParseVersion:
    """Tests for parse_version from lib.common."""

    @pytest.mark.parametrize(
        "version, expected",
        [
            ("1.2.3", (1, 2, 3)),
            ("1.2.3-alpha", (1, 2, 3)),
            ("2.1.0+build123", (2, 1, 0)),
            ("invalid", (0, 0, 0)),
            ("1", (0, 0, 0)),
            ("1.2", (0, 0, 0)),
        ],
        ids=[
            "semver", "prerelease", "build_metadata",
            "invalid", "single_digit", "two_digits",
        ],
    )
    def test_parse_version(self, version, expected):
        assert parse_version(version) == expected


# ═══════════════════════════════════════════════════════════════════════════
# BUMP_VERSION TESTS (from lib.common)
# ═══════════════════════════════════════════════════════════════════════════


class TestBumpVersion:
    """Tests for bump_version from lib.common."""

    @pytest.mark.parametrize(
        "version, bump, expected",
        [
            ("1.2.3", "major", "2.0.0"),
            ("1.2.3", "minor", "1.3.0"),
            ("1.2.3", "patch", "1.2.4"),
            ("0.5.0", "major", "1.0.0"),
            ("0.0.5", "minor", "0.1.0"),
            ("1.2.3", "invalid", "1.2.3"),
            ("1.2.3", "none", "1.2.3"),
        ],
        ids=["major", "minor", "patch", "zero_major", "zero_minor", "invalid", "none"],
    )
    def test_bump_version(self, version, bump, expected):
        assert bump_version(version, bump) == expected


# ═══════════════════════════════════════════════════════════════════════════
# LOAD_BREAKING_CHANGES TESTS
# ═══════════════════════════════════════════════════════════════════════════


class TestLoadBreakingChanges:
    """Tests for load_breaking_changes function."""

    def test_load_valid_report(self, breaking_changes_report):
        """Load valid breaking changes report."""
        report_path, expected = breaking_changes_report
        result = load_breaking_changes(str(report_path))

        assert "changes" in result
        assert len(result["changes"]) == 3
        assert result["changes"][0]["manifest"] == "orders"
        assert result["changes"][0]["change_type"] == "breaking"

    def test_load_missing_report(self, tmp_path):
        """Return empty report when file doesn't exist."""
        report_path = tmp_path / "nonexistent.json"
        result = load_breaking_changes(str(report_path))

        assert result == {"changes": [], "has_breaking_changes": False}

    def test_load_empty_report(self, empty_breaking_changes_report):
        """Load empty but valid report."""
        report_path, expected = empty_breaking_changes_report
        result = load_breaking_changes(str(report_path))

        assert result["changes"] == []
        assert result["has_breaking_changes"] is False

    def test_load_report_preserves_extra_fields(self, tmp_path):
        """Load report preserves additional fields."""
        report = {
            "changes": [
                {"manifest": "test", "change_type": "breaking"}
            ],
            "timestamp": "2024-01-01T00:00:00Z",
            "author": "ci-bot",
        }
        report_path = tmp_path / "report.json"
        with open(report_path, "w") as f:
            json.dump(report, f)

        result = load_breaking_changes(str(report_path))
        assert result["timestamp"] == "2024-01-01T00:00:00Z"
        assert result["author"] == "ci-bot"


# ═══════════════════════════════════════════════════════════════════════════
# DETERMINE_BUMP_TYPE TESTS
# ═══════════════════════════════════════════════════════════════════════════


class TestDetermineBumpType:
    """Tests for determine_bump_type function."""

    def test_breaking_changes_only(self):
        """Changes with breaking changes only."""
        changes = [
            {"change_type": "breaking", "description": "Field removed"},
            {"change_type": "breaking", "description": "Type changed"},
        ]
        bump_type, reasons = determine_bump_type(changes)

        assert bump_type == "major"
        assert len(reasons) == 2
        assert all("BREAKING" in r for r in reasons)

    def test_non_breaking_changes_only(self):
        """Changes with non-breaking changes only."""
        changes = [
            {"change_type": "non_breaking", "description": "New field added"},
            {"change_type": "non_breaking", "description": "New enum value"},
        ]
        bump_type, reasons = determine_bump_type(changes)

        assert bump_type == "minor"
        assert len(reasons) == 2
        assert all("MINOR" in r for r in reasons)

    def test_patch_changes_only(self):
        """Changes with patch changes only."""
        changes = [
            {"change_type": "patch", "description": "Doc update"},
        ]
        bump_type, reasons = determine_bump_type(changes)

        assert bump_type == "patch"
        assert "PATCH" in reasons[0]

    def test_mixed_breaking_and_minor(self):
        """Breaking takes precedence over minor."""
        changes = [
            {"change_type": "non_breaking", "description": "New field"},
            {"change_type": "breaking", "description": "Field removed"},
        ]
        bump_type, reasons = determine_bump_type(changes)

        assert bump_type == "major"

    def test_mixed_minor_and_patch(self):
        """Minor takes precedence over patch."""
        changes = [
            {"change_type": "patch", "description": "Doc update"},
            {"change_type": "non_breaking", "description": "New field"},
        ]
        bump_type, reasons = determine_bump_type(changes)

        assert bump_type == "minor"

    def test_empty_changes(self):
        """Empty changes list."""
        changes = []
        bump_type, reasons = determine_bump_type(changes)

        assert bump_type == "none"
        assert "No changes detected" in reasons

    def test_unknown_change_type(self):
        """Unknown change type treated as no change."""
        changes = [
            {"change_type": "unknown", "description": "Something"},
        ]
        bump_type, reasons = determine_bump_type(changes)

        assert bump_type == "none"

    def test_reasons_include_descriptions(self):
        """Reasons include change descriptions."""
        changes = [
            {"change_type": "breaking", "description": "Field 'id' removed"},
            {"change_type": "non_breaking", "description": "Field 'name' optional"},
        ]
        bump_type, reasons = determine_bump_type(changes)

        assert "Field 'id' removed" in reasons[0]
        assert "Field 'name' optional" in reasons[1]


# ═══════════════════════════════════════════════════════════════════════════
# GET_CHANGED_CONTRACTS TESTS
# ═══════════════════════════════════════════════════════════════════════════


class TestGetChangedManifests:
    """Tests for get_changed_manifests function."""

    @patch("subprocess.run")
    def test_get_changed_manifests_success(self, mock_run):
        """Successfully get changed manifests."""
        mock_run.return_value = MagicMock(
            stdout="examples/sales/orders/manifest.yaml\nexamples/catalog/products/manifest.yaml\n",
            returncode=0,
        )

        manifests = get_changed_manifests("origin/main", "HEAD")

        assert "examples/sales/orders/manifest.yaml" in manifests
        assert "examples/catalog/products/manifest.yaml" in manifests
        mock_run.assert_called_once()

    @patch("subprocess.run")
    def test_get_changed_manifests_mixed_files(self, mock_run):
        """Handle mixed manifest and non-manifest files."""
        mock_run.return_value = MagicMock(
            stdout="examples/sales/orders/manifest.yaml\nexamples/sales/invoices/schema.avsc\n",
            returncode=0,
        )

        manifests = get_changed_manifests("origin/main", "HEAD")

        # Should include the manifest.yaml
        assert "examples/sales/orders/manifest.yaml" in manifests
        # Should infer manifest path from non-manifest files
        assert len(manifests) >= 1

    @patch("subprocess.run")
    def test_get_changed_manifests_git_failure(self, mock_run):
        """Handle git command failure."""
        import subprocess
        mock_run.side_effect = subprocess.CalledProcessError(1, "git")

        manifests = get_changed_manifests("origin/main", "HEAD")

        assert manifests == []

    @patch("subprocess.run")
    def test_get_changed_manifests_no_changes(self, mock_run):
        """Handle empty diff output."""
        mock_run.return_value = MagicMock(stdout="", returncode=0)

        manifests = get_changed_manifests("origin/main", "HEAD")

        assert manifests == []

    @patch("subprocess.run")
    def test_get_changed_manifests_non_domain_files(self, mock_run):
        """Ignore files outside examples/."""
        mock_run.return_value = MagicMock(
            stdout="README.md\nci/script.py\nDOCKERFILE\n",
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

        # Verify correct refs were passed
        call_args = mock_run.call_args
        assert "v1.0.0" in call_args[0][0]
        assert "v2.0.0" in call_args[0][0]

    @patch("subprocess.run")
    def test_get_changed_manifests_deduplication(self, mock_run):
        """Deduplicate manifests from multiple files."""
        mock_run.return_value = MagicMock(
            stdout=(
                "examples/sales/orders/manifest.yaml\n"
                "examples/sales/orders/schema.avsc\n"
                "examples/sales/orders/README.md\n"
            ),
            returncode=0,
        )

        manifests = get_changed_manifests("origin/main", "HEAD")

        # Should have only one entry for orders manifest
        assert manifests.count("examples/sales/orders/manifest.yaml") <= 1


# ═══════════════════════════════════════════════════════════════════════════
# SUGGEST_FOR_CONTRACT TESTS
# ═══════════════════════════════════════════════════════════════════════════


class TestSuggestForManifest:
    """Tests for suggest_for_manifest function."""

    def test_suggest_breaking_change(self, manifest_v1_0_0):
        """Suggest major bump for breaking change."""
        _, manifest_path, _ = manifest_v1_0_0
        changes = [
            {"manifest": "orders", "change_type": "breaking", "description": "Field removed"}
        ]

        suggestion = suggest_for_manifest(str(manifest_path), changes, "origin/main")

        assert suggestion is not None
        assert suggestion.current_version == "1.0.0"
        assert suggestion.suggested_version == "2.0.0"
        assert suggestion.bump_type == "major"

    def test_suggest_non_breaking_change(self, manifest_v1_0_0):
        """Suggest minor bump for non-breaking change."""
        _, manifest_path, _ = manifest_v1_0_0
        changes = [
            {"manifest": "orders", "change_type": "non_breaking", "description": "New field"}
        ]

        suggestion = suggest_for_manifest(str(manifest_path), changes, "origin/main")

        assert suggestion is not None
        assert suggestion.suggested_version == "1.1.0"
        assert suggestion.bump_type == "minor"

    def test_suggest_patch_change(self, manifest_v1_0_0):
        """Suggest patch bump for patch change."""
        _, manifest_path, _ = manifest_v1_0_0
        changes = [
            {"manifest": "orders", "change_type": "patch", "description": "Doc update"}
        ]

        suggestion = suggest_for_manifest(str(manifest_path), changes, "origin/main")

        assert suggestion is not None
        assert suggestion.suggested_version == "1.0.1"
        assert suggestion.bump_type == "patch"

    def test_suggest_multiple_changes_breaking_wins(self, manifest_v1_0_0):
        """Multiple changes, breaking takes precedence."""
        _, manifest_path, _ = manifest_v1_0_0
        changes = [
            {"manifest": "orders", "change_type": "patch", "description": "Doc update"},
            {"manifest": "orders", "change_type": "non_breaking", "description": "New field"},
            {"manifest": "orders", "change_type": "breaking", "description": "Field removed"},
        ]

        suggestion = suggest_for_manifest(str(manifest_path), changes, "origin/main")

        assert suggestion.bump_type == "major"
        assert suggestion.suggested_version == "2.0.0"

    def test_suggest_missing_manifest_file(self, tmp_path):
        """Return None when manifest file doesn't exist."""
        nonexistent = tmp_path / "nonexistent" / "manifest.yaml"
        changes = [{"manifest": "test", "change_type": "breaking", "description": "Test"}]

        suggestion = suggest_for_manifest(str(nonexistent), changes, "origin/main")

        assert suggestion is None

    def test_suggest_no_changes_for_manifest(self, manifest_v1_0_0):
        """No specific changes for manifest -> patch."""
        _, manifest_path, _ = manifest_v1_0_0
        changes = [
            {"manifest": "other", "change_type": "breaking", "description": "Unrelated"}
        ]

        with patch("dpm.validators.suggest_version.get_file_at_ref") as mock_get_file:
            mock_get_file.return_value = None
            suggestion = suggest_for_manifest(str(manifest_path), changes, "origin/main")

            assert suggestion is not None
            # No changes found for this manifest, defaults to patch
            assert suggestion.bump_type == "patch"

    def test_suggest_already_bumped_version(self, tmp_path):
        """Version already bumped correctly."""
        old_manifest = {
            "spec_version": "1.0.0",
            "manifest_version": "1.0.0",
            "metadata": {
                "name": "orders",
                "namespace": "sales",
            },
        }
        new_manifest = {
            "spec_version": "1.0.0",
            "manifest_version": "2.0.0",  # Already bumped
            "metadata": {
                "name": "orders",
                "namespace": "sales",
            },
        }

        manifest_path = tmp_path / "manifest.yaml"
        with open(manifest_path, "w") as f:
            yaml.dump(new_manifest, f)

        changes = [
            {"manifest": "orders", "change_type": "breaking", "description": "Field removed"}
        ]

        with patch("dpm.validators.suggest_version.get_file_at_ref") as mock_get_file:
            old_yaml = yaml.dump(old_manifest)
            mock_get_file.return_value = old_yaml

            suggestion = suggest_for_manifest(str(manifest_path), changes, "origin/main")

            assert suggestion is not None
            assert suggestion.bump_type == "none"
            assert suggestion.suggested_version == "2.0.0"

    def test_suggest_insufficient_bump(self, tmp_path):
        """Version not bumped enough for change type."""
        old_manifest = {
            "spec_version": "1.0.0",
            "manifest_version": "1.0.0",
            "metadata": {"name": "orders", "namespace": "sales"},
        }
        new_manifest = {
            "spec_version": "1.0.0",
            "manifest_version": "1.1.0",  # Minor bump, but breaking change
            "metadata": {"name": "orders", "namespace": "sales"},
        }

        manifest_path = tmp_path / "manifest.yaml"
        with open(manifest_path, "w") as f:
            yaml.dump(new_manifest, f)

        changes = [
            {"manifest": "orders", "change_type": "breaking", "description": "Field removed"}
        ]

        with patch("dpm.validators.suggest_version.get_file_at_ref") as mock_get_file:
            old_yaml = yaml.dump(old_manifest)
            mock_get_file.return_value = old_yaml

            suggestion = suggest_for_manifest(str(manifest_path), changes, "origin/main")

            assert suggestion is not None
            # Version not bumped enough, suggest major
            assert suggestion.bump_type == "major"
            assert suggestion.suggested_version == "2.0.0"

    def test_suggest_manifest_without_version(self, tmp_path):
        """Handle manifest without explicit manifest_version."""
        manifest = {
            "spec_version": "1.0.0",
            "metadata": {"name": "test", "namespace": "domain"},
            # No manifest_version
        }
        manifest_path = tmp_path / "manifest.yaml"
        with open(manifest_path, "w") as f:
            yaml.dump(manifest, f)

        changes = [
            {"manifest": "test", "change_type": "breaking", "description": "Breaking"}
        ]

        with patch("dpm.validators.suggest_version.get_file_at_ref") as mock_get_file:
            mock_get_file.return_value = None

            suggestion = suggest_for_manifest(str(manifest_path), changes, "origin/main")

            assert suggestion is not None
            # Should use default version 1.0.0
            assert suggestion.current_version == "1.0.0"


# ═══════════════════════════════════════════════════════════════════════════
# MAIN FUNCTION TESTS
# ═══════════════════════════════════════════════════════════════════════════


class TestMainFunction:
    """Tests for main() function."""

    @patch("sys.argv")
    @patch("dpm.validators.suggest_version.get_changed_manifests")
    @patch("dpm.validators.suggest_version.load_breaking_changes")
    def test_main_with_specific_manifest(
        self, mock_load_changes, mock_get_manifests, mock_argv, manifest_v1_0_0
    ):
        """Main with --manifest option."""
        _, manifest_path, _ = manifest_v1_0_0
        mock_load_changes.return_value = {"changes": []}

        with patch("sys.argv", [
            "suggest_version.py",
            "--manifest", str(manifest_path),
        ]):
            with pytest.raises(SystemExit) as exc_info:
                from dpm.validators.suggest_version import main
                main()

            # Should exit with 0 (no major bump required)
            assert exc_info.value.code == 0

    @patch("sys.argv")
    @patch("dpm.validators.suggest_version.get_changed_manifests")
    @patch("dpm.validators.suggest_version.load_breaking_changes")
    def test_main_exit_code_major_required(
        self, mock_load_changes, mock_get_manifests, mock_argv, manifest_v1_0_0
    ):
        """Main exits with 1 when major bump required but not applied."""
        _, manifest_path, _ = manifest_v1_0_0
        breaking_report = {
            "changes": [
                {"manifest": "orders", "change_type": "breaking", "description": "Breaking"}
            ]
        }
        mock_load_changes.return_value = breaking_report

        with patch("sys.argv", [
            "suggest_version.py",
            "--manifest", str(manifest_path),
        ]):
            with pytest.raises(SystemExit) as exc_info:
                from dpm.validators.suggest_version import main
                main()

            # Should exit with 1 (major bump required)
            assert exc_info.value.code == 1

    @patch("sys.argv")
    @patch("dpm.validators.suggest_version.get_changed_manifests")
    @patch("dpm.validators.suggest_version.load_breaking_changes")
    def test_main_with_output_file(
        self, mock_load_changes, mock_get_manifests, mock_argv,
        manifest_v1_0_0, tmp_path
    ):
        """Main writes output file."""
        _, manifest_path, _ = manifest_v1_0_0
        output_file = tmp_path / "suggestions.json"
        mock_load_changes.return_value = {"changes": []}
        mock_get_manifests.return_value = []

        with patch("sys.argv", [
            "suggest_version.py",
            "--output", str(output_file),
            "--manifest", str(manifest_path),
        ]):
            with pytest.raises(SystemExit):
                from dpm.validators.suggest_version import main
                main()


# ═══════════════════════════════════════════════════════════════════════════
# INTEGRATION TESTS
# ═══════════════════════════════════════════════════════════════════════════


class TestSuggestVersionIntegration:
    """Integration tests combining multiple functions."""

    def test_full_suggestion_workflow(self, tmp_path):
        """Complete workflow: load changes, analyze manifests, generate suggestions."""
        # The suggest_for_manifest function filters changes by metadata.name
        manifests_data = [
            ("orders", "1.0.0", "breaking"),
            ("products", "2.0.0", "non_breaking"),
            ("events", "1.5.0", "patch"),
        ]

        manifest_paths = []
        for name, version, change_type in manifests_data:
            # Create domain structure: examples/{namespace}/{entity}/
            domain_dir = tmp_path / "examples" / "test" / name
            domain_dir.mkdir(parents=True)

            manifest = {
                "spec_version": "1.0.0",
                "manifest_version": version,
                "metadata": {
                    "name": name,  # This is used as the key in changes
                    "namespace": "test",
                },
            }
            manifest_path = domain_dir / "manifest.yaml"
            with open(manifest_path, "w") as f:
                yaml.dump(manifest, f)
            manifest_paths.append(str(manifest_path))

        # Create changes with metadata.name as the key
        changes = [
            {"manifest": name, "change_type": ctype, "description": f"{ctype} change"}
            for name, _, ctype in manifests_data
        ]

        # Use patch to mock get_file_at_ref before calling suggest_for_manifest
        with patch("dpm.lib.common.subprocess.run") as mock_run:
            # Make subprocess fail (simulate no file at ref)
            import subprocess
            mock_run.side_effect = subprocess.CalledProcessError(1, "git")

            # Generate suggestions
            suggestions = []
            for manifest_path in manifest_paths:
                suggestion = suggest_for_manifest(manifest_path, changes, "origin/main")
                if suggestion:
                    suggestions.append(suggestion)

        # Verify suggestions are generated with correct bumps
        assert len(suggestions) == 3
        # Index 0: orders, 1.0.0 + breaking -> 2.0.0
        assert suggestions[0].manifest == "test/orders"
        assert suggestions[0].suggested_version == "2.0.0"
        assert suggestions[0].bump_type == "major"
        # Index 1: products, 2.0.0 + non_breaking -> 2.1.0
        assert suggestions[1].manifest == "test/products"
        assert suggestions[1].suggested_version == "2.1.0"
        assert suggestions[1].bump_type == "minor"
        # Index 2: events, 1.5.0 + patch -> 1.5.1
        assert suggestions[2].manifest == "test/events"
        assert suggestions[2].suggested_version == "1.5.1"
        assert suggestions[2].bump_type == "patch"

    def test_version_bump_sequence(self):
        """Test a sequence of version bumps."""
        current = "1.0.0"
        expected_sequence = [
            ("major", "2.0.0"),
            ("major", "3.0.0"),
            ("minor", "3.1.0"),
            ("patch", "3.1.1"),
        ]

        for bump_type, expected in expected_sequence:
            current = bump_version(current, bump_type)
            assert current == expected
