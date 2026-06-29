#!/usr/bin/env python3
"""
Suggest version bumps based on detected changes.

This script analyzes manifest changes and suggests appropriate version bumps
following semantic versioning (SemVer) rules.

Versioning rules:
- MAJOR: Breaking changes (field removal, type change, required field added)
- MINOR: Non-breaking additions (new optional field, new enum value)
- PATCH: Documentation, description, metadata changes

Usage:
    python suggest_version.py --breaking-changes-file breaking_changes_report.json
    python suggest_version.py --manifest examples/sales/orders/manifest.yaml
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

import yaml
from pydantic import BaseModel

from dpm.lib.common import bump_version, get_file_at_ref, parse_version


class VersionSuggestion(BaseModel):
    """Version suggestion for a manifest."""
    manifest: str
    current_version: str
    suggested_version: str
    bump_type: str  # major, minor, patch, none
    reasons: list[str]
    
    model_config = {
        "use_enum_values": True,
    }


def get_changed_manifests(base_ref: str, head_ref: str) -> list[str]:
    """Get list of changed manifest files."""
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", base_ref, head_ref, "--", "examples/"],
            capture_output=True,
            text=True,
            check=True,
        )
        files = result.stdout.strip().split("\n")
        
        # Find manifest.yaml files
        manifest_files = []
        for f in files:
            if f and f.endswith("manifest.yaml"):
                manifest_files.append(f)
            elif f and "examples/" in f:
                # Check if there's a manifest.yaml in this directory
                parts = f.split("/")
                if len(parts) >= 3:
                    manifest_path = f"examples/{parts[1]}/{parts[2]}/manifest.yaml"
                    if manifest_path not in manifest_files:
                        manifest_files.append(manifest_path)
        
        return list(set(manifest_files))
    except subprocess.CalledProcessError:
        return []


def load_breaking_changes(report_path: str) -> dict:
    """Load breaking changes report."""
    path = Path(report_path)
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {"changes": [], "has_breaking_changes": False}


def determine_bump_type(changes: list[dict]) -> tuple[str, list[str]]:
    """Determine bump type based on changes."""
    reasons = []
    
    has_breaking = False
    has_minor = False
    has_patch = False
    
    for change in changes:
        change_type = change.get("change_type", "")
        description = change.get("description", "")
        
        if change_type == "breaking":
            has_breaking = True
            reasons.append(f"BREAKING: {description}")
        elif change_type == "non_breaking":
            has_minor = True
            reasons.append(f"MINOR: {description}")
        elif change_type == "patch":
            has_patch = True
            reasons.append(f"PATCH: {description}")
    
    if has_breaking:
        return "major", reasons
    elif has_minor:
        return "minor", reasons
    elif has_patch:
        return "patch", reasons
    else:
        return "none", ["No changes detected"]


def suggest_for_manifest(
    manifest_path: str,
    changes: list[dict],
    base_ref: str,
) -> VersionSuggestion | None:
    """Generate version suggestion for a manifest."""
    path = Path(manifest_path)
    
    if not path.exists():
        return None
    
    with open(path, encoding="utf-8") as f:
        current_manifest = yaml.safe_load(f)
    
    current_version = current_manifest.get("manifest_version", "1.0.0")
    metadata = current_manifest.get("metadata", {})
    manifest_name = f"{metadata.get('namespace', 'unknown')}/{metadata.get('name', 'unknown')}"
    
    # Filter changes for this manifest
    manifest_changes = [
        c for c in changes
        if c.get("manifest", "") == metadata.get("name", "")
    ]
    
    # If no specific changes found, check if version already bumped
    if not manifest_changes:
        # Check old version
        old_content = get_file_at_ref(manifest_path, base_ref)
        if old_content:
            old_manifest = yaml.safe_load(old_content)
            old_version = old_manifest.get("manifest_version", "1.0.0")
            
            if old_version != current_version:
                return VersionSuggestion(
                    manifest=manifest_name,
                    current_version=current_version,
                    suggested_version=current_version,
                    bump_type="none",
                    reasons=[f"Version already bumped from {old_version} to {current_version}"],
                )
        
        # Default to patch for any changes
        manifest_changes = [{"change_type": "patch", "description": "Manifest file modified"}]
    
    bump_type, reasons = determine_bump_type(manifest_changes)
    suggested_version = bump_version(current_version, bump_type)
    
    # Check if version was already bumped correctly
    if bump_type != "none":
        old_content = get_file_at_ref(manifest_path, base_ref)
        if old_content:
            old_manifest = yaml.safe_load(old_content)
            old_version = old_manifest.get("manifest_version", "1.0.0")
            
            old_major, old_minor, old_patch = parse_version(old_version)
            cur_major, cur_minor, cur_patch = parse_version(current_version)
            
            # Check if bump was sufficient
            version_ok = False
            if bump_type == "major" and cur_major > old_major:
                version_ok = True
            elif bump_type == "minor" and (cur_major > old_major or cur_minor > old_minor):
                version_ok = True
            elif bump_type == "patch" and (
                cur_major > old_major or cur_minor > old_minor or cur_patch > old_patch
            ):
                version_ok = True
            
            if version_ok:
                return VersionSuggestion(
                    manifest=manifest_name,
                    current_version=current_version,
                    suggested_version=current_version,
                    bump_type="none",
                    reasons=[f"Version correctly bumped from {old_version}"] + reasons,
                )
    
    return VersionSuggestion(
        manifest=manifest_name,
        current_version=current_version,
        suggested_version=suggested_version,
        bump_type=bump_type,
        reasons=reasons,
    )


def main():
    parser = argparse.ArgumentParser(description="Suggest version bumps for manifests")
    parser.add_argument("--output", help="Output file for JSON report")
    parser.add_argument("--manifest", help="Path to specific manifest to analyze")
    parser.add_argument(
        "--breaking-changes-file",
        default="breaking_changes_report.json",
        help="Path to breaking changes report",
    )
    parser.add_argument("--base-ref", default="origin/main", help="Base git ref")
    parser.add_argument("--head-ref", default="HEAD", help="Head git ref")
    
    args = parser.parse_args()
    
    # Load breaking changes
    breaking_report = load_breaking_changes(args.breaking_changes_file)
    changes = breaking_report.get("changes", [])
    
    suggestions = []
    
    if args.manifest:
        # Analyze specific manifest
        suggestion = suggest_for_manifest(args.manifest, changes, args.base_ref)
        if suggestion:
            suggestions.append(suggestion)
    else:
        # Analyze all changed manifests
        changed_manifests = get_changed_manifests(args.base_ref, args.head_ref)
        
        for manifest_path in changed_manifests:
            suggestion = suggest_for_manifest(manifest_path, changes, args.base_ref)
            if suggestion:
                suggestions.append(suggestion)
    
    # Build report
    report = {
        "total_manifests": len(suggestions),
        "bump_required": sum(1 for s in suggestions if s.bump_type != "none"),
        "bump_summary": {
            "major": sum(1 for s in suggestions if s.bump_type == "major"),
            "minor": sum(1 for s in suggestions if s.bump_type == "minor"),
            "patch": sum(1 for s in suggestions if s.bump_type == "patch"),
            "none": sum(1 for s in suggestions if s.bump_type == "none"),
        },
        "suggestions": [s.model_dump() for s in suggestions],
    }
    
    # Output
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        print(f"Report written to {args.output}")
    
    # Print summary
    print(f"\n{'=' * 50}")
    print("VERSION SUGGESTION REPORT")
    print(f"{'=' * 50}")
    print(f"\nManifests analyzed: {report['total_manifests']}")
    print(f"Bump required: {report['bump_required']}")
    print("\nBump summary:")
    for bump_type, count in report["bump_summary"].items():
        if count > 0:
            emoji = {
                "major": "🔴",
                "minor": "🟡",
                "patch": "🟢",
                "none": "✅",
            }.get(bump_type, "⚪")
            print(f"  {emoji} {bump_type.upper()}: {count}")
    
    for suggestion in suggestions:
        print(f"\n📋 {suggestion.manifest}")
        print(f"   Current: {suggestion.current_version}")
        if suggestion.bump_type != "none":
            print(f"   Suggested: {suggestion.suggested_version} ({suggestion.bump_type})")
            for reason in suggestion.reasons:
                print(f"   - {reason}")
        else:
            print("   ✅ No bump needed")
    
    # Exit with error if major bump required but not applied
    major_required = report["bump_summary"]["major"]
    if major_required > 0:
        print(f"\n⚠️  {major_required} manifest(s) require MAJOR version bump!")
        sys.exit(1)
    
    sys.exit(0)


if __name__ == "__main__":
    main()
