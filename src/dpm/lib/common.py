"""Shared utilities for manifest CI scripts.

Provides common functions for git operations and semantic versioning
used across suggest_version.py and detect_breaking_changes.py.
"""

import re
import subprocess

__all__ = [
    "get_file_at_ref",
    "parse_version",
    "bump_version",
]


def get_file_at_ref(file_path: str, ref: str) -> str | None:
    """Get file content at a specific git ref.

    Args:
        file_path: Relative path to the file within the repository.
        ref: Git ref (branch, tag, or commit SHA).

    Returns:
        File content as string, or None if the file does not exist at that ref.
    """
    try:
        result = subprocess.run(
            ["git", "show", f"{ref}:{file_path}"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout
    except subprocess.CalledProcessError:
        return None


def parse_version(version: str) -> tuple[int, int, int]:
    """Parse a semantic version string into a (major, minor, patch) tuple.

    Args:
        version: Version string in ``MAJOR.MINOR.PATCH`` format.

    Returns:
        Tuple of (major, minor, patch). Defaults to (0, 0, 0) on parse failure.
    """
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)", version)
    if match:
        return int(match.group(1)), int(match.group(2)), int(match.group(3))
    return 0, 0, 0


def bump_version(version: str, bump_type: str) -> str:
    """Bump a semantic version according to the specified bump type.

    Args:
        version: Current version string in ``MAJOR.MINOR.PATCH`` format.
        bump_type: One of ``"major"``, ``"minor"``, ``"patch"``.
            Any other value returns the version unchanged.

    Returns:
        The bumped version string.
    """
    major, minor, patch = parse_version(version)

    if bump_type == "major":
        return f"{major + 1}.0.0"
    elif bump_type == "minor":
        return f"{major}.{minor + 1}.0"
    elif bump_type == "patch":
        return f"{major}.{minor}.{patch + 1}"
    return version
