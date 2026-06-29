"""Tests for per-directory CODEOWNERS resolution and approval matching."""

from __future__ import annotations

from pathlib import Path

from dpm.codeowners.codeowners import (
    collect_required_scopes,
    find_codeowners_for_file,
    find_unsatisfied_scopes,
    load_codeowners_scope,
    parse_codeowners_file,
    scope_is_satisfied,
)


def test_parse_codeowners_file() -> None:
    content = """
# comment
* @sales-integration @analytics
"""
    rules = parse_codeowners_file(content)
    assert rules == [("*", ["sales-integration", "analytics"])]


def test_find_codeowners_for_manifest_file(repo_root: Path) -> None:
    path = find_codeowners_for_file(
        "examples/aviation/flights/schema.avsc", repo_root
    )
    assert path == repo_root / "examples/aviation/flights/CODEOWNERS"


def test_find_codeowners_for_ci_file(repo_root: Path) -> None:
    path = find_codeowners_for_file("src/dpm/validators/validate_manifest.py", repo_root)
    assert path == repo_root / "src/dpm/validators/CODEOWNERS"


def test_collect_required_scopes_single_manifest(repo_root: Path) -> None:
    scopes = collect_required_scopes(
        ["examples/aviation/flights/sla.yml"], repo_root
    )
    assert len(scopes) == 1
    scope = next(iter(scopes.values()))
    assert "platform-team" in scope.handles


def test_collect_required_scopes_multiple_manifests(repo_root: Path) -> None:
    scopes = collect_required_scopes(
        [
            "examples/aviation/flights/sla.yml",
            "src/dpm/validators/validate_manifest.py",
        ],
        repo_root,
    )
    assert len(scopes) == 2


def test_scope_satisfied_by_username(repo_root: Path) -> None:
    scope = load_codeowners_scope(
        repo_root / "examples/aviation/flights/CODEOWNERS"
    )
    assert scope is not None
    assert scope_is_satisfied(scope, {"platform-team"}, {})


def test_scope_satisfied_by_group_member(repo_root: Path) -> None:
    scope = load_codeowners_scope(
        repo_root / "examples/aviation/flights/CODEOWNERS"
    )
    assert scope is not None
    group_members = {"platform-team": {"bob"}}
    assert scope_is_satisfied(scope, {"bob"}, group_members)


def test_find_unsatisfied_scopes(repo_root: Path) -> None:
    unsatisfied = find_unsatisfied_scopes(
        ["examples/aviation/flights/schema.avsc"],
        repo_root,
        approved_usernames=set(),
        group_member_usernames={},
    )
    assert len(unsatisfied) == 1
