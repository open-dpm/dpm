#!/usr/bin/env python3
"""
Detect breaking changes between manifest versions.

Breaking changes:
- Removing a field
- Changing a field's type
- Making an optional field required
- Changing enum values (removing options)
- Tightening constraints (increasing min, decreasing max)

Non-breaking changes:
- Adding a new nullable field
- Adding new enum values
- Relaxing constraints

Usage:
    python detect_breaking_changes.py --base-ref origin/main --head-ref HEAD
    python detect_breaking_changes.py --old old_manifest.yaml --new new_manifest.yaml
"""

import argparse
import json
import subprocess
import sys
from enum import Enum
from pathlib import Path

import yaml
from pydantic import BaseModel

from dpm.lib.common import get_file_at_ref

# Avro type promotion rules (reader can read writer's data)
# https://avro.apache.org/docs/current/specification/#schema-resolution
AVRO_COMPATIBLE_PROMOTIONS = {
    "int": {"long", "float", "double"},
    "long": {"float", "double"},
    "float": {"double"},
    "string": {"bytes"},
    "bytes": {"string"},
}


def is_compatible_type_change(old_type, new_type) -> bool:
    """Check whether the type change is a backward-compatible promotion."""
    old_base = _get_base_type(old_type)
    new_base = _get_base_type(new_type)
    if old_base == new_base:
        return True
    return new_base in AVRO_COMPATIBLE_PROMOTIONS.get(old_base, set())


def _get_base_type(field_type) -> str:
    """Extract the base type from an Avro type definition."""
    if isinstance(field_type, str):
        return field_type
    if isinstance(field_type, dict):
        return field_type.get("type", "")
    if isinstance(field_type, list):
        # Union: return the first non-null type
        for t in field_type:
            if t != "null":
                return _get_base_type(t)
    return ""


class ChangeType(str, Enum):
    BREAKING = "breaking"
    NON_BREAKING = "non_breaking"
    PATCH = "patch"


class Change(BaseModel):
    """Represents a change detected in manifest."""
    manifest: str
    field: str | None
    change_type: ChangeType
    description: str
    
    model_config = {
        "use_enum_values": True,
    }


def get_changed_files(base_ref: str, head_ref: str) -> list[str]:
    """Get list of changed files in examples/."""
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", base_ref, head_ref, "--", "examples/"],
            capture_output=True,
            text=True,
            check=True,
        )
        files = [f for f in result.stdout.strip().split("\n") if f]
        return files
    except subprocess.CalledProcessError:
        return []


def load_avro_fields(avsc_content: str, recursive: bool = True) -> list[dict]:
    """Extract fields from an Avro schema, including nested record types."""
    try:
        schema = json.loads(avsc_content)
    except (json.JSONDecodeError, AttributeError):
        return []

    fields = schema.get("fields", [])
    if not recursive:
        return fields

    all_fields = []
    for field in fields:
        all_fields.append(field)
        # Recurse into nested records
        nested = _extract_nested_fields(field, prefix=field["name"])
        all_fields.extend(nested)
    return all_fields


def _extract_nested_fields(field: dict, prefix: str) -> list[dict]:
    """Recursively extract fields from nested record types."""
    nested = []
    field_type = field.get("type")

    # array of records: {"type": {"type": "array", "items": {"type": "record", ...}}}
    if isinstance(field_type, dict):
        if field_type.get("type") == "array":
            items = field_type.get("items", {})
            if isinstance(items, dict) and items.get("type") == "record":
                for sub_field in items.get("fields", []):
                    prefixed = {**sub_field, "name": f"{prefix}.{sub_field['name']}"}
                    nested.append(prefixed)
                    nested.extend(_extract_nested_fields(sub_field, prefix=prefixed["name"]))
        elif field_type.get("type") == "record":
            for sub_field in field_type.get("fields", []):
                prefixed = {**sub_field, "name": f"{prefix}.{sub_field['name']}"}
                nested.append(prefixed)
                nested.extend(_extract_nested_fields(sub_field, prefix=prefixed["name"]))

    # union types: ["null", {"type": "record", ...}]
    if isinstance(field_type, list):
        for variant in field_type:
            if isinstance(variant, dict) and variant.get("type") == "record":
                for sub_field in variant.get("fields", []):
                    prefixed = {**sub_field, "name": f"{prefix}.{sub_field['name']}"}
                    nested.append(prefixed)
                    nested.extend(_extract_nested_fields(sub_field, prefix=prefixed["name"]))

    return nested


