"""Parse per-directory CODEOWNERS files and resolve required approvers for changed paths."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

CODEOWNERS_FILENAME = "CODEOWNERS"
HANDLE_RE = re.compile(r"@([A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*)")


@dataclass(frozen=True)
class CodeownersScope:
    """A CODEOWNERS file and the handles (users/groups) listed in it."""

    path: Path
    handles: frozenset[str]


def parse_handles(line: str) -> list[str]:
    """Extract @handles from a CODEOWNERS line."""
    return HANDLE_RE.findall(line)


def parse_codeowners_file(content: str) -> list[tuple[str, list[str]]]:
    """Parse CODEOWNERS content into (pattern, handles) rules."""
    rules: list[tuple[str, list[str]]] = []
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        pattern = parts[0]
        handles = parse_handles(line)
        if handles:
            rules.append((pattern, handles))
    return rules


def load_codeowners_scope(codeowners_path: Path) -> CodeownersScope | None:
    """Load handles from a CODEOWNERS file."""
    if not codeowners_path.is_file():
        return None
    rules = parse_codeowners_file(codeowners_path.read_text(encoding="utf-8"))
    handles: set[str] = set()
    for _pattern, rule_handles in rules:
        handles.update(rule_handles)
    if not handles:
        return None
    return CodeownersScope(path=codeowners_path, handles=frozenset(handles))


def find_codeowners_for_file(changed_file: str, repo_root: Path) -> Path | None:
    """Find nearest CODEOWNERS walking up from the changed file's directory."""
    path = PurePosixPath(changed_file)
    if path.is_absolute():
        path = PurePosixPath(*path.parts[1:]) if path.parts[0] == "/" else path

    current = repo_root / Path(*path.parts[:-1]) if path.parts else repo_root
    while True:
        candidate = current / CODEOWNERS_FILENAME
        if candidate.is_file():
            return candidate
        if current == repo_root or current.parent == current:
            break
        current = current.parent
    return None


def collect_required_scopes(
    changed_files: list[str], repo_root: Path
) -> dict[Path, CodeownersScope]:
    """Map each touched CODEOWNERS scope to its required handles."""
    scopes: dict[Path, CodeownersScope] = {}
    for changed_file in changed_files:
        codeowners_path = find_codeowners_for_file(changed_file, repo_root)
        if codeowners_path is None:
            continue
        if codeowners_path in scopes:
            continue
        scope = load_codeowners_scope(codeowners_path)
        if scope is not None:
            scopes[codeowners_path] = scope
    return scopes


def scope_is_satisfied(
    scope: CodeownersScope,
    approved_usernames: set[str],
    group_member_usernames: dict[str, set[str]],
) -> bool:
    """Return True if at least one handle in the scope is satisfied by an approver."""
    for handle in scope.handles:
        if handle in approved_usernames:
            return True
        members = group_member_usernames.get(handle)
        if members and members & approved_usernames:
            return True
    return False


def find_unsatisfied_scopes(
    changed_files: list[str],
    repo_root: Path,
    approved_usernames: set[str],
    group_member_usernames: dict[str, set[str]],
) -> list[CodeownersScope]:
    """Return scopes that still need an approval from one of their handles."""
    scopes = collect_required_scopes(changed_files, repo_root)
    unsatisfied: list[CodeownersScope] = []
    for scope in scopes.values():
        if not scope_is_satisfied(scope, approved_usernames, group_member_usernames):
            unsatisfied.append(scope)
    return unsatisfied
