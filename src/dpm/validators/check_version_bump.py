#!/usr/bin/env python3
"""
Check that the manifest version bump is correct based on the type of changes.

This script verifies that manifest versioning follows SemVer rules:
- MAJOR (x.0.0): Breaking changes (field removal, type change, adding a required field)
- MINOR (0.x.0): Non-breaking changes (new nullable field, new enum value)
- PATCH (0.0.x): Documentation and metadata changes

The script analyzes the git diff and the breaking changes report, compares the
current version with the version from the base branch and validates the version bump.

Exit codes:
    0 - Version bump is correct
    1 - Version bump is incorrect or missing
    2 - Error reading files or running git

Usage:
    python check_version_bump.py --breaking-changes-file report.json
    python check_version_bump.py --base-ref origin/main --head-ref HEAD

Examples:
    # Check based on the breaking changes report from the CI pipeline
    python check_version_bump.py --breaking-changes-file breaking_changes_report.json

    # Direct check between git refs
    python check_version_bump.py --base-ref origin/main
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import yaml


def parse_semver(version: str) -> tuple[int, int, int]:
    """Parse semantic version string.

    Handles pre-release suffixes like ``1.2.3-beta.1`` by stripping
    anything after a hyphen in each numeric segment before converting
    to ``int``.

    Args:
        version: Version string in ``MAJOR.MINOR.PATCH`` format,
            optionally followed by a pre-release suffix.

    Returns:
        Tuple of (major, minor, patch).

    Raises:
        ValueError: If *version* does not contain three dot-separated
            numeric segments.
    """
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)(?:$|[-+])", version)
    if not match:
        raise ValueError(f"Invalid version format: {version}")
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def get_version_at_ref(file_path: str, ref: str) -> str:
    """Get manifest version at specific git ref."""
    try:
        result = subprocess.run(
            ["git", "show", f"{ref}:{file_path}"],
            capture_output=True,
            text=True,
            check=True,
        )
        manifest = yaml.safe_load(result.stdout)
        return manifest.get("manifest_version", "0.0.0")
    except subprocess.CalledProcessError:
        return "0.0.0"  # New file


def check_version_bump(
    old_version: str,
    new_version: str,
    has_breaking: bool,
    has_non_breaking: bool,
) -> tuple[bool, str]:
    """
    Check if version bump is appropriate for the changes.
    
    Returns:
        Tuple of (is_valid, message)
    """
    try:
        old = parse_semver(old_version)
        new = parse_semver(new_version)
    except ValueError as e:
        return False, str(e)
    
    if new <= old:
        return False, f"Version must be bumped: {old_version} -> new version required"
    
    if has_breaking:
        # MAJOR must be bumped
        if new[0] <= old[0]:
            return False, f"Breaking changes require MAJOR version bump: {old_version} -> {old[0]+1}.0.0"
        # MAJOR bump must reset MINOR and PATCH to 0
        if new[1] != 0 or new[2] != 0:
            return False, (
                f"MAJOR version bump must reset MINOR and PATCH to 0: "
                f"{old_version} -> {new[0]}.0.0 (got {new_version})"
            )
        return True, f"MAJOR version bump correct: {old_version} -> {new_version}"
    
    if has_non_breaking:
        # MINOR must be bumped (unless MAJOR was bumped)
        if new[0] > old[0]:
            return True, f"MAJOR version bump (includes non-breaking): {old_version} -> {new_version}"
        if new[1] <= old[1]:
            return False, f"Non-breaking changes require MINOR version bump: {old_version} -> {old[0]}.{old[1]+1}.0"
        return True, f"MINOR version bump correct: {old_version} -> {new_version}"
    
    # Patch changes
    if new[0] > old[0] or new[1] > old[1]:
        return True, f"Version bump correct: {old_version} -> {new_version}"
    if new[2] <= old[2]:
        return False, f"Changes require at least PATCH version bump: {old_version} -> {old[0]}.{old[1]}.{old[2]+1}"
    return True, f"PATCH version bump correct: {old_version} -> {new_version}"


def main():
    parser = argparse.ArgumentParser(description="Check version bump correctness")
    parser.add_argument(
        "--breaking-changes-file",
        required=True,
        help="Path to breaking changes report JSON",
    )
    parser.add_argument(
        "--base-ref",
        default="origin/main",
        help="Base git ref",
    )
    
    args = parser.parse_args()
    
    # Load breaking changes report
    with open(args.breaking_changes_file) as f:
        report = json.load(f)
    
    changes = report.get("changes", [])

    # Group changes by manifest
    manifests = {}
    for change in changes:
        manifest = change.get("manifest", "unknown")
        if manifest not in manifests:
            manifests[manifest] = {"breaking": False, "non_breaking": False}
        if change.get("change_type") == "breaking":
            manifests[manifest]["breaking"] = True
        elif change.get("change_type") == "non_breaking":
            manifests[manifest]["non_breaking"] = True
    
    print(f"{'=' * 50}")
    print("VERSION CHECK REPORT")
    print(f"{'=' * 50}")
    
    all_valid = True
    
    # Find changed manifest files
    for domain_path in Path("examples").rglob("manifest.yaml"):
        manifest_name = domain_path.parent.name
        
        if manifest_name not in manifests:
            continue
        
        manifest_info = manifests[manifest_name]
        
        # Get versions
        old_version = get_version_at_ref(str(domain_path), args.base_ref)
        
        with open(domain_path) as f:
            new_manifest = yaml.safe_load(f)
        new_version = new_manifest.get("manifest_version", "0.0.0")
        
        # Check version bump
        is_valid, message = check_version_bump(
            old_version,
            new_version,
            manifest_info["breaking"],
            manifest_info["non_breaking"],
        )
        
        if is_valid:
            print(f"\n✅ {manifest_name}: {message}")
        else:
            print(f"\n❌ {manifest_name}: {message}")
            all_valid = False
    
    print(f"\n{'=' * 50}")
    
    if all_valid:
        print("✅ All version bumps are correct")
        sys.exit(0)
    else:
        print("❌ Version bump errors found")
        sys.exit(1)


if __name__ == "__main__":
    main()