def get_manifest_dir_from_file(file_path: str) -> str | None:
    """Determine the manifest directory from a changed file path."""
    parts = Path(file_path).parts
    # examples/<domain>/<entity>/ — three nesting levels
    if len(parts) >= 3 and parts[0] == "examples":
        return str(Path(*parts[:3]))
    return None


def is_avro_nullable(field: dict) -> bool:
    """Check whether a field is nullable in Avro format.

    Nullable: type = ["null", "X"] and default = None/null.
    Also supports the manifest.yaml style: required = false.
    """
    # manifest.yaml style
    if "required" in field:
        return not field["required"]
    # Avro style: union with null and default=null
    field_type = field.get("type")
    if isinstance(field_type, list) and "null" in field_type:
        return field.get("default") is None
    return False


def detect_field_changes(
    old_fields: list[dict],
    new_fields: list[dict],
    manifest_name: str,
) -> list[Change]:
    """Detect changes between old and new field definitions."""
    changes = []
    
    old_fields_dict = {f["name"]: f for f in old_fields}
    new_fields_dict = {f["name"]: f for f in new_fields}
    
    # Check for removed fields (BREAKING)
    for field_name in old_fields_dict:
        if field_name not in new_fields_dict:
            changes.append(Change(
                manifest=manifest_name,
                field=field_name,
                change_type=ChangeType.BREAKING,
                description=f"Field '{field_name}' was removed",
            ))
    
    # Check for new and modified fields
    for field_name, new_field in new_fields_dict.items():
        if field_name not in old_fields_dict:
            # New field — a nullable field is non-breaking
            if is_avro_nullable(new_field):
                changes.append(Change(
                    manifest=manifest_name,
                    field=field_name,
                    change_type=ChangeType.NON_BREAKING,
                    description=f"New optional/nullable field '{field_name}' added",
                ))
            else:
                changes.append(Change(
                    manifest=manifest_name,
                    field=field_name,
                    change_type=ChangeType.BREAKING,
                    description=f"New required field '{field_name}' added",
                ))
        else:
            # Existing field - check for changes
            old_field = old_fields_dict[field_name]
            
            # Type change
            if old_field.get("type") != new_field.get("type"):
                if is_compatible_type_change(old_field.get("type"), new_field.get("type")):
                    changes.append(Change(
                        manifest=manifest_name,
                        field=field_name,
                        change_type=ChangeType.NON_BREAKING,
                        description=f"Field '{field_name}' type promoted from '{old_field.get('type')}' to '{new_field.get('type')}' (compatible)",
                    ))
                else:
                    changes.append(Change(
                        manifest=manifest_name,
                        field=field_name,
                        change_type=ChangeType.BREAKING,
                        description=f"Field '{field_name}' type changed from '{old_field.get('type')}' to '{new_field.get('type')}'",
                    ))
            
            # Required change: false -> true (BREAKING)
            old_required = old_field.get("required", True)
            new_required = new_field.get("required", True)
            if not old_required and new_required:
                changes.append(Change(
                    manifest=manifest_name,
                    field=field_name,
                    change_type=ChangeType.BREAKING,
                    description=f"Field '{field_name}' changed from optional to required",
                ))
            elif old_required and not new_required:
                changes.append(Change(
                    manifest=manifest_name,
                    field=field_name,
                    change_type=ChangeType.NON_BREAKING,
                    description=f"Field '{field_name}' changed from required to optional",
                ))
            
            # Constraint changes
            old_constraints = old_field.get("constraints", {})
            new_constraints = new_field.get("constraints", {})
            
            # Enum values removed (BREAKING)
            old_enum = set(old_constraints.get("enum", []))
            new_enum = set(new_constraints.get("enum", []))
            if old_enum and new_enum:
                removed_values = old_enum - new_enum
                if removed_values:
                    changes.append(Change(
                        manifest=manifest_name,
                        field=field_name,
                        change_type=ChangeType.BREAKING,
                        description=f"Field '{field_name}' enum values removed: {removed_values}",
                    ))
                added_values = new_enum - old_enum
                if added_values:
                    changes.append(Change(
                        manifest=manifest_name,
                        field=field_name,
                        change_type=ChangeType.NON_BREAKING,
                        description=f"Field '{field_name}' enum values added: {added_values}",
                    ))
            
            # min_length increased (BREAKING — old values may become invalid)
            old_min_len = old_constraints.get("min_length")
            new_min_len = new_constraints.get("min_length")
            if old_min_len is not None and new_min_len is not None and new_min_len > old_min_len:
                changes.append(Change(
                    manifest=manifest_name,
                    field=field_name,
                    change_type=ChangeType.BREAKING,
                    description=f"Field '{field_name}' min_length increased from {old_min_len} to {new_min_len}",
                ))
            
            # max_length decreased (BREAKING — old values may become invalid)
            old_max_len = old_constraints.get("max_length")
            new_max_len = new_constraints.get("max_length")
            if old_max_len is not None and new_max_len is not None and new_max_len < old_max_len:
                changes.append(Change(
                    manifest=manifest_name,
                    field=field_name,
                    change_type=ChangeType.BREAKING,
                    description=f"Field '{field_name}' max_length decreased from {old_max_len} to {new_max_len}",
                ))
            
            # pattern changed (BREAKING — may reject previously valid values)
            old_pattern = old_constraints.get("pattern")
            new_pattern = new_constraints.get("pattern")
            if old_pattern and new_pattern and old_pattern != new_pattern:
                changes.append(Change(
                    manifest=manifest_name,
                    field=field_name,
                    change_type=ChangeType.BREAKING,
                    description=f"Field '{field_name}' pattern changed from '{old_pattern}' to '{new_pattern}'",
                ))
            
            # min/max for numeric fields (increasing min or decreasing max — BREAKING)
            old_min = old_constraints.get("min")
            new_min = new_constraints.get("min")
            if old_min is not None and new_min is not None and new_min > old_min:
                changes.append(Change(
                    manifest=manifest_name,
                    field=field_name,
                    change_type=ChangeType.BREAKING,
                    description=f"Field '{field_name}' min value increased from {old_min} to {new_min}",
                ))
            
            old_max = old_constraints.get("max")
            new_max = new_constraints.get("max")
            if old_max is not None and new_max is not None and new_max < old_max:
                changes.append(Change(
                    manifest=manifest_name,
                    field=field_name,
                    change_type=ChangeType.BREAKING,
                    description=f"Field '{field_name}' max value decreased from {old_max} to {new_max}",
                ))
    
    return changes


