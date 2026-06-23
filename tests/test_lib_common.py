"""Tests for ci/lib/common.py -- parse_version, bump_version, get_file_at_ref."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Path setup so ``from dpm.lib.common import ...`` resolves to ci/lib/common.py
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dpm.lib.common import bump_version, get_file_at_ref, parse_version


# =========================================================================
# parse_version
# =========================================================================
class TestParseVersion:
    """Tests for the parse_version helper."""

    def test_standard_version(self) -> None:
        assert parse_version("1.2.3") == (1, 2, 3)

    def test_zero_version(self) -> None:
        assert parse_version("0.0.0") == (0, 0, 0)

    def test_large_numbers(self) -> None:
        assert parse_version("100.200.300") == (100, 200, 300)

    def test_version_with_prerelease_suffix(self) -> None:
        """Regex is not end-anchored, so pre-release suffixes are ignored."""
        assert parse_version("1.2.3-beta") == (1, 2, 3)

    def test_version_with_build_metadata(self) -> None:
        assert parse_version("4.5.6+build.789") == (4, 5, 6)

    def test_empty_string_returns_zeros(self) -> None:
        assert parse_version("") == (0, 0, 0)

    def test_alphabetic_string_returns_zeros(self) -> None:
        assert parse_version("abc") == (0, 0, 0)

    def test_incomplete_version_two_parts(self) -> None:
        assert parse_version("1.2") == (0, 0, 0)

    def test_incomplete_version_one_part(self) -> None:
        assert parse_version("1") == (0, 0, 0)

    def test_leading_whitespace_returns_zeros(self) -> None:
        """re.match anchors at start; leading space prevents match."""
        assert parse_version(" 1.2.3") == (0, 0, 0)

    def test_trailing_whitespace_still_matches(self) -> None:
        """Regex is not end-anchored; trailing space is ignored."""
        assert parse_version("1.2.3 ") == (1, 2, 3)

    def test_negative_looking_input(self) -> None:
        assert parse_version("-1.2.3") == (0, 0, 0)


# =========================================================================
# bump_version
# =========================================================================
class TestBumpVersion:
    """Tests for the bump_version helper."""

    def test_major_bump(self) -> None:
        assert bump_version("1.2.3", "major") == "2.0.0"

    def test_minor_bump(self) -> None:
        assert bump_version("1.2.3", "minor") == "1.3.0"

    def test_patch_bump(self) -> None:
        assert bump_version("1.2.3", "patch") == "1.2.4"

    def test_unknown_bump_type_returns_original(self) -> None:
        assert bump_version("1.2.3", "unknown") == "1.2.3"

    def test_empty_bump_type_returns_original(self) -> None:
        assert bump_version("1.2.3", "") == "1.2.3"

    def test_zero_version_patch_bump(self) -> None:
        assert bump_version("0.0.0", "patch") == "0.0.1"

    def test_zero_version_minor_bump(self) -> None:
        assert bump_version("0.0.0", "minor") == "0.1.0"

    def test_zero_version_major_bump(self) -> None:
        assert bump_version("0.0.0", "major") == "1.0.0"

    def test_major_resets_minor_and_patch(self) -> None:
        assert bump_version("5.9.8", "major") == "6.0.0"

    def test_minor_resets_patch(self) -> None:
        assert bump_version("5.9.8", "minor") == "5.10.0"


# =========================================================================
# get_file_at_ref
# =========================================================================
class TestGetFileAtRef:
    """Tests for the get_file_at_ref helper (subprocess is always mocked)."""

    @patch("dpm.lib.common.subprocess.run")
    def test_success_returns_stdout(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(stdout="file content\n")
        result = get_file_at_ref("manifests/v1.yaml", "main")

        assert result == "file content\n"
        mock_run.assert_called_once_with(
            ["git", "show", "main:manifests/v1.yaml"],
            capture_output=True,
            text=True,
            check=True,
        )

    @patch("dpm.lib.common.subprocess.run")
    def test_called_process_error_returns_none(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = subprocess.CalledProcessError(
            returncode=128, cmd=["git", "show", "main:missing.yaml"]
        )
        result = get_file_at_ref("missing.yaml", "main")
        assert result is None

    @patch("dpm.lib.common.subprocess.run")
    def test_ref_is_commit_sha(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(stdout="sha content")
        result = get_file_at_ref("f.yaml", "abc123")

        assert result == "sha content"
        mock_run.assert_called_once_with(
            ["git", "show", "abc123:f.yaml"],
            capture_output=True,
            text=True,
            check=True,
        )

    @patch("dpm.lib.common.subprocess.run")
    def test_empty_file_returns_empty_string(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(stdout="")
        result = get_file_at_ref("empty.yaml", "HEAD")
        assert result == ""
