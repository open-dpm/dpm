#!/usr/bin/env python3
"""
Validate manifest YAML syntax and required fields.

This script performs basic validation of data manifests:
- YAML syntax correctness
- Presence of required manifest.yaml sections
- Correct version format (spec_version, manifest_version)
- Validity of the metadata, owner and lineage structures
- Correctness of file references (schema.avsc, semantics.yml, quality_rules.yml, sla.yml)

Does not perform:
- Breaking-change detection (see detect_breaking_changes.py)
- Governance checks (see validate_governance.py)

Exit codes:
    0 - All manifests are valid
    1 - Validation errors found

Usage:
    # Validate a single manifest
    python validate_manifest.py examples/sales/orders/manifest.yaml

    # Validate all manifests under examples/
    python validate_manifest.py --all

    # Validate manifests in a specific domain
    python validate_manifest.py --domain sales

Examples:
    python validate_manifest.py examples/sales/orders/manifest.yaml
    python validate_manifest.py --all --json-output validation_report.json
"""

import argparse
import json
import logging
import re
import sys
from pathlib import Path

import yaml

from dpm.manifest_loader import ManifestLoader, find_all_manifests

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

SNAKE_CASE_RE = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$")
VALID_STATUSES = {"draft", "active", "deprecated", "retired"}
# A data product publishes rows; a canonical_entity is a definition without
# rows (the shared standard a product conforms to). Absent kind = data_product.
VALID_KINDS = {"data_product", "canonical_entity"}
CANONICAL_ENTITY_KIND = "canonical_entity"
# Canonical entities live in a v<major>/ directory; its number must match the
# major of the entity's manifest_version (guards against copy/paste mistakes).
VERSION_DIR_RE = re.compile(r"^v(\d+)$")
VALID_DATA_CATEGORIES = {
    "transactional_data",
    "master_data",
    "reference_data",
    "analytical_data",
}
SEMANTICS_SECTION_TYPES = {
    "business_terms": list,
    "interpretation": dict,
    "typical_questions": list,
    "ai_hints": dict,
}
ALLOWED_SEMANTICS_SECTIONS = {"version", *SEMANTICS_SECTION_TYPES}

# SemVer 2.0 regex: MAJOR.MINOR.PATCH[-prerelease][+buildmetadata]
# Ref: https://semver.org/#is-there-a-suggested-regular-expression-regex-to-check-a-semver-string
SEMVER_PATTERN = re.compile(
    r"^\d+\.\d+\.\d+"
    r"(-[a-zA-Z0-9]+(\.[a-zA-Z0-9]+)*)?"
    r"(\+[a-zA-Z0-9]+(\.[a-zA-Z0-9]+)*)?$"
)


def validate_yaml_syntax(file_path: Path) -> list[str]:
    """Validate YAML syntax.

    Args:
        file_path: Path to the manifest YAML file.

    Returns:
        List of error strings.  Empty if the file is valid YAML.
    """
    errors: list[str] = []
    try:
        with open(file_path, encoding="utf-8") as f:
            yaml.safe_load(f)
    except yaml.YAMLError as e:
        errors.append(f"YAML syntax error: {e}")
    except Exception as e:
        errors.append(f"Error reading file: {e}")
    return errors


def validate_semantics_file(file_path: Path) -> list[str]:
    """Validate lightweight structure of semantics.yml."""
    errors: list[str] = []

    try:
        with open(file_path, encoding="utf-8") as f:
            semantics = yaml.safe_load(f)
    except yaml.YAMLError as e:
        return [f"Invalid YAML in semantics file: {e}"]
    except Exception as e:
        return [f"Error reading semantics file: {e}"]

    if semantics is None:
        return []

    if not isinstance(semantics, dict):
        return ["Semantics file must be a YAML object"]

    for section in sorted(set(semantics) - ALLOWED_SEMANTICS_SECTIONS):
        errors.append(
            f"Unknown semantics section '{section}'. "
            f"Allowed sections: {sorted(ALLOWED_SEMANTICS_SECTIONS)}"
        )

    for section, expected_type in SEMANTICS_SECTION_TYPES.items():
        value = semantics.get(section)
        if value is not None and not isinstance(value, expected_type):
            errors.append(
                f"Invalid semantics section '{section}': "
                f"expected {expected_type.__name__}, got {type(value).__name__}"
            )

    return errors


