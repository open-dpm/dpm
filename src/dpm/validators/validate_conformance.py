#!/usr/bin/env python3
"""
Validate that a data product conforms to the canonical entities it declares.

A data product opts in to the Enterprise Data Model by declaring, in its
manifest, which canonical entities it represents:

    metadata:
      conforms_to:
        - entity: customer@1            # pin by MAJOR version
          rename: {customer_id: cust_id}   # canonical attribute -> physical field

For every declared entity this validator resolves the canonical definition
from the registry (``<registry>/<entity>/v<major>/``), reads its mandatory
attributes (the non-nullable fields of the entity's Avro schema) and checks
that the product's schema carries each one, under its physical name, with a
compatible type. A product without ``conforms_to`` is outside the EDM and
produces no findings.

Exit codes:
    0 - All products conform (no errors)
    1 - Conformance errors found

Usage:
    python validate_conformance.py examples/aviation/flights/manifest.yaml --registry-path examples/canonical
    python validate_conformance.py --all --base-path . --registry-path examples/canonical
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml

from dpm.manifest_loader import find_all_manifests
from dpm.validators.detect_breaking_changes import is_avro_nullable, is_compatible_type_change
from dpm.validators.report import Finding, Severity, ValidationReport, print_report
from dpm.validators.validate_manifest import CANONICAL_ENTITY_KIND

# A conforms_to entity reference pins a MAJOR version only: "name@N".
ENTITY_REF_RE = re.compile(r"^(?P<name>[a-z][a-z0-9_]*)@(?P<major>\d+)$")


class ConformanceValidator:
    """Validates data products against canonical entity definitions."""

    def __init__(self, registry_base: Path) -> None:
        """Initialize with the canonical registry base directory.

        Args:
            registry_base: Directory containing ``<entity>/v<major>/`` folders.
        """
        self.registry_base = registry_base

    def validate_manifest(self, manifest_path: Path) -> ValidationReport:
        """Validate a single product manifest's conformance declarations."""
        report = ValidationReport(manifest_path=str(manifest_path))

        try:
            with open(manifest_path, encoding="utf-8") as f:
                manifest = yaml.safe_load(f) or {}
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

        # A canonical entity does not conform to anything; nothing to check.
        if manifest.get("kind") == CANONICAL_ENTITY_KIND:
            return report

        conforms_to = manifest.get("metadata", {}).get("conforms_to")
        if not conforms_to:
            # Outside the EDM: a plain contract, no conformance to enforce.
            return report

        if not isinstance(conforms_to, list):
            report.add_finding(
                Finding(
                    rule="conforms_to_malformed",
                    severity=Severity.ERROR,
                    message="metadata.conforms_to must be a list of entity declarations",
                    path="metadata.conforms_to",
                    suggestion="Use a list: 'conforms_to: [{entity: customer@1}]'",
                )
            )
            return report

        product_fields = self._load_schema_fields(manifest, manifest_path)
        product_by_name: dict[str, dict[str, Any]] = {}
        for fld in product_fields:
            fname = fld.get("name")
            if isinstance(fname, str):
                product_by_name[fname] = fld

        for index, entry in enumerate(conforms_to):
            self._validate_entry(entry, index, product_by_name, report)

        return report

    def _validate_entry(
        self,
        entry: Any,
        index: int,
        product_by_name: dict[str, dict[str, Any]],
        report: ValidationReport,
    ) -> None:
        """Validate a single ``conforms_to`` entry against the registry."""
        path = f"metadata.conforms_to[{index}]"

        if not isinstance(entry, dict) or "entity" not in entry:
            report.add_finding(
                Finding(
                    rule="conforms_to_malformed",
                    severity=Severity.ERROR,
                    message="Each conforms_to entry must be an object with an 'entity' key",
                    path=path,
                    suggestion="Use '{entity: customer@1, rename: {...}}'",
                )
            )
            return

        ref = str(entry["entity"])
        match = ENTITY_REF_RE.match(ref)
        if not match:
            report.add_finding(
                Finding(
                    rule="conforms_to_malformed",
                    severity=Severity.ERROR,
                    message=f"Invalid entity reference '{ref}', expected 'name@MAJOR' (e.g. customer@1)",
                    path=f"{path}.entity",
                    suggestion="Pin the major version only, e.g. 'customer@1'",
                )
            )
            return

        name = match.group("name")
        major = match.group("major")
        rename = entry.get("rename") or {}
        if not isinstance(rename, dict):
            report.add_finding(
                Finding(
                    rule="conforms_to_malformed",
                    severity=Severity.ERROR,
                    message=f"'rename' for entity '{ref}' must be a mapping of canonical->physical names",
                    path=f"{path}.rename",
                )
            )
            return

        entity_dir = self.registry_base / name / f"v{major}"
        entity_manifest_path = entity_dir / "manifest.yaml"

        if not (self.registry_base / name).is_dir():
            report.add_finding(
                Finding(
                    rule="conforms_to_unknown_entity",
                    severity=Severity.ERROR,
                    message=f"Unknown canonical entity '{name}' (not found in registry)",
                    path=f"{path}.entity",
                    suggestion=f"Register '{name}' in the canonical registry, or fix the reference",
                )
            )
            return

        if not entity_manifest_path.exists():
            report.add_finding(
                Finding(
                    rule="conforms_to_unresolved_version",
                    severity=Severity.ERROR,
                    message=f"Canonical entity '{name}' has no version v{major} (sunset or never existed)",
                    path=f"{path}.entity",
                    suggestion=f"Migrate to an available major version of '{name}'",
                )
            )
            return

        try:
            with open(entity_manifest_path, encoding="utf-8") as f:
                entity_manifest = yaml.safe_load(f) or {}
        except Exception as e:
            report.add_finding(
                Finding(
                    rule="conforms_to_unresolved_version",
                    severity=Severity.ERROR,
                    message=f"Cannot read canonical entity '{ref}': {e}",
                    path=f"{path}.entity",
                )
            )
            return

        if entity_manifest.get("kind") != CANONICAL_ENTITY_KIND:
            report.add_finding(
                Finding(
                    rule="conforms_to_unknown_entity",
                    severity=Severity.ERROR,
                    message=f"Registry target '{ref}' is not a canonical_entity",
                    path=f"{path}.entity",
                )
            )
            return

        # A deprecated entity version still resolves, but the product should
        # migrate before its sunset date.
        if entity_manifest.get("status") == "deprecated":
            sunset = entity_manifest.get("deprecation", {}).get("sunset_date", "unknown")
            report.add_finding(
                Finding(
                    rule="conforms_to_deprecated",
                    severity=Severity.WARNING,
                    message=f"Canonical entity '{ref}' is deprecated (sunset: {sunset})",
                    path=f"{path}.entity",
                    suggestion="Plan migration to the next major version",
                )
            )

        self._check_attributes(ref, entity_manifest, entity_dir, rename, product_by_name, path, report)

    def _check_attributes(
        self,
        ref: str,
        entity_manifest: dict[str, Any],
        entity_dir: Path,
        rename: dict[str, str],
        product_by_name: dict[str, dict[str, Any]],
        path: str,
        report: ValidationReport,
    ) -> None:
        """Check the product carries every mandatory attribute, compatibly typed."""
        entity_fields = self._load_schema_fields(entity_manifest, entity_dir / "manifest.yaml")

        # Mandatory canonical attributes are the non-nullable top-level fields.
        for attr in entity_fields:
            attr_name = attr.get("name")
            if not attr_name or is_avro_nullable(attr):
                continue

            physical_name = rename.get(attr_name, attr_name)
            product_field = product_by_name.get(physical_name)

            if product_field is None:
                hint = (
                    f"Add field '{physical_name}'"
                    if physical_name != attr_name
                    else f"Add field '{attr_name}' (or map it via rename)"
                )
                report.add_finding(
                    Finding(
                        rule="conformance_missing_attribute",
                        severity=Severity.ERROR,
                        message=f"'{ref}' requires mandatory attribute '{attr_name}', "
                        f"expected as field '{physical_name}'",
                        path=f"{path}.entity",
                        suggestion=hint,
                    )
                )
                continue

            if not is_compatible_type_change(product_field.get("type"), attr.get("type")):
                report.add_finding(
                    Finding(
                        rule="conformance_type_mismatch",
                        severity=Severity.ERROR,
                        message=f"Field '{physical_name}' type is not compatible with "
                        f"canonical attribute '{attr_name}' of '{ref}'",
                        path=f"{path}.entity",
                        suggestion=f"Use a type compatible with the canonical '{attr_name}'",
                    )
                )

            # A mandatory canonical attribute cannot be satisfied by a nullable
            # field: that would allow the attribute to be absent, contradicting
            # the entity's guarantee.
            if is_avro_nullable(product_field):
                report.add_finding(
                    Finding(
                        rule="conformance_nullable_attribute",
                        severity=Severity.ERROR,
                        message=f"Field '{physical_name}' is nullable but canonical attribute "
                        f"'{attr_name}' of '{ref}' is mandatory",
                        path=f"{path}.entity",
                        suggestion=f"Make '{physical_name}' non-nullable to satisfy '{attr_name}'",
                    )
                )

    def _load_schema_fields(
        self, manifest: dict[str, Any], manifest_path: Path
    ) -> list[dict[str, Any]]:
        """Load the top-level Avro schema fields, or [] if unavailable."""
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


