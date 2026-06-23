"""Tests for detect_breaking_changes.py."""

import json
import sys
from pathlib import Path

import pytest

# Add the parent directory to the path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from dpm.validators.detect_breaking_changes import (
    Change,
    ChangeType,
    _get_base_type,
    detect_breaking_changes,
    detect_field_changes,
    get_manifest_dir_from_file,
    is_avro_nullable,
    is_compatible_type_change,
    load_avro_fields,
)

# ═══════════════════════════════════════════════════════════════════════════
# is_avro_nullable
# ═══════════════════════════════════════════════════════════════════════════


class TestIsAvroNullable:
    """Tests for nullable field detection."""

    def test_nullable_union_with_default(self):
        field = {"name": "f", "type": ["null", "string"], "default": None}
        assert is_avro_nullable(field) is True

    def test_non_nullable_simple_type(self):
        field = {"name": "f", "type": "string"}
        assert is_avro_nullable(field) is False

    def test_union_without_null(self):
        field = {"name": "f", "type": ["string", "int"]}
        assert is_avro_nullable(field) is False

    def test_manifest_style_required_false(self):
        field = {"name": "f", "type": "string", "required": False}
        assert is_avro_nullable(field) is True

    def test_manifest_style_required_true(self):
        field = {"name": "f", "type": "string", "required": True}
        assert is_avro_nullable(field) is False


# ═══════════════════════════════════════════════════════════════════════════
# load_avro_fields
# ═══════════════════════════════════════════════════════════════════════════


class TestLoadAvroFields:
    """Tests for loading fields from an Avro schema."""

    def test_valid_avro(self):
        content = '{"type":"record","name":"T","fields":[{"name":"id","type":"string"}]}'
        fields = load_avro_fields(content)
        assert len(fields) == 1
        assert fields[0]["name"] == "id"

    def test_invalid_json(self):
        fields = load_avro_fields("{invalid}")
        assert fields == []

    def test_missing_fields_key(self):
        fields = load_avro_fields('{"type":"record","name":"T"}')
        assert fields == []


# ═══════════════════════════════════════════════════════════════════════════
# get_manifest_dir_from_file
# ═══════════════════════════════════════════════════════════════════════════


class TestGetManifestDirFromFile:
    """Tests for resolving the manifest directory from a file path."""

    def test_valid_path(self):
        result = get_manifest_dir_from_file("examples/aviation/flights/schema.avsc")
        assert result == "examples/aviation/flights"

    def test_manifest_yaml(self):
        result = get_manifest_dir_from_file("examples/aviation/flights/manifest.yaml")
        assert result == "examples/aviation/flights"

    def test_short_path(self):
        result = get_manifest_dir_from_file("examples/aviation")
        assert result is None

    def test_non_domains_path(self):
        result = get_manifest_dir_from_file("ci/validate_manifest.py")
        assert result is None


# ═══════════════════════════════════════════════════════════════════════════
# detect_field_changes
# ═══════════════════════════════════════════════════════════════════════════