def validate_required_fields(file_path: Path, manifest: dict | None = None) -> list[str]:
    """Validate required fields are present.

    Args:
        file_path: Path to the manifest YAML file (used for resolving
            relative schema references).
        manifest: Pre-parsed manifest dict.  When ``None`` the file is
            loaded from *file_path* (legacy/backward-compatible path).

    Returns:
        List of error strings.
    """
    errors: list[str] = []

    if manifest is None:
        with open(file_path, encoding="utf-8") as f:
            manifest = yaml.safe_load(f)

    if not manifest:
        return ["Manifest is empty"]

    kind = manifest.get("kind")
    if kind is not None and kind not in VALID_KINDS:
        errors.append(f"Invalid kind '{kind}'. Valid kinds: {sorted(VALID_KINDS)}")
    is_entity = kind == CANONICAL_ENTITY_KIND

    # Sections required for every manifest, including canonical entities.
    required_top = [
        "spec_version",
        "manifest_version",
        "status",
        "metadata",
        "schema",
        "changelog",
    ]
    # A canonical entity carries no rows, so it needs no semantics glossary,
    # quality rules, SLA or lineage. These stay required for data products.
    if not is_entity:
        required_top += ["semantics", "quality_rules", "sla", "lineage"]
    for field in required_top:
        if field not in manifest:
            errors.append(f"Missing required field: {field}")

    status = manifest.get("status")
    if status and status not in VALID_STATUSES:
        errors.append(
            f"Invalid status '{status}'. Valid statuses: {sorted(VALID_STATUSES)}"
        )

    # Required metadata fields. data_category classifies row-bearing data, so
    # it is not required for a canonical entity.
    metadata = manifest.get("metadata", {})
    required_metadata = ["name", "namespace", "owner"]
    if not is_entity:
        required_metadata.append("data_category")
    for field in required_metadata:
        if field not in metadata:
            errors.append(f"Missing required metadata field: {field}")

    data_category = metadata.get("data_category")
    if data_category and data_category not in VALID_DATA_CATEGORIES:
        errors.append(
            f"Invalid data_category '{data_category}'. "
            f"Valid categories: {sorted(VALID_DATA_CATEGORIES)}"
        )

    # Required owner fields
    owner = metadata.get("owner", {})
    required_owner = ["team", "email"]
    for field in required_owner:
        if field not in owner:
            errors.append(f"Missing required owner field: {field}")

    # Validate schema section
    schema = manifest.get("schema", {})

    # Multi-file structure: schema.file references external .avsc file
    if "file" in schema:
        # Validate that the referenced file exists
        schema_file_ref = schema.get("file", "")
        schema_file_path = file_path.parent / schema_file_ref
        if not schema_file_path.exists():
            errors.append(f"Referenced schema file not found: {schema_file_ref}")
        else:
            # Validate the .avsc file is valid JSON (Avro schema)
            try:
                with open(schema_file_path, encoding="utf-8") as f:
                    avro_schema = json.load(f)
                # Check for required Avro fields
                if "type" not in avro_schema:
                    errors.append("Avro schema missing 'type' field")
                if "name" not in avro_schema:
                    errors.append("Avro schema missing 'name' field")
                if "fields" not in avro_schema:
                    errors.append("Avro schema missing 'fields' array")
            except json.JSONDecodeError as e:
                errors.append(f"Invalid JSON in schema file: {e}")

        # Format is still required for multi-file structure
        if "format" not in schema:
            errors.append("Missing required schema field: format")

    # Legacy inline structure: schema.fields directly in manifest
    elif "fields" in schema:
        required_schema = ["format", "fields"]
        for field in required_schema:
            if field not in schema:
                errors.append(f"Missing required schema field: {field}")

        # Validate fields array
        fields = schema.get("fields", [])
        if not fields:
            errors.append("Schema must have at least one field")

        for i, field in enumerate(fields):
            if "name" not in field:
                errors.append(f"Field {i}: missing 'name'")
            if "type" not in field:
                errors.append(f"Field {i}: missing 'type'")

    else:
        errors.append("Schema must have either 'file' (multi-file) or 'fields' (inline)")

    # semantics / quality_rules / sla / lineage describe row-bearing data and
    # are required only for data products, not for canonical entities.
    if not is_entity:
        semantics = manifest.get("semantics", {})
        if "file" not in semantics:
            errors.append("Missing required semantics field: file")
        else:
            semantics_file_ref = semantics.get("file", "")
            semantics_file_path = file_path.parent / semantics_file_ref
            if not semantics_file_path.exists():
                errors.append(f"Referenced semantics file not found: {semantics_file_ref}")
            else:
                errors.extend(validate_semantics_file(semantics_file_path))

        quality_rules = manifest.get("quality_rules", {})
        if "file" not in quality_rules:
            errors.append("Missing required quality_rules field: file")
        else:
            rules_file_ref = quality_rules.get("file", "")
            rules_file_path = file_path.parent / rules_file_ref
            if not rules_file_path.exists():
                errors.append(f"Referenced quality rules file not found: {rules_file_ref}")

        sla = manifest.get("sla", {})
        if "file" not in sla:
            errors.append("Missing required sla field: file")
        else:
            sla_file_ref = sla.get("file", "")
            sla_file_path = file_path.parent / sla_file_ref
            if not sla_file_path.exists():
                errors.append(f"Referenced SLA file not found: {sla_file_ref}")

        lineage = manifest.get("lineage", {})
        if not isinstance(lineage.get("upstream"), list):
            errors.append("Missing required lineage field: upstream")
        if not isinstance(lineage.get("downstream"), list):
            errors.append("Missing required lineage field: downstream")

    changelog = manifest.get("changelog")
    if not isinstance(changelog, list) or not changelog:
        errors.append("Missing required changelog entries")

    # A canonical entity in a v<major>/ directory must carry a matching major.
    if is_entity:
        dir_match = VERSION_DIR_RE.match(file_path.parent.name)
        version = manifest.get("manifest_version")
        if dir_match and isinstance(version, str):
            dir_major = dir_match.group(1)
            version_major = version.split(".")[0]
            if dir_major != version_major:
                errors.append(
                    f"Canonical entity in 'v{dir_major}/' must have manifest_version "
                    f"major {dir_major}, got '{version}'"
                )

    return errors


