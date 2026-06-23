#!/usr/bin/env python3
"""
Validate data quality rule files (quality_rules.yml).

This script checks that quality rules are defined correctly:
- YAML syntax validity
- Presence of required fields (name, type, severity, config)
- Correct rule types (not_null, unique, range, regex, enum, freshness, format, custom, sql, reference)
- Correct severity (error, warning, info)
- Validity of config parameters for each rule type

Supported rule types:
    - not_null: Field must not be empty
    - unique: Value must be unique within a batch/window
    - range: Numeric value must be within a given range (min/max)
    - regex: Value must match a regular expression
    - enum: Value must be one of an allowed set of values
    - freshness: Check data freshness via a timestamp field (max_age_minutes)
    - format: Format check (email, phone, uuid, iso_date, etc.)
    - custom: Custom validation logic (Python expression)
    - sql: SQL query for validation (for reference data checks)
    - reference: Check that a value exists in a reference table
    - currency: Data recency relative to the expected update interval
    - reasonableness: Soft check of business plausibility of values

Exit codes:
    0 - All rules are valid
    1 - Errors found in rules

Usage:
    # Validate a single rules file
    python validate_quality_rules.py examples/sales/orders/quality_rules.yml

    # Validate all rules files
    python validate_quality_rules.py --all

Examples:
    python validate_quality_rules.py examples/sales/orders/quality_rules.yml
    python validate_quality_rules.py --all --verbose
"""

import argparse
import json
import sys
from pathlib import Path

import yaml

VALID_RULE_TYPES = [
    "not_null",
    "unique",
    "range",
    "regex",
    "enum",
    "freshness",
    "format",
    "custom",
    "sql",
    "reference",
    "completeness",
    "currency",
    "reasonableness",
]

VALID_SEVERITIES = ["error", "warning", "info"]


def _validate_enum_against_schema(rule: dict, schema_path: Path) -> list[str]:
    """Cross-validate enum rule values against Avro schema symbols."""
    errors: list[str] = []
    field_name = rule.get("field")
    rule_values = rule.get("values", [])
    if not field_name or not rule_values:
        return errors
    try:
        with open(schema_path, encoding="utf-8") as f:
            schema = json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return errors
    for field in schema.get("fields", []):
        if field.get("name") != field_name:
            continue
        field_type = field.get("type")
        enum_type = None
        if isinstance(field_type, list):
            for t in field_type:
                if isinstance(t, dict) and t.get("type") == "enum":
                    enum_type = t
                    break
        elif isinstance(field_type, dict) and field_type.get("type") == "enum":
            enum_type = field_type
        if enum_type is None:
            return errors
        schema_symbols = set(enum_type.get("symbols", []))
        rule_value_set = set(rule_values)
        if schema_symbols != rule_value_set:
            missing_in_rules = schema_symbols - rule_value_set
            extra_in_rules = rule_value_set - schema_symbols
            if missing_in_rules:
                errors.append(f"enum values missing from quality rule but present in schema: {sorted(missing_in_rules)}")
            if extra_in_rules:
                errors.append(f"enum values in quality rule but missing from schema: {sorted(extra_in_rules)}")
        break
    return errors