def detect_avro_metadata_changes(
    old_schema: dict,
    new_schema: dict,
    manifest_name: str,
) -> list[Change]:
    """Detect breaking changes in top-level Avro schema metadata.

    The following are classified as breaking changes:
    - Change of top-level ``namespace``
    - Change of top-level ``name``
    - Change of ``aliases``

    Args:
        old_schema: Parsed old Avro schema dict.
        new_schema: Parsed new Avro schema dict.
        manifest_name: Human-readable manifest identifier for reports.

    Returns:
        List of detected changes.
    """
    changes: list[Change] = []

    old_namespace = old_schema.get("namespace")
    new_namespace = new_schema.get("namespace")
    if old_namespace is not None and old_namespace != new_namespace:
        changes.append(Change(
            manifest=manifest_name,
            field=None,
            change_type=ChangeType.BREAKING,
            description=(
                f"Avro namespace changed from '{old_namespace}' to '{new_namespace}'"
            ),
        ))

    old_name = old_schema.get("name")
    new_name = new_schema.get("name")
    if old_name is not None and old_name != new_name:
        changes.append(Change(
            manifest=manifest_name,
            field=None,
            change_type=ChangeType.BREAKING,
            description=(
                f"Avro schema name changed from '{old_name}' to '{new_name}'"
            ),
        ))

    old_aliases = old_schema.get("aliases")
    new_aliases = new_schema.get("aliases")
    if old_aliases is not None and old_aliases != new_aliases:
        changes.append(Change(
            manifest=manifest_name,
            field=None,
            change_type=ChangeType.BREAKING,
            description=(
                f"Avro aliases changed from {old_aliases} to {new_aliases}"
            ),
        ))

    return changes