class TestDetectFieldChanges:
    """Tests for field change detection."""

    def test_field_removed_is_breaking(self):
        old = [{"name": "a", "type": "string"}, {"name": "b", "type": "int"}]
        new = [{"name": "a", "type": "string"}]
        changes = detect_field_changes(old, new, "test")
        breaking = [c for c in changes if c.change_type == ChangeType.BREAKING]
        assert len(breaking) == 1
        assert "b" in breaking[0].description
        assert "removed" in breaking[0].description.lower()

    def test_nullable_field_added_is_non_breaking(self):
        old = [{"name": "a", "type": "string"}]
        new = [
            {"name": "a", "type": "string"},
            {"name": "b", "type": ["null", "int"], "default": None},
        ]
        changes = detect_field_changes(old, new, "test")
        non_breaking = [c for c in changes if c.change_type == ChangeType.NON_BREAKING]
        assert len(non_breaking) == 1
        assert "b" in non_breaking[0].description

    def test_required_field_added_is_breaking(self):
        old = [{"name": "a", "type": "string"}]
        new = [{"name": "a", "type": "string"}, {"name": "b", "type": "int"}]
        changes = detect_field_changes(old, new, "test")
        breaking = [c for c in changes if c.change_type == ChangeType.BREAKING]
        assert len(breaking) == 1
        assert "b" in breaking[0].description

    def test_type_change_is_breaking(self):
        old = [{"name": "a", "type": "string"}]
        new = [{"name": "a", "type": "int"}]
        changes = detect_field_changes(old, new, "test")
        breaking = [c for c in changes if c.change_type == ChangeType.BREAKING]
        assert len(breaking) == 1
        assert "type changed" in breaking[0].description.lower()

    def test_no_changes_returns_empty(self):
        fields = [{"name": "a", "type": "string"}]
        changes = detect_field_changes(fields, fields, "test")
        assert changes == []

    def test_optional_to_required_is_breaking(self):
        old = [{"name": "a", "type": "string", "required": False}]
        new = [{"name": "a", "type": "string", "required": True}]
        changes = detect_field_changes(old, new, "test")
        breaking = [c for c in changes if c.change_type == ChangeType.BREAKING]
        assert len(breaking) >= 1

    def test_required_to_optional_is_non_breaking(self):
        old = [{"name": "a", "type": "string", "required": True}]
        new = [{"name": "a", "type": "string", "required": False}]
        changes = detect_field_changes(old, new, "test")
        non_breaking = [c for c in changes if c.change_type == ChangeType.NON_BREAKING]
        assert len(non_breaking) == 1

    def test_enum_value_removed_is_breaking(self):
        """Removing an enum value is breaking (via constraints)."""
        old = [{"name": "s", "type": "string", "constraints": {"enum": ["a", "b", "c"]}}]
        new = [{"name": "s", "type": "string", "constraints": {"enum": ["a", "b"]}}]
        changes = detect_field_changes(old, new, "test")
        breaking = [c for c in changes if c.change_type == ChangeType.BREAKING]
        assert len(breaking) == 1
        assert "enum" in breaking[0].description.lower()

    def test_enum_value_added_is_non_breaking(self):
        """Adding an enum value is non-breaking (via constraints)."""
        old = [{"name": "s", "type": "string", "constraints": {"enum": ["a", "b"]}}]
        new = [{"name": "s", "type": "string", "constraints": {"enum": ["a", "b", "c"]}}]
        changes = detect_field_changes(old, new, "test")
        non_breaking = [c for c in changes if c.change_type == ChangeType.NON_BREAKING]
        assert len(non_breaking) == 1

    def test_min_length_increase_is_breaking(self):
        old = [{"name": "f", "type": "string", "constraints": {"min_length": 5}}]
        new = [{"name": "f", "type": "string", "constraints": {"min_length": 10}}]
        changes = detect_field_changes(old, new, "test")
        breaking = [c for c in changes if c.change_type == ChangeType.BREAKING]
        assert len(breaking) == 1
        assert "min_length" in breaking[0].description

    def test_max_length_decrease_is_breaking(self):
        old = [{"name": "f", "type": "string", "constraints": {"max_length": 100}}]
        new = [{"name": "f", "type": "string", "constraints": {"max_length": 50}}]
        changes = detect_field_changes(old, new, "test")
        breaking = [c for c in changes if c.change_type == ChangeType.BREAKING]
        assert len(breaking) == 1
        assert "max_length" in breaking[0].description

    def test_pattern_change_is_breaking(self):
        old = [{"name": "f", "type": "string", "constraints": {"pattern": "^[a-z]+$"}}]
        new = [{"name": "f", "type": "string", "constraints": {"pattern": "^[a-z0-9]+$"}}]
        changes = detect_field_changes(old, new, "test")
        breaking = [c for c in changes if c.change_type == ChangeType.BREAKING]
        assert len(breaking) == 1
        assert "pattern" in breaking[0].description

    def test_min_value_increase_is_breaking(self):
        old = [{"name": "v", "type": "int", "constraints": {"min": 0}}]
        new = [{"name": "v", "type": "int", "constraints": {"min": 5}}]
        changes = detect_field_changes(old, new, "test")
        breaking = [c for c in changes if c.change_type == ChangeType.BREAKING]
        assert len(breaking) == 1

    def test_max_value_decrease_is_breaking(self):
        old = [{"name": "v", "type": "int", "constraints": {"max": 100}}]
        new = [{"name": "v", "type": "int", "constraints": {"max": 50}}]
        changes = detect_field_changes(old, new, "test")
        breaking = [c for c in changes if c.change_type == ChangeType.BREAKING]
        assert len(breaking) == 1


# ═══════════════════════════════════════════════════════════════════════════
# detect_breaking_changes (integration)
# ═══════════════════════════════════════════════════════════════════════════


class TestDetectBreakingChanges:
    """Integration tests for detect_breaking_changes."""

    def test_no_changes(self):
        manifest = {
            "metadata": {"name": "test"},
            "schema": {"fields": [{"name": "a", "type": "string"}]},
        }
        changes = detect_breaking_changes(manifest, manifest)
        assert changes == []

    def test_metadata_only_change_is_patch(self):
        old = {"metadata": {"name": "test", "desc": "old"}, "schema": {"fields": []}}
        new = {"metadata": {"name": "test", "desc": "new"}, "schema": {"fields": []}}
        changes = detect_breaking_changes(old, new)
        assert len(changes) == 1
        assert changes[0].change_type == ChangeType.PATCH


