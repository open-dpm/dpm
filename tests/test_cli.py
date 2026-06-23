"""Tests for the dpm CLI dispatch."""

from __future__ import annotations

import sys

import pytest

from dpm import cli


@pytest.fixture(autouse=True)
def _preserve_argv():
    """cli.main() rewrites sys.argv; restore it after each test."""
    saved = sys.argv[:]
    yield
    sys.argv = saved


@pytest.mark.parametrize(
    "argv, target",
    [
        (["validate", "m.yaml"], "dpm.validators.validate_manifest.main"),
        (["validate", "--all"], "dpm.validators.validate_manifest.main"),
        (["validate-rules", "r.yml"], "dpm.validators.validate_quality_rules.main"),
        (["governance", "m.yaml"], "dpm.validators.validate_governance.main"),
        (["breaking-changes"], "dpm.validators.detect_breaking_changes.main"),
        (
            ["suggest-version", "--breaking-changes-file", "b.json"],
            "dpm.validators.suggest_version.main",
        ),
    ],
)
def test_cli_dispatches_to_subcommand(argv, target, mocker):
    """Each subcommand calls the matching validator entry point exactly once."""
    entry = mocker.patch(target)
    cli.main(argv)
    entry.assert_called_once()


def test_cli_requires_a_subcommand():
    """Invoking dpm with no subcommand exits with an error."""
    with pytest.raises(SystemExit):
        cli.main([])


@pytest.mark.parametrize("command", ["validate", "validate-rules", "governance"])
def test_cli_requires_path_or_all(command, mocker):
    """validate/validate-rules/governance need a path or --all."""
    mocker.patch("dpm.validators.validate_manifest.main")
    mocker.patch("dpm.validators.validate_quality_rules.main")
    mocker.patch("dpm.validators.validate_governance.main")
    with pytest.raises(SystemExit):
        cli.main([command])


def test_cli_suggest_version_requires_report():
    """suggest-version needs --breaking-changes-file."""
    with pytest.raises(SystemExit):
        cli.main(["suggest-version"])


def test_cli_validate_forwards_json_output(mocker):
    """--json-output is forwarded to the underlying validator argv."""
    entry = mocker.patch("dpm.validators.validate_manifest.main")
    cli.main(["validate", "--all", "--json-output", "out.json"])
    entry.assert_called_once()
    assert "--json-output" in sys.argv
    assert "out.json" in sys.argv