def validate_naming_conventions(file_path: Path, manifest: dict | None = None) -> list[str]:
    """Validate naming conventions.

    Args:
        file_path: Path to the manifest YAML file (used for resolving
            relative schema references).
        manifest: Pre-parsed manifest dict.  When ``None`` the file is
            loaded from *file_path*.

    Returns:
        List of error strings.
    """
    errors: list[str] = []

    if manifest is None:
        with open(file_path, encoding="utf-8") as f:
            manifest = yaml.safe_load(f)

    metadata = manifest.get("metadata", {})

    # Name should be snake_case
    name = metadata.get("name", "")
    if name and not SNAKE_CASE_RE.match(name):
        errors.append(f"Name '{name}' should be snake_case (lowercase alphanumeric with underscores)")

    # Namespace should be snake_case
    namespace = metadata.get("namespace", "")
    if namespace and not SNAKE_CASE_RE.match(namespace):
        errors.append(f"Namespace '{namespace}' should be snake_case")

    # Validate field names
    schema = manifest.get("schema", {})
    fields: list[dict] = []

    # Multi-file structure: load fields from .avsc file
    if "file" in schema:
        schema_file_ref = schema.get("file", "")
        schema_file_path = file_path.parent / schema_file_ref
        if schema_file_path.exists():
            try:
                with open(schema_file_path, encoding="utf-8") as f:
                    avro_schema = json.load(f)
                fields = avro_schema.get("fields", [])
            except (json.JSONDecodeError, Exception):
                pass  # Error already reported in validate_required_fields
    else:
        # Inline structure
        fields = schema.get("fields", [])

    # Field names should be snake_case
    for field in fields:
        field_name = field.get("name", "")
        if field_name and not SNAKE_CASE_RE.match(field_name):
            errors.append(f"Field name '{field_name}' should be snake_case")

    return errors


