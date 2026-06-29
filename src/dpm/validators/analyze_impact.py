#!/usr/bin/env python3
"""
Analyze impact of manifest changes on downstream consumers.

This script identifies which consumers might be affected by manifest changes
and generates an impact report.

Usage:
    python analyze_impact.py --output impact_report.json
    python analyze_impact.py --manifest examples/sales/orders/manifest.yaml
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

import yaml
from pydantic import BaseModel


class Consumer(BaseModel):
    """Represents a downstream consumer."""
    name: str
    team: str | None = None
    contact: str | None = None
    criticality: str | None = None
    usage: str | None = None


class ImpactAssessment(BaseModel):
    """Impact assessment for a single manifest change."""
    manifest: str
    manifest_version: str
    change_type: str  # breaking, non_breaking, patch
    affected_consumers: list[Consumer]
    risk_level: str  # critical, high, medium, low
    notification_required: bool
    
    model_config = {
        "use_enum_values": True,
    }


def get_changed_manifests(base_ref: str = "origin/main", head_ref: str = "HEAD") -> list[str]:
    """Get list of changed manifest directories."""
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", base_ref, head_ref, "--", "examples/"],
            capture_output=True,
            text=True,
            check=True,
        )
        files = result.stdout.strip().split("\n")
        
        # Extract unique manifest directories
        manifest_dirs = set()
        for f in files:
            if f and "examples/" in f:
                parts = f.split("/")
                if len(parts) >= 3:
                    # examples/{namespace}/{entity}
                    manifest_dirs.add(f"examples/{parts[1]}/{parts[2]}")
        
        return list(manifest_dirs)
    except subprocess.CalledProcessError:
        return []


def load_manifest(manifest_path: str) -> dict | None:
    """Load manifest YAML file."""
    path = Path(manifest_path)
    
    if path.is_dir():
        manifest_file = path / "manifest.yaml"
    else:
        manifest_file = path
    
    if not manifest_file.exists():
        return None
    
    with open(manifest_file, encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_consumers(manifest: dict) -> list[Consumer]:
    """Extract consumers from manifest lineage."""
    consumers = []
    
    # Check lineage.downstream
    lineage = manifest.get("lineage", {})
    downstream = lineage.get("downstream", [])
    
    for consumer in downstream:
        if isinstance(consumer, dict):
            consumers.append(Consumer(
                name=consumer.get("system") or consumer.get("name") or "unknown",
                team=consumer.get("team"),
                contact=consumer.get("contact"),
                criticality=consumer.get("criticality"),
                usage=consumer.get("usage"),
            ))
        elif isinstance(consumer, str):
            consumers.append(Consumer(name=consumer))

    return consumers


def assess_risk(consumers: list[Consumer], change_type: str) -> str:
    """Assess risk level based on consumers and change type."""
    if change_type == "breaking":
        # Check for critical consumers
        for consumer in consumers:
            if consumer.criticality == "critical":
                return "critical"
        return "high"
    
    elif change_type == "non_breaking":
        for consumer in consumers:
            if consumer.criticality == "critical":
                return "medium"
        return "low"
    
    else:  # patch
        return "low"


def analyze_manifest_impact(
    manifest_path: str,
    change_type: str = "unknown",
) -> ImpactAssessment | None:
    """Analyze impact for a single manifest."""
    manifest = load_manifest(manifest_path)
    if not manifest:
        return None
    
    metadata = manifest.get("metadata", {})
    manifest_name = f"{metadata.get('namespace', 'unknown')}/{metadata.get('name', 'unknown')}"
    manifest_version = manifest.get("manifest_version", "unknown")
    
    consumers = get_consumers(manifest)
    risk_level = assess_risk(consumers, change_type)
    
    return ImpactAssessment(
        manifest=manifest_name,
        manifest_version=manifest_version,
        change_type=change_type,
        affected_consumers=consumers,
        risk_level=risk_level,
        notification_required=change_type == "breaking" or risk_level in ["critical", "high"],
    )


def load_breaking_changes_report(report_path: str) -> dict:
    """Load breaking changes report if it exists."""
    path = Path(report_path)
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {"changes": []}


def main():
    parser = argparse.ArgumentParser(description="Analyze impact of manifest changes")
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
    
    assessments = []
    
    # Load breaking changes report to get change types
    breaking_report = load_breaking_changes_report(args.breaking_changes_file)
    manifest_change_types = {}
    for change in breaking_report.get("changes", []):
        manifest = change.get("manifest", "")
        ctype = change.get("change_type", "unknown")
        if manifest:
            if manifest not in manifest_change_types or ctype == "breaking":
                manifest_change_types[manifest] = ctype
    
    if args.manifest:
        # Analyze specific manifest
        # Extract entity name from path: examples/{namespace}/{entity}/manifest.yaml
        manifest_dir = Path(args.manifest).parent
        entity_name = manifest_dir.name  # e.g. "orders"
        assessment = analyze_manifest_impact(
            args.manifest,
            manifest_change_types.get(entity_name, "unknown"),
        )
        if assessment:
            assessments.append(assessment)
    else:
        # Analyze all changed manifests
        changed_manifests = get_changed_manifests(args.base_ref, args.head_ref)
        
        for manifest_path in changed_manifests:
            manifest = load_manifest(manifest_path)
            if manifest:
                metadata = manifest.get("metadata", {})
                manifest_name = metadata.get("name", "unknown")
                change_type = manifest_change_types.get(manifest_name, "unknown")
                
                assessment = analyze_manifest_impact(manifest_path, change_type)
                if assessment:
                    assessments.append(assessment)
    
    # Build report
    report = {
        "total_manifests_analyzed": len(assessments),
        "manifests_requiring_notification": sum(
            1 for a in assessments if a.notification_required
        ),
        "risk_summary": {
            "critical": sum(1 for a in assessments if a.risk_level == "critical"),
            "high": sum(1 for a in assessments if a.risk_level == "high"),
            "medium": sum(1 for a in assessments if a.risk_level == "medium"),
            "low": sum(1 for a in assessments if a.risk_level == "low"),
        },
        "assessments": [a.model_dump() for a in assessments],
    }
    
    # Output
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        print(f"Report written to {args.output}")
    
    # Print summary
    print(f"\n{'=' * 50}")
    print("IMPACT ANALYSIS REPORT")
    print(f"{'=' * 50}")
    print(f"\nManifests analyzed: {report['total_manifests_analyzed']}")
    print(f"Requiring notification: {report['manifests_requiring_notification']}")
    print("\nRisk summary:")
    for level, count in report["risk_summary"].items():
        emoji = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(level, "⚪")
        print(f"  {emoji} {level.upper()}: {count}")
    
    for assessment in assessments:
        print(f"\n📋 {assessment.manifest} v{assessment.manifest_version}")
        print(f"   Change: {assessment.change_type}")
        print(f"   Risk: {assessment.risk_level}")
        print(f"   Consumers: {len(assessment.affected_consumers)}")
        if assessment.notification_required:
            print("   ⚠️  Notification required!")
    
    # Exit with error if critical risk
    if report["risk_summary"]["critical"] > 0:
        sys.exit(1)
    
    sys.exit(0)


if __name__ == "__main__":
    main()