def detect_breaking_changes(old_manifest: dict, new_manifest: dict) -> list[Change]:
    """Detect all changes between old and new manifest."""
    changes = []

    manifest_name = new_manifest.get("metadata", {}).get("name", "unknown")

    old_fields = old_manifest.get("schema", {}).get("fields", [])
    new_fields = new_manifest.get("schema", {}).get("fields", [])

    changes.extend(detect_field_changes(old_fields, new_fields, manifest_name))

    # Check for description-only changes (PATCH)
    if not changes:
        if old_manifest != new_manifest:
            changes.append(Change(
                manifest=manifest_name,
                field=None,
                change_type=ChangeType.PATCH,
                description="Non-schema changes (description, metadata, etc.)",
            ))

    return changes


def main():
    parser = argparse.ArgumentParser(description="Detect breaking changes in manifests")
    parser.add_argument("--base-ref", help="Base git ref (e.g., origin/main)")
    parser.add_argument("--head-ref", default="HEAD", help="Head git ref")
    parser.add_argument("--old", help="Path to old manifest file")
    parser.add_argument("--new", help="Path to new manifest file")
    parser.add_argument("--output", help="Output file for JSON report")
    
    args = parser.parse_args()
    
    all_changes = []
    
    if args.old and args.new:
        # Compare two specific files
        old_path = Path(args.old)
        new_path = Path(args.new)
        
        # Determine file type by extension
        if old_path.suffix == ".avsc" and new_path.suffix == ".avsc":
            # Direct comparison of Avro schemas
            old_avsc_content = old_path.read_text()
            new_avsc_content = new_path.read_text()

            old_fields = load_avro_fields(old_avsc_content)
            new_fields = load_avro_fields(new_avsc_content)

            # Extract manifest name and full schemas for metadata checks
            try:
                old_schema_dict = json.loads(old_avsc_content)
            except json.JSONDecodeError:
                old_schema_dict = {}
            try:
                new_schema_dict = json.loads(new_avsc_content)
                manifest_name = new_schema_dict.get("name", new_path.stem)
            except json.JSONDecodeError:
                new_schema_dict = {}
                manifest_name = new_path.stem

            changes = detect_field_changes(old_fields, new_fields, manifest_name)
            all_changes.extend(changes)

            # Detect namespace/name/aliases changes
            all_changes.extend(
                detect_avro_metadata_changes(old_schema_dict, new_schema_dict, manifest_name)
            )
        else:
            # Comparison of manifest.yaml files
            with open(args.old, encoding="utf-8") as f:
                old_manifest = yaml.safe_load(f)
            with open(args.new, encoding="utf-8") as f:
                new_manifest = yaml.safe_load(f)
            
            changes = detect_breaking_changes(old_manifest, new_manifest)
            all_changes.extend(changes)
    
    elif args.base_ref:
        # Compare git refs
        changed_files = get_changed_files(args.base_ref, args.head_ref)

        # Collect unique manifest directories
        manifest_dirs: set[str] = set()
        for file_path in changed_files:
            manifest_dir = get_manifest_dir_from_file(file_path)
            if manifest_dir:
                manifest_dirs.add(manifest_dir)

        for manifest_dir in manifest_dirs:
            manifest_yaml = f"{manifest_dir}/manifest.yaml"
            schema_avsc = f"{manifest_dir}/schema.avsc"

            # Load manifest.yaml (current and base)
            old_yaml_content = get_file_at_ref(manifest_yaml, args.base_ref)
            if old_yaml_content is None:
                print(f"📋 New manifest: {manifest_dir}")
                continue

            new_yaml_path = Path(manifest_yaml)
            if not new_yaml_path.exists():
                continue
            new_yaml_content = new_yaml_path.read_text()

            old_manifest = yaml.safe_load(old_yaml_content)
            new_manifest = yaml.safe_load(new_yaml_content)

            # If the manifest uses schema.file, load the Avro schema
            schema_file = old_manifest.get("schema", {}).get("file")
            if schema_file:
                old_avsc = get_file_at_ref(schema_avsc, args.base_ref)
                new_avsc_path = Path(schema_avsc)
                new_avsc = new_avsc_path.read_text() if new_avsc_path.exists() else None

                if old_avsc and new_avsc:
                    old_fields = load_avro_fields(old_avsc)
                    new_fields = load_avro_fields(new_avsc)
                    manifest_name = new_manifest.get("metadata", {}).get("name", "unknown")
                    changes = detect_field_changes(old_fields, new_fields, manifest_name)
                    all_changes.extend(changes)

                    # Detect namespace/name/aliases changes in Avro schema
                    try:
                        old_schema_dict = json.loads(old_avsc)
                    except json.JSONDecodeError:
                        old_schema_dict = {}
                    try:
                        new_schema_dict = json.loads(new_avsc)
                    except json.JSONDecodeError:
                        new_schema_dict = {}
                    all_changes.extend(
                        detect_avro_metadata_changes(old_schema_dict, new_schema_dict, manifest_name)
                    )

                    # Also check manifest.yaml (versions, metadata)
                    if old_manifest != new_manifest:
                        meta_changes = detect_breaking_changes(old_manifest, new_manifest)
                        all_changes.extend(meta_changes)
            else:
                # Inline fields — legacy logic
                changes = detect_breaking_changes(old_manifest, new_manifest)
                all_changes.extend(changes)
    
    else:
        parser.print_help()
        sys.exit(1)
    
    # Output results
    has_breaking = any(c.change_type == ChangeType.BREAKING for c in all_changes)
    
    report = {
        "has_breaking_changes": has_breaking,
        "total_changes": len(all_changes),
        "changes": [c.model_dump() for c in all_changes],
    }
    
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        print(f"Report written to {args.output}")
    
    # Print summary
    print(f"\n{'=' * 50}")
    print("CHANGE DETECTION REPORT")
    print(f"{'=' * 50}")
    
    breaking_changes = [c for c in all_changes if c.change_type == ChangeType.BREAKING]
    non_breaking_changes = [c for c in all_changes if c.change_type == ChangeType.NON_BREAKING]
    patch_changes = [c for c in all_changes if c.change_type == ChangeType.PATCH]
    
    if breaking_changes:
        print(f"\n🔴 BREAKING CHANGES ({len(breaking_changes)}):")
        for change in breaking_changes:
            print(f"   - {change.description}")
    
    if non_breaking_changes:
        print(f"\n🟡 Non-breaking changes ({len(non_breaking_changes)}):")
        for change in non_breaking_changes:
            print(f"   - {change.description}")
    
    if patch_changes:
        print(f"\n🟢 Patch changes ({len(patch_changes)}):")
        for change in patch_changes:
            print(f"   - {change.description}")
    
    if not all_changes:
        print("\n✅ No changes detected")
    
    # Exit with error if breaking changes found
    if has_breaking:
        print("\n⚠️  Breaking changes require MAJOR version bump!")
        sys.exit(1)
    
    sys.exit(0)


if __name__ == "__main__":
    main()