def validate_version_format(file_path: Path, manifest: dict | None = None) -> list[str]:
    """Validate version format (SemVer 2.0).

    Supports the full SemVer 2.0 specification including optional
    pre-release identifiers (e.g. ``1.0.0-beta.1``) and build metadata
    (e.g. ``1.0.0+build.42``).

    Also verifies that version fields are strings.  YAML silently parses
    unquoted ``1.0`` as a float, which is a common authoring mistake.

    Args:
        file_path: Path to the manifest YAML file (unused when
            *manifest* is provided, kept for API compatibility).
        manifest: Pre-parsed manifest dict.  When ``None`` the file is
            loaded from *file_path*.

    Returns:
        List of error strings.

    Examples:
        >>> validate_version_format(Path("."), {"spec_version": "1.0.0", "manifest_version": "2.1.0"})
        []
        >>> validate_version_format(Path("."), {"spec_version": "1.0.0-beta.1+build.42", "manifest_version": "2.1.0"})
        []
    """
    errors: list[str] = []

    if manifest is None:
        with open(file_path, encoding="utf-8") as f:
            manifest = yaml.safe_load(f)

    version_fields = ("spec_version", "manifest_version")
    for field_name in version_fields:
        value = manifest.get(field_name)
        if value is None:
            continue

        # YAML parses unquoted 1.0 as float and 1 as int -- catch that.
        if not isinstance(value, str):
            errors.append(
                f"{field_name} must be a quoted string in YAML, "
                f"got {type(value).__name__} "
                f'(e.g. use "{field_name}: \'1.0.0\'" instead of "{field_name}: {value}")'
            )
            continue

        if not SEMVER_PATTERN.match(value):
            errors.append(
                f"{field_name} '{value}' is not valid SemVer 2.0 "
                f"(expected X.Y.Z[-prerelease][+build])"
            )

    return errors


def validate_manifest(file_path: Path) -> list[str]:
    """Run all validations on a manifest file.

    YAML is loaded once via ``ManifestLoader`` and the parsed dict is
    passed to each validation function, avoiding redundant I/O and
    parsing.
    """
    all_errors: list[str] = []

    # Syntax validation (must still open the file to catch YAML errors)
    syntax_errors = validate_yaml_syntax(file_path)
    if syntax_errors:
        return syntax_errors  # Can't continue if syntax is broken

    # Load YAML once and reuse across all validators
    loader = ManifestLoader()
    manifest = loader.load_manifest(file_path)

    all_errors.extend(validate_required_fields(file_path, manifest))
    all_errors.extend(validate_naming_conventions(file_path, manifest))
    all_errors.extend(validate_version_format(file_path, manifest))

    return all_errors


def main():
    parser = argparse.ArgumentParser(description="Validate data manifests")
    parser.add_argument(
        "path",
        nargs="?",
        help="Path to manifest.yaml file",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Validate all manifests in examples directory",
    )
    parser.add_argument(
        "--base-path",
        default=".",
        help="Base path for manifests directory",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose (DEBUG) logging",
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Suppress INFO messages, show only errors",
    )
    parser.add_argument(
        "--json-output",
        type=str,
        metavar="FILE",
        help="Write validation report as JSON to FILE",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    elif args.quiet:
        logging.getLogger().setLevel(logging.ERROR)

    base_path = Path(args.base_path)
    
    if args.all:
        manifests = find_all_manifests(base_path)
        if not manifests:
            logger.error("No manifests found in examples directory")
            sys.exit(1)
    elif args.path:
        manifests = [Path(args.path)]
    else:
        parser.print_help()
        sys.exit(1)
    
    total_errors = 0
    results_list: list[dict] = []

    for manifest_path in manifests:
        logger.info("Validating: %s", manifest_path)
        errors = validate_manifest(manifest_path)

        result_entry = {
            "file": str(manifest_path),
            "valid": len(errors) == 0,
            "errors": errors,
        }
        results_list.append(result_entry)

        if errors:
            logger.error("%d error(s) found:", len(errors))
            for error in errors:
                logger.error("  %s", error)
            total_errors += len(errors)
        else:
            logger.info("Valid")

    print(f"\n{'=' * 40}")
    print(f"Validated {len(manifests)} manifest(s)")

    if total_errors > 0:
        print(f"Total errors: {total_errors}")

    else:
        print("All manifests are valid")

    if args.json_output:
        report = {
            "total_files": len(manifests),
            "total_errors": total_errors,
            "results": results_list,
        }
        with open(args.json_output, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print(f"JSON report written to {args.json_output}")

    sys.exit(1 if total_errors > 0 else 0)


if __name__ == "__main__":
    main()
