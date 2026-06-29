"""Tests for check_version_bump.py."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

# Add the parent directory to the path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from dpm.validators import check_version_bump as mod
from dpm.validators.check_version_bump import (
    check_version_bump,
    get_version_at_ref,
    parse_semver,
)

# ═══════════════════════════════════════════════════════════════════════════
# parse_semver
# ═══════════════════════════════════════════════════════════════════════════


class TestParseSemver:
    """Tests for SemVer parsing."""

    def test_valid_semver(self):
        assert parse_semver("1.0.0") == (1, 0, 0)
        assert parse_semver("2.3.4") == (2, 3, 4)
        assert parse_semver("10.20.30") == (10, 20, 30)

    def test_two_parts_invalid(self):
        with pytest.raises(ValueError):
            parse_semver("1.0")

    def test_four_parts_invalid(self):
        with pytest.raises(ValueError):
            parse_semver("1.0.0.0")

    def test_prefix_v_invalid(self):
        with pytest.raises(ValueError):
            parse_semver("v1.0.0")

    def test_non_numeric_invalid(self):
        with pytest.raises(ValueError):
            parse_semver("1.0.x")


# ═══════════════════════════════════════════════════════════════════════════
# check_version_bump — MAJOR (breaking changes)
# ═══════════════════════════════════════════════════════════════════════════


class TestMajorVersionBump:
    """Tests for breaking changes — MAJOR."""

    def test_breaking_requires_major(self):
        ok, msg = check_version_bump("1.2.3", "2.0.0", True, False)
        assert ok is True
        assert "MAJOR" in msg

    def test_breaking_without_major_fails(self):
        ok, msg = check_version_bump("1.2.3", "1.3.0", True, False)
        assert ok is False
        assert "MAJOR" in msg

    def test_breaking_patch_fails(self):
        ok, msg = check_version_bump("1.2.3", "1.2.4", True, False)
        assert ok is False

    def test_breaking_and_non_breaking_requires_major(self):
        ok, msg = check_version_bump("1.2.3", "2.0.0", True, True)
        assert ok is True

    def test_breaking_and_non_breaking_without_major_fails(self):
        ok, msg = check_version_bump("1.2.3", "1.3.0", True, True)
        assert ok is False


# ═══════════════════════════════════════════════════════════════════════════
# check_version_bump — MINOR (non-breaking changes)
# ═══════════════════════════════════════════════════════════════════════════


class TestMinorVersionBump:
    """Tests for non-breaking changes — MINOR."""

    def test_non_breaking_requires_minor(self):
        ok, msg = check_version_bump("1.2.3", "1.3.0", False, True)
        assert ok is True
        assert "MINOR" in msg

    def test_non_breaking_patch_fails(self):
        ok, msg = check_version_bump("1.2.3", "1.2.4", False, True)
        assert ok is False
        assert "MINOR" in msg

    def test_non_breaking_with_major_allowed(self):
        ok, msg = check_version_bump("1.2.3", "2.0.0", False, True)
        assert ok is True


# ═══════════════════════════════════════════════════════════════════════════
# check_version_bump — PATCH
# ═══════════════════════════════════════════════════════════════════════════


class TestPatchVersionBump:
    """Tests for PATCH changes."""

    def test_patch_ok(self):
        ok, msg = check_version_bump("1.2.3", "1.2.4", False, False)
        assert ok is True
        assert "PATCH" in msg

    def test_patch_with_minor_ok(self):
        ok, _ = check_version_bump("1.2.3", "1.3.0", False, False)
        assert ok is True

    def test_patch_with_major_ok(self):
        ok, _ = check_version_bump("1.2.3", "2.0.0", False, False)
        assert ok is True

    def test_no_bump_fails(self):
        ok, msg = check_version_bump("1.2.3", "1.2.3", False, False)
        assert ok is False
        assert "must be bumped" in msg.lower()

    def test_downgrade_fails(self):
        ok, _ = check_version_bump("1.2.3", "1.2.2", False, False)
        assert ok is False


# ═══════════════════════════════════════════════════════════════════════════
# Edge cases
# ═══════════════════════════════════════════════════════════════════════════


class TestEdgeCases:
    """Edge cases."""

    def test_initial_version_from_zero(self):
        ok, _ = check_version_bump("0.0.0", "1.0.0", False, True)
        assert ok is True

    def test_invalid_old_version(self):
        ok, msg = check_version_bump("invalid", "1.0.0", False, False)
        assert ok is False
        assert "Invalid" in msg

    def test_invalid_new_version(self):
        ok, msg = check_version_bump("1.0.0", "invalid", False, False)
        assert ok is False
        assert "Invalid" in msg

    def test_large_version_numbers(self):
        ok, _ = check_version_bump("99.99.99", "100.0.0", True, False)
        assert ok is True

    def test_zero_major_development(self):
        ok, _ = check_version_bump("0.1.0", "0.2.0", False, True)
        assert ok is True


# ═══════════════════════════════════════════════════════════════════════════
# Real-world scenarios
# ═══════════════════════════════════════════════════════════════════════════


class TestRealScenarios:
    """Real-world manifest versioning scenarios."""

    def test_add_optional_field(self):
        ok, _ = check_version_bump("1.0.0", "1.1.0", False, True)
        assert ok is True

    def test_remove_field(self):
        ok, _ = check_version_bump("1.5.2", "2.0.0", True, False)
        assert ok is True

    def test_documentation_change(self):
        ok, _ = check_version_bump("1.2.3", "1.2.4", False, False)
        assert ok is True


# ═══════════════════════════════════════════════════════════════════════════
# get_version_at_ref
# ═══════════════════════════════════════════════════════════════════════════


class TestGetVersionAtRef:
    """Reading a manifest version from a git ref."""

    def test_returns_version_from_ref(self, mocker):
        mocker.patch(
            "subprocess.run",
            return_value=mocker.Mock(stdout="manifest_version: 1.2.3\n"),
        )
        assert get_version_at_ref("examples/x/manifest.yaml", "origin/main") == "1.2.3"

    def test_missing_file_returns_zero(self, mocker):
        mocker.patch(
            "subprocess.run",
            side_effect=subprocess.CalledProcessError(1, "git"),
        )
        assert get_version_at_ref("examples/x/manifest.yaml", "origin/main") == "0.0.0"


# ═══════════════════════════════════════════════════════════════════════════
# main
# ═══════════════════════════════════════════════════════════════════════════


def _setup_manifest_repo(tmp_path, new_version):
    """Create an examples/flights manifest at *new_version* and a report file."""
    flights = tmp_path / "examples" / "flights"
    flights.mkdir(parents=True)
    (flights / "manifest.yaml").write_text(f"manifest_version: {new_version}\n")
    report = tmp_path / "bc.json"
    report.write_text(
        json.dumps({"changes": [{"manifest": "flights", "change_type": "breaking"}]})
    )
    return report


class TestMain:
    """End-to-end main() over a breaking-changes report."""

    def test_main_exits_zero_for_valid_bump(self, tmp_path, monkeypatch, mocker):
        monkeypatch.chdir(tmp_path)
        report = _setup_manifest_repo(tmp_path, "2.0.0")
        mocker.patch.object(mod, "get_version_at_ref", return_value="1.0.0")
        monkeypatch.setattr(sys, "argv", ["x", "--breaking-changes-file", str(report)])
        with pytest.raises(SystemExit) as exc:
            mod.main()
        assert exc.value.code == 0

    def test_main_exits_one_for_invalid_bump(self, tmp_path, monkeypatch, mocker):
        monkeypatch.chdir(tmp_path)
        report = _setup_manifest_repo(tmp_path, "1.1.0")  # breaking but not MAJOR
        mocker.patch.object(mod, "get_version_at_ref", return_value="1.0.0")
        monkeypatch.setattr(sys, "argv", ["x", "--breaking-changes-file", str(report)])
        with pytest.raises(SystemExit) as exc:
            mod.main()
        assert exc.value.code == 1
