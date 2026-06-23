"""Tests for validate_quality_rules.py."""

import json
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

from dpm.validators.validate_quality_rules import validate_quality_rules

# ═══════════════════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════════════════


def _write_rules(tmp_path, rules, version="1.0.0"):
    """Write a quality-rules YAML file and return its path."""
    data = {"version": version, "rules": rules}
    path = tmp_path / "quality_rules.yml"
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f)
    return path


# ═══════════════════════════════════════════════════════════════════════════
# VALID RULES FOR EACH TYPE
# ═══════════════════════════════════════════════════════════════════════════


class TestValidRuleTypes:
    """Each rule type, when well-formed, validates without errors."""

    @pytest.mark.parametrize(
        "rule",
        [
            {"name": "check_id", "type": "not_null", "severity": "error", "field": "id"},
            {"name": "unique_email", "type": "unique", "severity": "error", "field": "email"},
            {"name": "age_range", "type": "range", "severity": "warning", "field": "age", "min": 0, "max": 150},
            {"name": "positive_count", "type": "range", "severity": "error", "field": "count", "min": 0},
            {"name": "max_price", "type": "range", "severity": "warning", "field": "price", "max": 1000000},
            {"name": "email_re", "type": "regex", "severity": "error", "field": "email", "pattern": r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"},
            {"name": "status_enum", "type": "enum", "severity": "error", "field": "status", "values": ["active", "inactive", "pending"]},
            {"name": "data_freshness", "type": "freshness", "severity": "warning", "field": "updated_at", "max_age_minutes": 60},
            {"name": "rt_freshness", "type": "freshness", "severity": "error", "field": "timestamp", "max_age_minutes": 0},
            {"name": "custom_logic", "type": "custom", "severity": "error", "expression": "col('amount') > col('limit')"},
            {"name": "sql_check", "type": "sql", "severity": "error", "query": "SELECT COUNT(*) FROM users WHERE id IS NULL"},
            {"name": "ref_check", "type": "reference", "severity": "error", "table": "users", "column": "id"},
            {"name": "email_fmt", "type": "format", "severity": "warning", "format_type": "email"},
        ],
        ids=[
            "not_null", "unique", "range_min_max", "range_min", "range_max",
            "regex", "enum", "freshness", "freshness_zero", "custom", "sql",
            "reference", "format",
        ],
    )
    def test_valid_rule(self, tmp_path, rule):
        path = _write_rules(tmp_path, [rule])
        assert validate_quality_rules(path) == []


# ═══════════════════════════════════════════════════════════════════════════
# DUPLICATE RULE NAMES
# ═══════════════════════════════════════════════════════════════════════════


class TestDuplicateRuleNames:
    """Tests for detecting duplicate rule names."""

    def test_duplicate_rule_names_error(self, tmp_path):
        """Two rules with the same name is an error."""
        rules = [
            {
                "name": "check_id",
                "type": "not_null",
                "severity": "error",
                "field": "id",
            },
            {
                "name": "check_id",
                "type": "unique",
                "severity": "error",
                "field": "id",
            },
        ]
        path = _write_rules(tmp_path, rules)
        errors = validate_quality_rules(path)
        assert len(errors) > 0
        assert any("duplicate" in e.lower() for e in errors)

    def test_three_duplicate_names(self, tmp_path):
        """Three rules sharing a name."""
        rules = [
            {
                "name": "same_name",
                "type": "not_null",
                "severity": "error",
                "field": "id",
            },
            {
                "name": "same_name",
                "type": "unique",
                "severity": "error",
                "field": "email",
            },
            {
                "name": "same_name",
                "type": "range",
                "severity": "warning",
                "field": "age",
                "min": 0,
            },
        ]
        path = _write_rules(tmp_path, rules)
        errors = validate_quality_rules(path)
        assert len(errors) >= 2
        assert sum(1 for e in errors if "duplicate" in e.lower()) >= 2


# ═══════════════════════════════════════════════════════════════════════════
# INVALID REGEX
# ═══════════════════════════════════════════════════════════════════════════


class TestInvalidRegex:
    """Tests for detecting invalid regular expressions."""

    def test_invalid_regex_pattern(self, tmp_path):
        """An invalid regular expression in pattern."""
        rules = [
            {
                "name": "bad_regex",
                "type": "regex",
                "severity": "error",
                "field": "email",
                "pattern": "[invalid",
            }
        ]
        path = _write_rules(tmp_path, rules)
        errors = validate_quality_rules(path)
        assert len(errors) > 0
        assert any("invalid regex" in e.lower() for e in errors)

    def test_multiple_invalid_regexes(self, tmp_path):
        """Several invalid regular expressions."""
        rules = [
            {
                "name": "bad_regex1",
                "type": "regex",
                "severity": "error",
                "field": "email",
                "pattern": "[invalid",
            },
            {
                "name": "bad_regex2",
                "type": "regex",
                "severity": "warning",
                "field": "phone",
                "pattern": "(?P<invalid",
            },
        ]
        path = _write_rules(tmp_path, rules)
        errors = validate_quality_rules(path)
        assert len(errors) >= 2


# ═══════════════════════════════════════════════════════════════════════════
# MISSING REQUIRED FIELDS PER TYPE
# ═══════════════════════════════════════════════════════════════════════════


class TestMissingRequiredFields:
    """A rule missing a type-specific required field reports that field."""

    @pytest.mark.parametrize(
        "rule, expected",
        [
            ({"name": "check_null", "type": "not_null", "severity": "error"}, "field"),
            ({"name": "age_range", "type": "range", "severity": "warning", "min": 0, "max": 150}, "field"),
            ({"name": "age_range", "type": "range", "severity": "warning", "field": "age"}, "min"),
            ({"name": "email_re", "type": "regex", "severity": "error", "pattern": r"^[a-z]+@[a-z]+\.[a-z]+$"}, "field"),
            ({"name": "email_re", "type": "regex", "severity": "error", "field": "email"}, "pattern"),
            ({"name": "status", "type": "enum", "severity": "error", "values": ["active", "inactive"]}, "field"),
            ({"name": "status", "type": "enum", "severity": "error", "field": "status"}, "values"),
            ({"name": "data_freshness", "type": "freshness", "severity": "warning", "max_age_minutes": 60}, "field"),
            ({"name": "data_freshness", "type": "freshness", "severity": "warning", "field": "updated_at"}, "max_age_minutes"),
            ({"name": "custom_logic", "type": "custom", "severity": "error"}, "expression"),
            ({"name": "sql_check", "type": "sql", "severity": "error"}, "query"),
            ({"name": "ref_check", "type": "reference", "severity": "error", "column": "id"}, "table"),
            ({"name": "ref_check", "type": "reference", "severity": "error", "table": "users"}, "column"),
            ({"name": "unique_check", "type": "unique", "severity": "error"}, "field"),
            ({"name": "format_check", "type": "format", "severity": "warning"}, "format_type"),
        ],
        ids=[
            "not_null_field", "range_field", "range_min_max", "regex_field",
            "regex_pattern", "enum_field", "enum_values", "freshness_field",
            "freshness_max_age", "custom_expression", "sql_query",
            "reference_table", "reference_column", "unique_field", "format_type",
        ],
    )
    def test_missing_required_field(self, tmp_path, rule, expected):
        path = _write_rules(tmp_path, [rule])
        errors = validate_quality_rules(path)
        assert any(expected in e.lower() for e in errors)


# ═══════════════════════════════════════════════════════════════════════════
# YAML SYNTAX AND FILE STRUCTURE
# ═══════════════════════════════════════════════════════════════════════════


class TestYamlSyntax:
    """Tests for YAML syntax and file structure."""

    def test_invalid_yaml_syntax(self, tmp_path):
        """Invalid YAML syntax is an error."""
        file_path = tmp_path / "broken.yml"
        file_path.write_text("key:\n  - item1\n item2\n", encoding="utf-8")
        errors = validate_quality_rules(file_path)
        assert len(errors) > 0
        assert "YAML syntax error" in errors[0]

    def test_empty_file(self, tmp_path):
        """An empty file is an error."""
        file_path = tmp_path / "empty.yml"
        file_path.write_text("", encoding="utf-8")
        errors = validate_quality_rules(file_path)
        assert "File is empty" in errors

    def test_yaml_only_comments(self, tmp_path):
        """A file with only comments is an error."""
        file_path = tmp_path / "comments.yml"
        file_path.write_text("# Just a comment\n# Another comment\n", encoding="utf-8")
        errors = validate_quality_rules(file_path)
        assert "File is empty" in errors


# ═══════════════════════════════════════════════════════════════════════════
# VERSION VALIDATION
# ═══════════════════════════════════════════════════════════════════════════


class TestVersionValidation:
    """Tests for version validation."""

    def test_missing_version(self, tmp_path):
        """A file without a version field is an error."""
        path = tmp_path / "no_version.yml"
        data = {
            "rules": [
                {
                    "name": "check_id",
                    "type": "not_null",
                    "severity": "error",
                    "field": "id",
                }
            ]
        }
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(data, f)
        errors = validate_quality_rules(path)
        assert any("version" in e.lower() for e in errors)

    def test_empty_version_string(self, tmp_path):
        """An empty version value is an error."""
        path = tmp_path / "empty_version.yml"
        data = {
            "version": "",
            "rules": [
                {
                    "name": "check_id",
                    "type": "not_null",
                    "severity": "error",
                    "field": "id",
                }
            ],
        }
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(data, f)
        errors = validate_quality_rules(path)
        assert any("version" in e.lower() for e in errors)


# ═══════════════════════════════════════════════════════════════════════════
# RULES ARRAY VALIDATION
# ═══════════════════════════════════════════════════════════════════════════


class TestRulesArray:
    """Tests for rules-array validation."""

    def test_no_rules_defined(self, tmp_path):
        """A file with a version but no rules is an error."""
        path = tmp_path / "no_rules.yml"
        data = {"version": "1.0.0", "rules": []}
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(data, f)
        errors = validate_quality_rules(path)
        assert any("No rules defined" in e or "rules" in e.lower() for e in errors)

    def test_rules_missing_key(self, tmp_path):
        """A file without a rules key is an error."""
        path = tmp_path / "no_rules_key.yml"
        data = {"version": "1.0.0"}
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(data, f)
        errors = validate_quality_rules(path)
        assert any("No rules defined" in e or "rules" in e.lower() for e in errors)


# ═══════════════════════════════════════════════════════════════════════════
# RULE TYPE VALIDATION
# ═══════════════════════════════════════════════════════════════════════════


class TestRuleTypeValidation:
    """Tests for rule-type validation."""

    def test_invalid_rule_type(self, tmp_path):
        """An invalid rule type is an error."""
        rules = [
            {
                "name": "invalid_type",
                "type": "nonexistent",
                "severity": "error",
            }
        ]
        path = _write_rules(tmp_path, rules)
        errors = validate_quality_rules(path)
        assert len(errors) > 0
        assert any("invalid type" in e.lower() for e in errors)

    def test_missing_rule_type(self, tmp_path):
        """A rule without a type is an error."""
        rules = [
            {
                "name": "no_type",
                "severity": "error",
                "field": "id",
            }
        ]
        path = _write_rules(tmp_path, rules)
        errors = validate_quality_rules(path)
        assert any("type" in e.lower() for e in errors)


# ═══════════════════════════════════════════════════════════════════════════
# SEVERITY VALIDATION
# ═══════════════════════════════════════════════════════════════════════════


class TestSeverityValidation:
    """Tests for severity validation."""

    def test_invalid_severity(self, tmp_path):
        """An invalid severity is an error."""
        rules = [
            {
                "name": "bad_severity",
                "type": "not_null",
                "severity": "fatal",
                "field": "id",
            }
        ]
        path = _write_rules(tmp_path, rules)
        errors = validate_quality_rules(path)
        assert len(errors) > 0
        assert any("severity" in e.lower() for e in errors)

    def test_missing_severity(self, tmp_path):
        """A rule without a severity is an error."""
        rules = [
            {
                "name": "no_severity",
                "type": "not_null",
                "field": "id",
            }
        ]
        path = _write_rules(tmp_path, rules)
        errors = validate_quality_rules(path)
        assert any("severity" in e.lower() for e in errors)

    def test_all_valid_severities(self, tmp_path):
        """All valid severities pass validation."""
        for severity in ["error", "warning", "info"]:
            rules = [
                {
                    "name": f"check_{severity}",
                    "type": "not_null",
                    "severity": severity,
                    "field": "id",
                }
            ]
            path = _write_rules(tmp_path, rules, version="1.0.0")
            errors = validate_quality_rules(path)
            assert errors == []


# ═══════════════════════════════════════════════════════════════════════════
# RULE NAME VALIDATION
# ═══════════════════════════════════════════════════════════════════════════


class TestRuleNameValidation:
    """Tests for rule-name validation."""

    def test_missing_rule_name(self, tmp_path):
        """A rule without a name is an error."""
        rules = [
            {
                "type": "not_null",
                "severity": "error",
                "field": "id",
            }
        ]
        path = _write_rules(tmp_path, rules)
        errors = validate_quality_rules(path)
        assert any("name" in e.lower() for e in errors)

    def test_empty_rule_name(self, tmp_path):
        """A rule with an empty name is an error."""
        rules = [
            {
                "name": "",
                "type": "not_null",
                "severity": "error",
                "field": "id",
            }
        ]
        path = _write_rules(tmp_path, rules)
        errors = validate_quality_rules(path)
        assert any("name" in e.lower() for e in errors)


# ═══════════════════════════════════════════════════════════════════════════
# INTEGRATION: MULTIPLE RULES WITH MIXED VALIDITY
# ═══════════════════════════════════════════════════════════════════════════


class TestMultipleRulesMixed:
    """Integration tests with multiple rules of varying validity."""

    def test_multiple_valid_rules(self, tmp_path):
        """Several valid rules of different types."""
        rules = [
            {
                "name": "check_id",
                "type": "not_null",
                "severity": "error",
                "field": "id",
            },
            {
                "name": "unique_email",
                "type": "unique",
                "severity": "error",
                "field": "email",
            },
            {
                "name": "age_range",
                "type": "range",
                "severity": "warning",
                "field": "age",
                "min": 0,
                "max": 150,
            },
        ]
        path = _write_rules(tmp_path, rules)
        errors = validate_quality_rules(path)
        assert errors == []

    def test_multiple_rules_with_errors(self, tmp_path):
        """Several rules, some with errors."""
        rules = [
            {
                "name": "check_id",
                "type": "not_null",
                "severity": "error",
                "field": "id",
            },
            {
                "name": "bad_range",
                "type": "range",
                "severity": "warning",
                "field": "age",
            },
            {
                "name": "bad_regex",
                "type": "regex",
                "severity": "error",
                "field": "email",
                "pattern": "[invalid",
            },
        ]
        path = _write_rules(tmp_path, rules)
        errors = validate_quality_rules(path)
        assert len(errors) > 0

    def test_all_rule_types_together(self, tmp_path):
        """All supported types in a single file."""
        rules = [
            {
                "name": "check_id",
                "type": "not_null",
                "severity": "error",
                "field": "id",
            },
            {
                "name": "unique_email",
                "type": "unique",
                "severity": "error",
                "field": "email",
            },
            {
                "name": "age_range",
                "type": "range",
                "severity": "warning",
                "field": "age",
                "min": 0,
                "max": 150,
            },
            {
                "name": "email_format",
                "type": "regex",
                "severity": "error",
                "field": "email",
                "pattern": r"^[a-z]+@[a-z]+\.[a-z]+$",
            },
            {
                "name": "status_enum",
                "type": "enum",
                "severity": "error",
                "field": "status",
                "values": ["active", "inactive"],
            },
            {
                "name": "data_freshness",
                "type": "freshness",
                "severity": "warning",
                "field": "updated_at",
                "max_age_minutes": 60,
            },
            {
                "name": "custom_logic",
                "type": "custom",
                "severity": "error",
                "expression": "col('amount') > 0",
            },
            {
                "name": "sql_check",
                "type": "sql",
                "severity": "error",
                "query": "SELECT COUNT(*) FROM users",
            },
            {
                "name": "ref_check",
                "type": "reference",
                "severity": "error",
                "table": "users",
                "column": "id",
            },
            {
                "name": "phone_format",
                "type": "format",
                "severity": "info",
                "format_type": "phone",
            },
        ]
        path = _write_rules(tmp_path, rules)
        errors = validate_quality_rules(path)
        assert errors == []


# ═══════════════════════════════════════════════════════════════════════════
# EDGE CASES
# ═══════════════════════════════════════════════════════════════════════════


class TestEdgeCases:
    """Edge cases."""

    def test_single_rule_valid(self, tmp_path):
        """A single valid rule."""
        rules = [
            {
                "name": "single_rule",
                "type": "not_null",
                "severity": "error",
                "field": "id",
            }
        ]
        path = _write_rules(tmp_path, rules)
        errors = validate_quality_rules(path)
        assert errors == []

    def test_freshness_with_false_max_age(self, tmp_path):
        """Freshness with max_age_minutes: false passes (False is not None)."""
        rules = [
            {
                "name": "data_freshness",
                "type": "freshness",
                "severity": "warning",
                "field": "updated_at",
                "max_age_minutes": False,
            }
        ]
        path = _write_rules(tmp_path, rules)
        errors = validate_quality_rules(path)
        # False is not None, so there is no error (even though it is odd)
        assert errors == []

    def test_enum_empty_values_list(self, tmp_path):
        """Enum with an empty values list."""
        rules = [
            {
                "name": "status_enum",
                "type": "enum",
                "severity": "error",
                "field": "status",
                "values": [],
            }
        ]
        path = _write_rules(tmp_path, rules)
        errors = validate_quality_rules(path)
        assert any("values" in e.lower() for e in errors)

    def test_many_rules_with_one_duplicate(self, tmp_path):
        """Many rules with one duplicate."""
        rules = [
            {
                "name": "rule1",
                "type": "not_null",
                "severity": "error",
                "field": "id",
            },
            {
                "name": "rule2",
                "type": "unique",
                "severity": "error",
                "field": "email",
            },
            {
                "name": "rule3",
                "type": "not_null",
                "severity": "error",
                "field": "name",
            },
            {
                "name": "rule2",
                "type": "range",
                "severity": "warning",
                "field": "age",
                "min": 0,
            },
        ]
        path = _write_rules(tmp_path, rules)
        errors = validate_quality_rules(path)
        assert any("duplicate" in e.lower() for e in errors)


# ═══════════════════════════════════════════════════════════════════════════
# ENUM ↔ SCHEMA CROSS-VALIDATION
# ═══════════════════════════════════════════════════════════════════════════


def _write_enum_schema(tmp_path, symbols):
    """Write a schema.avsc with a single enum field named 'status'."""
    schema = {
        "type": "record",
        "name": "R",
        "fields": [
            {"name": "status", "type": {"type": "enum", "name": "S", "symbols": symbols}}
        ],
    }
    path = tmp_path / "schema.avsc"
    path.write_text(json.dumps(schema))
    return path


class TestEnumSchemaCrossValidation:
    """An enum rule is cross-checked against the Avro schema symbols."""

    def test_enum_matches_schema(self, tmp_path):
        schema = _write_enum_schema(tmp_path, ["a", "b"])
        rules = [
            {"name": "r", "type": "enum", "severity": "error", "field": "status", "values": ["a", "b"]}
        ]
        path = _write_rules(tmp_path, rules)
        assert validate_quality_rules(path, schema) == []

    def test_enum_mismatch_is_reported(self, tmp_path):
        schema = _write_enum_schema(tmp_path, ["a", "b", "c"])
        rules = [
            {"name": "r", "type": "enum", "severity": "error", "field": "status", "values": ["a", "b"]}
        ]
        path = _write_rules(tmp_path, rules)
        errors = validate_quality_rules(path, schema)
        assert any("schema" in e.lower() for e in errors)
