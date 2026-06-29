#!/usr/bin/env python3
"""
Validate manifest compliance with Data Governance requirements.

This script checks manifests against governance requirements:
- Required fields in manifest.yaml
- Completeness of owner information
- Compliance with PII tagging requirements
- Quality-rule coverage
- SLA documentation
- Lineage documentation
- Changelog maintenance

Usage:
    python validate_governance.py examples/sales/orders/manifest.yaml
    python validate_governance.py --all
    python validate_governance.py --domain sales
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

from dpm.manifest_loader import find_all_manifests
from dpm.validators.report import Finding, Severity, ValidationReport, print_report

# Manifests with this kind describe a canonical entity (a definition without
# rows), not a data product. Such manifests get a relaxed governance profile:
# no SLA, quality rules, or lineage are required.
CANONICAL_ENTITY_KIND = "canonical_entity"


def is_canonical_entity(manifest: dict[str, Any]) -> bool:
    """Return True if the manifest describes a canonical entity definition."""
    return manifest.get("kind") == CANONICAL_ENTITY_KIND


class GovernanceValidator:
    """Validates manifests against governance requirements."""

    # Required metadata fields
    REQUIRED_METADATA_FIELDS = [
        "name",
        "namespace",
        "description",
        "owner",
    ]

    # Required owner fields
    REQUIRED_OWNER_FIELDS = [
        "team",
        "email",
    ]

    # Criticality tags requiring special handling
    CRITICAL_TAGS = ["critical", "tier-1"]

    def __init__(self, manifests_base: Path) -> None:
        """Initialize the validator with the manifests base path."""
        self.manifests_base = manifests_base

    def validate_manifest(self, manifest_path: Path) -> ValidationReport:
        """Validate a single manifest."""
        report = ValidationReport(manifest_path=str(manifest_path))

        try:
            with open(manifest_path, encoding="utf-8") as f:
                manifest = yaml.safe_load(f)
        except Exception as e:
            report.add_finding(
                Finding(
                    rule="parse_manifest",
                    severity=Severity.ERROR,
                    message=f"Manifest parsing error: {e}",
                    path=str(manifest_path),
                )
            )
            return report

        # Rules that apply to every manifest, including canonical entities.
        self._validate_version_fields(manifest, report)
        self._validate_metadata(manifest, report)
        self._validate_owner(manifest, report)
        self._validate_schema_reference(manifest, manifest_path, report)
        self._validate_changelog(manifest, report)

        # A canonical entity is a definition without rows: it carries no data,
        # so quality rules, SLA, lineage, PII and runbook requirements do not
        # apply. A data product is held to the full profile.
        if not is_canonical_entity(manifest):
            self._validate_pii(manifest, manifest_path, report)
            self._validate_quality_rules(manifest, manifest_path, report)
            self._validate_sla(manifest, manifest_path, report)
            self._validate_lineage(manifest, report)
            self._validate_critical_manifest_requirements(manifest, report)

        return report

    def _validate_version_fields(
        self, manifest: dict[str, Any], report: ValidationReport
    ) -> None:
        """Validate version fields."""
        if "spec_version" not in manifest:
            report.add_finding(
                Finding(
                    rule="version_spec",
                    severity=Severity.ERROR,
                    message="Missing spec_version field",
                    suggestion="Add spec_version: '1.0.0'",
                )
            )

        if "manifest_version" not in manifest:
            report.add_finding(
                Finding(
                    rule="version_manifest",
                    severity=Severity.ERROR,
                    message="Missing manifest_version field",
                    suggestion="Add manifest_version following the SemVer standard",
                )
            )
        else:
            version = manifest["manifest_version"]
            parts = str(version).split(".")
            if len(parts) != 3:
                report.add_finding(
                    Finding(
                        rule="version_semver",
                        severity=Severity.WARNING,
                        message=f"Version '{version}' does not follow SemVer (MAJOR.MINOR.PATCH)",
                        suggestion="Use the '1.2.3' format",
                    )
                )

    def _validate_metadata(
        self, manifest: dict[str, Any], report: ValidationReport
    ) -> None:
        """Validate metadata section."""
        metadata = manifest.get("metadata", {})

        for field_name in self.REQUIRED_METADATA_FIELDS:
            if field_name not in metadata:
                report.add_finding(
                    Finding(
                        rule="metadata_required",
                        severity=Severity.ERROR,
                        message=f"Missing required metadata field: {field_name}",
                        path=f"metadata.{field_name}",
                    )
                )

        # Description should be meaningful (> 20 chars)
        description = metadata.get("description", "")
        if len(str(description).strip()) < 20:
            report.add_finding(
                Finding(
                    rule="metadata_description",
                    severity=Severity.WARNING,
                    message="Description is too short (<20 chars)",
                    path="metadata.description",
                    suggestion="Provide a meaningful description of the data manifest",
                )
            )

        # Tags should exist
        if "tags" not in metadata or not metadata["tags"]:
            report.add_finding(
                Finding(
                    rule="metadata_tags",
                    severity=Severity.WARNING,
                    message="No tags defined",
                    path="metadata.tags",
                    suggestion="Add relevant tags for discoverability",
                )
            )

    def _validate_owner(
        self, manifest: dict[str, Any], report: ValidationReport
    ) -> None:
        """Validate owner information."""
        owner = manifest.get("metadata", {}).get("owner", {})

        for field_name in self.REQUIRED_OWNER_FIELDS:
            if field_name not in owner:
                report.add_finding(
                    Finding(
                        rule="owner_required",
                        severity=Severity.ERROR,
                        message=f"Missing required owner field: {field_name}",
                        path=f"metadata.owner.{field_name}",
                    )
                )

        # Mattermost channel for alerting
        if "mattermost" not in owner:
            report.add_finding(
                Finding(
                    rule="owner_mattermost",
                    severity=Severity.WARNING,
                    message="No Mattermost channel specified for alerts",
                    path="metadata.owner.mattermost",
                    suggestion="Add mattermost: 'team-alerts' for incident notifications",
                )
            )

        # On-call for critical manifests
        tags = manifest.get("metadata", {}).get("tags", [])
        is_critical = any(t in self.CRITICAL_TAGS for t in tags)
        if is_critical and "on_call" not in owner:
            report.add_finding(
                Finding(
                    rule="owner_oncall",
                    severity=Severity.WARNING,
                    message="Critical manifest missing on_call information",
                    path="metadata.owner.on_call",
                    suggestion="Add on_call link for critical manifests",
                )
            )

    def _validate_pii(
        self, manifest: dict[str, Any], manifest_path: Path, report: ValidationReport
    ) -> None:
        """Validate the metadata.pii flag and its consistency with the schema."""
        metadata = manifest.get("metadata", {})
        pii = metadata.get("pii")

        # The product must declare its PII status explicitly.
        if pii is None:
            report.add_finding(
                Finding(
                    rule="pii_flag",
                    severity=Severity.ERROR,
                    message="Manifest must declare its PII status",
                    path="metadata.pii",
                    suggestion="Add 'pii: true' if it contains personal data, or 'pii: false' otherwise",
                )
            )
            return

        if not isinstance(pii, bool):
            report.add_finding(
                Finding(
                    rule="pii_flag",
                    severity=Severity.ERROR,
                    message=f"metadata.pii must be a boolean, got {type(pii).__name__}",
                    path="metadata.pii",
                    suggestion="Use 'pii: true' or 'pii: false'",
                )
            )
            return

        # Cross-check the product-level flag against per-field PII annotations.
        pii_fields = [
            f.get("name")
            for f in self._load_schema_fields(manifest, manifest_path)
            if f.get("pii") is True
        ]

        if pii is False and pii_fields:
            report.add_finding(
                Finding(
                    rule="pii_conflict",
                    severity=Severity.ERROR,
                    message=f"metadata.pii is false but the schema marks fields as PII: {pii_fields}",
                    path="metadata.pii",
                    suggestion="Set 'pii: true' or remove the field-level 'pii: true' annotations",
                )
            )
        elif pii is True and not pii_fields:
            report.add_finding(
                Finding(
                    rule="pii_unmarked_fields",
                    severity=Severity.WARNING,
                    message="metadata.pii is true but no schema field is annotated with 'pii: true'",
                    path="schema",
                    suggestion="Annotate the personal-data fields with 'pii: true' in the schema",
                )
            )

    def _load_schema_fields(
        self, manifest: dict[str, Any], manifest_path: Path
    ) -> list[dict[str, Any]]:
        """Load the Avro schema field list, or return [] if unavailable."""
        schema_file = manifest.get("schema", {}).get("file")
        if not schema_file:
            return []
        schema_path = manifest_path.parent / schema_file
        try:
            with open(schema_path, encoding="utf-8") as f:
                schema = json.load(f)
        except (OSError, json.JSONDecodeError):
            return []
        fields = schema.get("fields", [])
        return fields if isinstance(fields, list) else []

    def _validate_schema_reference(
        self, manifest: dict[str, Any], manifest_path: Path, report: ValidationReport
    ) -> None:
        """Validate schema file exists and is referenced."""
        schema = manifest.get("schema", {})

        if "file" not in schema:
            report.add_finding(
                Finding(
                    rule="schema_reference",
                    severity=Severity.ERROR,
                    message="No schema file referenced",
                    path="schema.file",
                )
            )
            return

        schema_path = manifest_path.parent / schema["file"]
        if not schema_path.exists():
            report.add_finding(
                Finding(
                    rule="schema_exists",
                    severity=Severity.ERROR,
                    message=f"Schema file not found: {schema['file']}",
                    path="schema.file",
                )
            )

    def _validate_quality_rules(
        self, manifest: dict[str, Any], manifest_path: Path, report: ValidationReport
    ) -> None:
        """Validate quality rules configuration."""
        quality = manifest.get("quality_rules", {})

        if "file" not in quality:
            report.add_finding(
                Finding(
                    rule="quality_rules_reference",
                    severity=Severity.WARNING,
                    message="No quality rules file referenced",
                    path="quality_rules.file",
                    suggestion="Add quality rules for data validation",
                )
            )
            return

        rules_path = manifest_path.parent / quality["file"]
        if not rules_path.exists():
            report.add_finding(
                Finding(
                    rule="quality_rules_exists",
                    severity=Severity.ERROR,
                    message=f"Quality rules file not found: {quality['file']}",
                    path="quality_rules.file",
                )
            )
            return

        # Check that quality rules have at least some rules
        try:
            with open(rules_path, encoding="utf-8") as f:
                rules_content = yaml.safe_load(f)
                rules = rules_content.get("rules", [])
                if len(rules) < 1:
                    report.add_finding(
                        Finding(
                            rule="quality_rules_empty",
                            severity=Severity.WARNING,
                            message="Quality rules file has no rules defined",
                            path=str(rules_path),
                        )
                    )
        except Exception:
            pass  # File parsing issues handled elsewhere

    def _validate_sla(
        self, manifest: dict[str, Any], manifest_path: Path, report: ValidationReport
    ) -> None:
        """Validate SLA documentation."""
        sla = manifest.get("sla", {})

        if "file" not in sla:
            report.add_finding(
                Finding(
                    rule="sla_reference",
                    severity=Severity.INFO,
                    message="No SLA file referenced",
                    path="sla.file",
                    suggestion="Add SLA documentation for service level expectations",
                )
            )
            return

        sla_path = manifest_path.parent / sla["file"]
        if not sla_path.exists():
            report.add_finding(
                Finding(
                    rule="sla_exists",
                    severity=Severity.WARNING,
                    message=f"SLA file not found: {sla['file']}",
                    path="sla.file",
                )
            )

    def _validate_lineage(
        self, manifest: dict[str, Any], report: ValidationReport
    ) -> None:
        """Validate data lineage documentation."""
        lineage = manifest.get("lineage", {})

        if not lineage:
            report.add_finding(
                Finding(
                    rule="lineage_missing",
                    severity=Severity.WARNING,
                    message="No lineage documentation",
                    path="lineage",
                    suggestion="Add upstream and downstream lineage information",
                )
            )
            return

        if "upstream" not in lineage:
            report.add_finding(
                Finding(
                    rule="lineage_upstream",
                    severity=Severity.WARNING,
                    message="No upstream sources documented",
                    path="lineage.upstream",
                )
            )

        if "downstream" not in lineage:
            report.add_finding(
                Finding(
                    rule="lineage_downstream",
                    severity=Severity.INFO,
                    message="No downstream consumers documented",
                    path="lineage.downstream",
                    suggestion="Document known consumers for impact analysis",
                )
            )
            return

        downstream = lineage.get("downstream", [])
        if not isinstance(downstream, list):
            report.add_finding(
                Finding(
                    rule="lineage_downstream_type",
                    severity=Severity.ERROR,
                    message="lineage.downstream must be a list",
                    path="lineage.downstream",
                )
            )
            return

        for index, consumer in enumerate(downstream):
            if not isinstance(consumer, dict):
                report.add_finding(
                    Finding(
                        rule="lineage_downstream_entry",
                        severity=Severity.ERROR,
                        message="Downstream consumer must be an object",
                        path=f"lineage.downstream[{index}]",
                    )
                )
                continue

            for field_name in ("system", "team", "contact"):
                if not consumer.get(field_name):
                    report.add_finding(
                        Finding(
                            rule="lineage_downstream_required",
                            severity=Severity.WARNING,
                            message=f"Downstream consumer missing {field_name}",
                            path=f"lineage.downstream[{index}].{field_name}",
                        )
                    )

            if not consumer.get("objects"):
                report.add_finding(
                    Finding(
                        rule="lineage_downstream_objects",
                        severity=Severity.WARNING,
                        message="Downstream consumer missing technical objects",
                        path=f"lineage.downstream[{index}].objects",
                    )
                )

    def _validate_changelog(
        self, manifest: dict[str, Any], report: ValidationReport
    ) -> None:
        """Validate changelog maintenance."""
        changelog = manifest.get("changelog", [])

        if not changelog:
            report.add_finding(
                Finding(
                    rule="changelog_missing",
                    severity=Severity.WARNING,
                    message="No changelog entries",
                    path="changelog",
                    suggestion="Add changelog entries for version history",
                )
            )
            return

        # Check that latest entry matches manifest version
        manifest_version = manifest.get("manifest_version")
        if manifest_version and changelog:
            latest_version = changelog[0].get("version")
            if latest_version != manifest_version:
                report.add_finding(
                    Finding(
                        rule="changelog_version_mismatch",
                        severity=Severity.WARNING,
                        message=f"Changelog latest version ({latest_version}) "
                        f"doesn't match manifest version ({manifest_version})",
                        path="changelog[0].version",
                    )
                )

    def _validate_critical_manifest_requirements(
        self, manifest: dict[str, Any], report: ValidationReport
    ) -> None:
        """Additional requirements for critical manifests."""
        tags = manifest.get("metadata", {}).get("tags", [])
        is_critical = any(t in self.CRITICAL_TAGS for t in tags)

        if not is_critical:
            return

        # Critical manifests must have runbook
        runbook = manifest.get("runbook", {})
        if "file" not in runbook:
            report.add_finding(
                Finding(
                    rule="critical_runbook",
                    severity=Severity.ERROR,
                    message="Critical manifest missing runbook reference",
                    path="runbook.file",
                    suggestion="Add operational runbook for critical manifests",
                )
            )

        # Critical manifests must explicitly document mission-critical downstream.
        downstream = manifest.get("lineage", {}).get("downstream", [])
        if not downstream:
            report.add_finding(
                Finding(
                    rule="critical_consumers",
                    severity=Severity.WARNING,
                    message="Critical manifest has no downstream consumers documented",
                    path="lineage.downstream",
                )
            )


def main() -> None:
    """Entry point."""
    parser = argparse.ArgumentParser(
        description="Validate manifest compliance with Data Governance requirements"
    )
    parser.add_argument(
        "manifest",
        nargs="?",
        help="Path to the manifest.yaml file",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Validate all manifests",
    )
    parser.add_argument(
        "--domain",
        help="Validate manifests in the specified domain",
    )
    parser.add_argument(
        "--output",
        help="Save the JSON report to a file",
    )
    parser.add_argument(
        "--base-path",
        default=".",
        help="Base path for manifests (default: current directory)",
    )

    args = parser.parse_args()
    base_path = Path(args.base_path)

    validator = GovernanceValidator(base_path)
    reports: list[ValidationReport] = []

    if args.manifest:
        manifest_path = Path(args.manifest)
        if not manifest_path.exists():
            print(f"Manifest not found: {manifest_path}", file=sys.stderr)
            sys.exit(1)
        reports.append(validator.validate_manifest(manifest_path))

    elif args.all or args.domain:
        manifests = find_all_manifests(base_path, args.domain)
        if not manifests:
            print("No manifests found", file=sys.stderr)
            sys.exit(1)

        print(f"Manifests found: {len(manifests)}")
        for manifest_path in manifests:
            reports.append(validator.validate_manifest(manifest_path))

    else:
        parser.print_help()
        sys.exit(1)

    # Print reports
    for report in reports:
        print_report(report)

    # Summary
    total_errors = sum(r.error_count for r in reports)
    total_warnings = sum(r.warning_count for r in reports)
    passed = sum(1 for r in reports if r.passed)
    failed = len(reports) - passed

    print(f"\n{'=' * 60}")
    print("SUMMARY")
    print(f"{'=' * 60}")
    print(f"Manifests: {len(reports)} ({passed} passed, {failed} failed)")
    print(f"Total errors: {total_errors}")
    print(f"Total warnings: {total_warnings}")

    # Save the JSON report
    if args.output:
        json_report = {
            "summary": {
                "total_manifests": len(reports),
                "passed": passed,
                "failed": failed,
                "total_errors": total_errors,
                "total_warnings": total_warnings,
            },
            "reports": [
                {
                    "manifest": r.manifest_path,
                    "passed": r.passed,
                    "findings": [
                        {
                            "rule": f.rule,
                            "severity": f.severity.value,
                            "message": f.message,
                            "path": f.path,
                            "suggestion": f.suggestion,
                        }
                        for f in r.findings
                    ],
                }
                for r in reports
            ],
        }
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(json_report, f, indent=2, ensure_ascii=False)
        print(f"\nJSON report saved to: {args.output}")

    # Exit with an error if any manifests failed
    sys.exit(1 if failed > 0 else 0)


if __name__ == "__main__":
    main()