# ═══════════════════════════════════════════════════════════════════════════
# Change model
# ═══════════════════════════════════════════════════════════════════════════


class TestChangeModel:
    """Tests for the Change Pydantic model."""

    def test_creation(self):
        change = Change(
            manifest="test",
            field="f",
            change_type=ChangeType.BREAKING,
            description="test",
        )
        assert change.manifest == "test"
        assert change.change_type == "breaking"

    def test_serialization(self):
        change = Change(
            manifest="t",
            field=None,
            change_type=ChangeType.NON_BREAKING,
            description="d",
        )
        data = change.model_dump()
        assert data["change_type"] == "non_breaking"
        assert data["field"] is None


# ═══════════════════════════════════════════════════════════════════════════
# Avro schema comparison (end-to-end)
# ═══════════════════════════════════════════════════════════════════════════


class TestAvroSchemaComparison:
    """Tests comparing Avro schemas directly."""

    def test_field_removed_from_avro_schema(self, tmp_path):
        """Removing a field from an Avro schema is detected as breaking."""
        old_schema = {
            "type": "record",
            "name": "Flight",
            "fields": [
                {"name": "icao24", "type": "string"},
                {"name": "callsign", "type": "string"},
                {"name": "altitude", "type": "float"},
            ],
        }
        new_schema = {
            "type": "record",
            "name": "Flight",
            "fields": [
                {"name": "icao24", "type": "string"},
                {"name": "altitude", "type": "float"},
            ],
        }

        old_fields = old_schema["fields"]
        new_fields = new_schema["fields"]
        
        changes = detect_field_changes(old_fields, new_fields, "Flight")
        breaking = [c for c in changes if c.change_type == ChangeType.BREAKING]
        
        assert len(breaking) == 1
        assert breaking[0].field == "callsign"
        assert "removed" in breaking[0].description.lower()

    def test_multiple_fields_removed(self):
        """Removing multiple fields produces separate breaking changes."""
        old = [
            {"name": "a", "type": "string"},
            {"name": "b", "type": "int"},
            {"name": "c", "type": "float"},
        ]
        new = [{"name": "b", "type": "int"}]
        
        changes = detect_field_changes(old, new, "test")
        breaking = [c for c in changes if c.change_type == ChangeType.BREAKING]
        
        assert len(breaking) == 2
        removed_fields = {c.field for c in breaking}
        assert removed_fields == {"a", "c"}

    def test_field_removed_and_added(self):
        """Removing and adding fields at the same time."""
        old = [
            {"name": "old_field", "type": "string"},
            {"name": "kept", "type": "int"},
        ]
        new = [
            {"name": "kept", "type": "int"},
            {"name": "new_field", "type": ["null", "string"], "default": None},
        ]
        
        changes = detect_field_changes(old, new, "test")
        breaking = [c for c in changes if c.change_type == ChangeType.BREAKING]
        non_breaking = [c for c in changes if c.change_type == ChangeType.NON_BREAKING]
        
        assert len(breaking) == 1
        assert breaking[0].field == "old_field"
        assert len(non_breaking) == 1
        assert non_breaking[0].field == "new_field"

    def test_no_fields_removed_no_breaking(self):
        """When no fields are removed there are no breaking changes."""
        old = [{"name": "a", "type": "string"}]
        new = [
            {"name": "a", "type": "string"},
            {"name": "b", "type": ["null", "int"], "default": None},
        ]

        changes = detect_field_changes(old, new, "test")
        breaking = [c for c in changes if c.change_type == ChangeType.BREAKING]

        assert len(breaking) == 0


# ═══════════════════════════════════════════════════════════════════════════
# Nested Avro records (R5)
# ═══════════════════════════════════════════════════════════════════════════