def validate_quality_rules(file_path: Path, schema_path: Path | None = None) -> list[str]:
    """Validate quality rules file."""
    errors = []
    
    try:
        with open(file_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        return [f"YAML syntax error: {e}"]
    except Exception as e:
        return [f"Error reading file: {e}"]
    
    if not data:
        return ["File is empty"]
    
    # Check version
    version = data.get("version")
    if not version:
        errors.append("Missing 'version' field")
    
    # Check rules array
    rules = data.get("rules", [])
    if not rules:
        errors.append("No rules defined")
        return errors
    
    rule_names = set()
    
    for i, rule in enumerate(rules):
        rule_prefix = f"Rule {i+1}"
        
        # Required fields
        name = rule.get("name")
        if not name:
            errors.append(f"{rule_prefix}: missing 'name'")
        else:
            if name in rule_names:
                errors.append(f"{rule_prefix}: duplicate rule name '{name}'")
            rule_names.add(name)
            rule_prefix = f"Rule '{name}'"
        
        rule_type = rule.get("type")
        if not rule_type:
            errors.append(f"{rule_prefix}: missing 'type'")
        elif rule_type not in VALID_RULE_TYPES:
            errors.append(f"{rule_prefix}: invalid type '{rule_type}'. Valid types: {VALID_RULE_TYPES}")
        
        severity = rule.get("severity")
        if not severity:
            errors.append(f"{rule_prefix}: missing 'severity'")
        elif severity not in VALID_SEVERITIES:
            errors.append(f"{rule_prefix}: invalid severity '{severity}'. Valid: {VALID_SEVERITIES}")
        
        # Type-specific validation
        if rule_type == "not_null" and not rule.get("field"):
            errors.append(f"{rule_prefix}: 'not_null' requires 'field'")
        
        if rule_type == "range":
            if not rule.get("field"):
                errors.append(f"{rule_prefix}: 'range' requires 'field'")
            if rule.get("min") is None and rule.get("max") is None:
                errors.append(f"{rule_prefix}: 'range' requires 'min' and/or 'max'")
        
        if rule_type == "regex":
            if not rule.get("field"):
                errors.append(f"{rule_prefix}: 'regex' requires 'field'")
            if not rule.get("pattern"):
                errors.append(f"{rule_prefix}: 'regex' requires 'pattern'")
            else:
                # Validate regex pattern
                import re
                try:
                    re.compile(rule["pattern"])
                except re.error as e:
                    errors.append(f"{rule_prefix}: invalid regex pattern: {e}")
        
        if rule_type == "enum":
            if not rule.get("field"):
                errors.append(f"{rule_prefix}: 'enum' requires 'field'")
            if not rule.get("values"):
                errors.append(f"{rule_prefix}: 'enum' requires 'values' list")
            if schema_path and schema_path.exists():
                enum_errors = _validate_enum_against_schema(rule, schema_path)
                for err in enum_errors:
                    errors.append(f"{rule_prefix}: {err}")
        
        if rule_type == "freshness":
            if not rule.get("field"):
                errors.append(f"{rule_prefix}: 'freshness' requires 'field'")
            if rule.get("max_age_minutes") is None:
                errors.append(f"{rule_prefix}: 'freshness' requires 'max_age_minutes'")
        
        if rule_type == "custom":
            if not rule.get("expression"):
                errors.append(f"{rule_prefix}: 'custom' requires 'expression'")

        if rule_type == "sql":
            if not rule.get("query"):
                errors.append(f"{rule_prefix}: 'sql' requires 'query'")

        if rule_type == "reference":
            if not rule.get("table"):
                errors.append(f"{rule_prefix}: 'reference' requires 'table'")
            if not rule.get("column"):
                errors.append(f"{rule_prefix}: 'reference' requires 'column'")

        if rule_type == "unique":
            if not rule.get("field"):
                errors.append(f"{rule_prefix}: 'unique' requires 'field'")

        if rule_type == "format":
            if not rule.get("format_type"):
                errors.append(f"{rule_prefix}: 'format' requires 'format_type'")

        if rule_type == "completeness":
            if not rule.get("field"):
                errors.append(f"{rule_prefix}: 'completeness' requires 'field'")
            min_rate = rule.get("min_rate")
            if min_rate is None:
                errors.append(f"{rule_prefix}: 'completeness' requires 'min_rate'")
            elif not isinstance(min_rate, (int, float)) or min_rate < 0.0 or min_rate > 1.0:
                errors.append(f"{rule_prefix}: 'min_rate' must be between 0.0 and 1.0")

        if rule_type == "currency":
            if not rule.get("field"):
                errors.append(f"{rule_prefix}: 'currency' requires 'field'")
            max_staleness = rule.get("max_staleness_minutes")
            if max_staleness is None:
                errors.append(f"{rule_prefix}: 'currency' requires 'max_staleness_minutes'")
            elif not isinstance(max_staleness, (int, float)) or max_staleness <= 0:
                errors.append(f"{rule_prefix}: 'max_staleness_minutes' must be a positive number")

        if rule_type == "reasonableness":
            if not rule.get("field"):
                errors.append(f"{rule_prefix}: 'reasonableness' requires 'field'")
            if rule.get("min") is None and rule.get("max") is None:
                errors.append(f"{rule_prefix}: 'reasonableness' requires 'min' and/or 'max'")

    return errors


def find_all_quality_rules(base_path: Path = Path(".")) -> list[tuple[Path, Path | None]]:
    """Find all quality_rules files referenced in manifests."""
    domains_path = base_path / "examples"
    if not domains_path.exists():
        return []
    files = []
    for manifest_path in domains_path.rglob("manifest.yaml"):
        try:
            with open(manifest_path, encoding="utf-8") as f:
                manifest = yaml.safe_load(f)
        except Exception:
            continue
        if not manifest:
            continue
        quality_rules = manifest.get("quality_rules", {})
        qr_file = quality_rules.get("file")
        if qr_file:
            qr_path = manifest_path.parent / qr_file
            schema_section = manifest.get("schema", {})
            schema_file = schema_section.get("file")
            schema_path = manifest_path.parent / schema_file if schema_file else None
            if schema_path and not schema_path.exists():
                schema_path = None
            if qr_path.exists():
                files.append((qr_path, schema_path))
    return files


def main():
    parser = argparse.ArgumentParser(description="Validate quality rules files")
    parser.add_argument(
        "path",
        nargs="?",
        help="Path to quality_rules.yml file",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Validate all quality rules files",
    )
    parser.add_argument(
        "--base-path",
        default=".",
        help="Base path for manifests directory",
    )
    
    args = parser.parse_args()
    base_path = Path(args.base_path)
    
    if args.all:
        file_pairs = find_all_quality_rules(base_path)
        if not file_pairs:
            print("No quality_rules.yml files found")
            sys.exit(1)
    elif args.path:
        file_pairs = [(Path(args.path), None)]
    else:
        parser.print_help()
        sys.exit(1)

    total_errors = 0

    for file_path, schema_path in file_pairs:
        print(f"\n📋 Validating: {file_path}")
        errors = validate_quality_rules(file_path, schema_path=schema_path)
        
        if errors:
            print(f"❌ {len(errors)} error(s):")
            for error in errors:
                print(f"   - {error}")
            total_errors += len(errors)
        else:
            print("✅ Valid")
    
    print(f"\n{'=' * 40}")
    print(f"Validated {len(file_pairs)} file(s)")
    
    if total_errors > 0:
        print(f"❌ Total errors: {total_errors}")
        sys.exit(1)
    else:
        print("✅ All quality rules are valid")
        sys.exit(0)


if __name__ == "__main__":
    main()