def main() -> None:
    """Entry point."""
    parser = argparse.ArgumentParser(
        description="Validate data product conformance to the canonical Enterprise Data Model"
    )
    parser.add_argument("manifest", nargs="?", help="Path to a product manifest.yaml")
    parser.add_argument("--all", action="store_true", help="Validate all manifests")
    parser.add_argument("--base-path", default=".", help="Base path for product manifests")
    parser.add_argument(
        "--registry-path",
        required=True,
        help="Path to the canonical registry (contains <entity>/v<major>/ folders)",
    )
    parser.add_argument("--output", help="Save the JSON report to a file")

    args = parser.parse_args()
    validator = ConformanceValidator(Path(args.registry_path))
    reports: list[ValidationReport] = []

    if args.manifest:
        manifest_path = Path(args.manifest)
        if not manifest_path.exists():
            print(f"Manifest not found: {manifest_path}", file=sys.stderr)
            sys.exit(1)
        reports.append(validator.validate_manifest(manifest_path))
    elif args.all:
        manifests = find_all_manifests(Path(args.base_path))
        if not manifests:
            print("No manifests found", file=sys.stderr)
            sys.exit(1)
        for manifest_path in manifests:
            reports.append(validator.validate_manifest(manifest_path))
    else:
        parser.print_help()
        sys.exit(1)

    for report in reports:
        print_report(report)

    total_errors = sum(r.error_count for r in reports)
    passed = sum(1 for r in reports if r.passed)
    failed = len(reports) - passed

    print(f"\n{'=' * 60}")
    print("CONFORMANCE SUMMARY")
    print(f"{'=' * 60}")
    print(f"Manifests: {len(reports)} ({passed} passed, {failed} failed)")
    print(f"Total errors: {total_errors}")

    if args.output:
        json_report = {
            "summary": {
                "total_manifests": len(reports),
                "passed": passed,
                "failed": failed,
                "total_errors": total_errors,
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

    sys.exit(1 if failed > 0 else 0)


if __name__ == "__main__":
    main()