class TestNestedAvroRecords:
    """Tests for recursive handling of nested Avro records."""

    def test_nested_record_fields_extracted(self):
        """load_avro_fields with a nested record in array items returns both top-level and prefixed nested fields."""
        schema = {
            "type": "record",
            "name": "Order",
            "fields": [
                {"name": "order_id", "type": "string"},
                {
                    "name": "items",
                    "type": {
                        "type": "array",
                        "items": {
                            "type": "record",
                            "name": "OrderItem",
                            "fields": [
                                {"name": "product_name", "type": "string"},
                                {"name": "quantity", "type": "int"},
                            ],
                        },
                    },
                },
            ],
        }
        content = json.dumps(schema)
        fields = load_avro_fields(content, recursive=True)

        # Top-level fields must be present
        field_names = [f["name"] for f in fields]
        assert "order_id" in field_names
        assert "items" in field_names

        # Prefixed nested fields must be present
        assert "items.product_name" in field_names
        assert "items.quantity" in field_names

    def test_breaking_change_in_nested_field(self):
        """Removing a field from a nested record is detected as breaking via detect_field_changes."""
        # Old fields: top-level + nested
        old_fields = [
            {"name": "order_id", "type": "string"},
            {"name": "items", "type": "array"},
            {"name": "items.product_name", "type": "string"},
            {"name": "items.quantity", "type": "int"},
        ]
        # New fields: items.quantity removed
        new_fields = [
            {"name": "order_id", "type": "string"},
            {"name": "items", "type": "array"},
            {"name": "items.product_name", "type": "string"},
        ]

        changes = detect_field_changes(old_fields, new_fields, "Order")
        breaking = [c for c in changes if c.change_type == ChangeType.BREAKING]

        assert len(breaking) == 1
        assert "items.quantity" in breaking[0].description or breaking[0].field == "items.quantity"
        assert "removed" in breaking[0].description.lower()

    def test_adding_field_to_nested_record_non_breaking(self):
        """Adding a nullable field to a nested record is non-breaking."""
        # Old fields
        old_fields = [
            {"name": "order_id", "type": "string"},
            {"name": "items", "type": "array"},
            {"name": "items.product_name", "type": "string"},
        ]
        # New fields: items.discount added (nullable)
        new_fields = [
            {"name": "order_id", "type": "string"},
            {"name": "items", "type": "array"},
            {"name": "items.product_name", "type": "string"},
            {
                "name": "items.discount",
                "type": ["null", "float"],
                "default": None,
            },
        ]

        changes = detect_field_changes(old_fields, new_fields, "Order")
        non_breaking = [c for c in changes if c.change_type == ChangeType.NON_BREAKING]

        assert len(non_breaking) == 1
        assert "items.discount" in non_breaking[0].description

    def test_removing_field_from_nested_record_breaking(self):
        """Removing a required field from a nested record is breaking."""
        # Old fields
        old_fields = [
            {"name": "order_id", "type": "string"},
            {"name": "items", "type": "array"},
            {"name": "items.product_name", "type": "string"},
            {"name": "items.quantity", "type": "int"},
        ]
        # New fields: items.quantity removed (required)
        new_fields = [
            {"name": "order_id", "type": "string"},
            {"name": "items", "type": "array"},
            {"name": "items.product_name", "type": "string"},
        ]

        changes = detect_field_changes(old_fields, new_fields, "Order")
        breaking = [c for c in changes if c.change_type == ChangeType.BREAKING]

        assert len(breaking) == 1
        assert "items.quantity" in breaking[0].description or breaking[0].field == "items.quantity"

    def test_union_with_nested_record(self):
        """A union type ["null", {"type": "record", ...}] is also traversed recursively."""
        schema = {
            "type": "record",
            "name": "Event",
            "fields": [
                {"name": "event_id", "type": "string"},
                {
                    "name": "metadata",
                    "type": [
                        "null",
                        {
                            "type": "record",
                            "name": "EventMetadata",
                            "fields": [
                                {"name": "timestamp", "type": "long"},
                                {"name": "user_id", "type": ["null", "string"]},
                            ],
                        },
                    ],
                },
            ],
        }
        content = json.dumps(schema)
        fields = load_avro_fields(content, recursive=True)

        field_names = [f["name"] for f in fields]
        assert "event_id" in field_names
        assert "metadata" in field_names
        # A union with a nested record must be traversed recursively
        assert "metadata.timestamp" in field_names
        assert "metadata.user_id" in field_names

    def test_deeply_nested_records(self):
        """A record within a record within a record is traversed at 3+ levels."""
        schema = {
            "type": "record",
            "name": "Company",
            "fields": [
                {"name": "company_id", "type": "string"},
                {
                    "name": "departments",
                    "type": {
                        "type": "array",
                        "items": {
                            "type": "record",
                            "name": "Department",
                            "fields": [
                                {"name": "dept_name", "type": "string"},
                                {
                                    "name": "teams",
                                    "type": {
                                        "type": "array",
                                        "items": {
                                            "type": "record",
                                            "name": "Team",
                                            "fields": [
                                                {"name": "team_name", "type": "string"},
                                                {
                                                    "name": "members",
                                                    "type": {
                                                        "type": "array",
                                                        "items": {
                                                            "type": "record",
                                                            "name": "TeamMember",
                                                            "fields": [
                                                                {
                                                                    "name": "member_name",
                                                                    "type": "string",
                                                                },
                                                                {
                                                                    "name": "role",
                                                                    "type": "string",
                                                                },
                                                            ],
                                                        },
                                                    },
                                                },
                                            ],
                                        },
                                    },
                                },
                            ],
                        },
                    },
                },
            ],
        }
        content = json.dumps(schema)
        fields = load_avro_fields(content, recursive=True)

        field_names = [f["name"] for f in fields]
        # Top-level
        assert "company_id" in field_names
        assert "departments" in field_names
        # 2nd level
        assert "departments.dept_name" in field_names
        assert "departments.teams" in field_names
        # 3rd level
        assert "departments.teams.team_name" in field_names
        assert "departments.teams.members" in field_names
        # 4th level
        assert "departments.teams.members.member_name" in field_names
        assert "departments.teams.members.role" in field_names

# ═══════════════════════════════════════════════════════════════════════════
# Avro type promotions (Q2)
# ═══════════════════════════════════════════════════════════════════════════


class TestAvroTypePromotions:
    """Avro type promotion: widening is non-breaking, narrowing is breaking."""

    @pytest.mark.parametrize(
        "old_type, new_type, expected",
        [
            ("int", "long", ChangeType.NON_BREAKING),
            ("float", "double", ChangeType.NON_BREAKING),
            ("string", "int", ChangeType.BREAKING),
            ("long", "int", ChangeType.BREAKING),
            ("int", "float", ChangeType.NON_BREAKING),
            ("int", "double", ChangeType.NON_BREAKING),
            ("long", "double", ChangeType.NON_BREAKING),
            ("string", "bytes", ChangeType.NON_BREAKING),
            ("bytes", "string", ChangeType.NON_BREAKING),
            ("double", "float", ChangeType.BREAKING),
        ],
        ids=[
            "int_to_long", "float_to_double", "string_to_int", "long_to_int",
            "int_to_float", "int_to_double", "long_to_double", "string_to_bytes",
            "bytes_to_string", "double_to_float",
        ],
    )
    def test_type_change(self, old_type, new_type, expected):
        old = [{"name": "f", "type": old_type}]
        new = [{"name": "f", "type": new_type}]
        changes = detect_field_changes(old, new, "test")
        assert len(changes) == 1
        assert changes[0].change_type == expected


class TestGetBaseType:
    """_get_base_type resolves the underlying Avro type."""

    @pytest.mark.parametrize(
        "value, expected",
        [
            ("int", "int"),
            ({"type": "long"}, "long"),
            (["null", "int"], "int"),
            (["string", "null"], "string"),
            ("", ""),
            (None, ""),
            ([], ""),
        ],
        ids=[
            "string", "dict", "union_null_first", "union_null_second",
            "empty_string", "none", "empty_list",
        ],
    )
    def test_get_base_type(self, value, expected):
        assert _get_base_type(value) == expected


class TestIsCompatibleTypeChange:
    """is_compatible_type_change for scalar, union and dict types."""

    @pytest.mark.parametrize(
        "old, new, expected",
        [
            ("int", "int", True),
            ("int", "long", True),
            ("long", "int", False),
            ("boolean", "int", False),
            (["null", "int"], ["null", "long"], True),
            ({"type": "int"}, {"type": "long"}, True),
        ],
        ids=["same", "int_long", "long_int", "unknown", "union", "dict"],
    )
    def test_is_compatible(self, old, new, expected):
        assert is_compatible_type_change(old, new) is expected


class TestNestedAvroRecordsRecursiveFalse:
    """Tests for recursive=False in load_avro_fields."""

    def test_recursive_false_returns_top_level_only(self):
        """load_avro_fields(content, recursive=False) returns only top-level fields."""
        schema = {
            "type": "record",
            "name": "Order",
            "fields": [
                {"name": "order_id", "type": "string"},
                {
                    "name": "items",
                    "type": {
                        "type": "array",
                        "items": {
                            "type": "record",
                            "name": "OrderItem",
                            "fields": [
                                {"name": "product_name", "type": "string"},
                                {"name": "quantity", "type": "int"},
                            ],
                        },
                    },
                },
            ],
        }
        content = json.dumps(schema)
        fields = load_avro_fields(content, recursive=False)

        field_names = [f["name"] for f in fields]
        # Only top-level fields must be present
        assert "order_id" in field_names
        assert "items" in field_names
        # Nested fields must be absent
        assert "items.product_name" not in field_names
        assert "items.quantity" not in field_names
