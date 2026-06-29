"""Tests for manifest_loader.py."""

import json

import pytest
import yaml

from dpm.manifest_loader import ManifestLoader, find_all_manifests, load_avro_schema, load_manifest

# ═══════════════════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def manifests_tree(tmp_path):
    """An examples/ tree with two manifests."""
    sales = tmp_path / "examples" / "sales" / "orders"
    sales.mkdir(parents=True)
    manifest_data = {"spec_version": "1.0.0", "metadata": {"name": "orders"}}
    with open(sales / "manifest.yaml", "w", encoding="utf-8") as f:
        yaml.dump(manifest_data, f)

    warehouse = tmp_path / "examples" / "warehouse" / "inventory"
    warehouse.mkdir(parents=True)
    manifest_data2 = {"spec_version": "1.0.0", "metadata": {"name": "inventory"}}
    with open(warehouse / "manifest.yaml", "w", encoding="utf-8") as f:
        yaml.dump(manifest_data2, f)

    return tmp_path


@pytest.fixture
def valid_avro_schema_file(tmp_path):
    """A valid .avsc file."""
    schema = {
        "type": "record",
        "name": "TestRecord",
        "namespace": "test",
        "fields": [
            {"name": "id", "type": "string"},
            {"name": "value", "type": "int"},
        ],
    }
    avsc_path = tmp_path / "schema.avsc"
    with open(avsc_path, "w", encoding="utf-8") as f:
        json.dump(schema, f)
    return avsc_path


# ═══════════════════════════════════════════════════════════════════════════
# ManifestLoader.find_all_manifests() — class methods
# ═══════════════════════════════════════════════════════════════════════════


class TestManifestLoaderFindAllManifests:
    """Tests for the ManifestLoader.find_all_manifests() method."""

    def test_finds_all_manifests(self, manifests_tree):
        loader = ManifestLoader(base_path=manifests_tree)
        manifests = loader.find_all_manifests()
        assert len(manifests) == 2

    def test_results_are_sorted(self, manifests_tree):
        loader = ManifestLoader(base_path=manifests_tree)
        manifests = loader.find_all_manifests()
        paths_str = [str(p) for p in manifests]
        assert paths_str == sorted(paths_str)

    def test_filter_by_domain(self, manifests_tree):
        loader = ManifestLoader(base_path=manifests_tree)
        manifests = loader.find_all_manifests(domain="sales")
        assert len(manifests) == 1
        assert "sales" in str(manifests[0])

    def test_filter_by_domain_warehouse(self, manifests_tree):
        """The domain filter works for different domains."""
        loader = ManifestLoader(base_path=manifests_tree)
        manifests = loader.find_all_manifests(domain="warehouse")
        assert len(manifests) == 1
        assert "warehouse" in str(manifests[0])

    def test_nonexistent_domain_returns_empty(self, manifests_tree):
        loader = ManifestLoader(base_path=manifests_tree)
        manifests = loader.find_all_manifests(domain="nonexistent")
        assert manifests == []

    def test_no_domains_directory(self, tmp_path):
        loader = ManifestLoader(base_path=tmp_path)
        manifests = loader.find_all_manifests()
        assert manifests == []

    def test_empty_domains_directory(self, tmp_path):
        (tmp_path / "examples").mkdir()
        loader = ManifestLoader(base_path=tmp_path)
        manifests = loader.find_all_manifests()
        assert manifests == []

    def test_rglob_finds_nested_manifests(self, tmp_path):
        """rglob() finds manifests in deeply nested subfolders."""
        deeply_nested = tmp_path / "examples" / "d1" / "d2" / "d3" / "entity"
        deeply_nested.mkdir(parents=True)
        with open(deeply_nested / "manifest.yaml", "w") as f:
            yaml.dump({"spec_version": "1.0.0"}, f)

        loader = ManifestLoader(base_path=tmp_path)
        manifests = loader.find_all_manifests()
        assert len(manifests) == 1


# ═══════════════════════════════════════════════════════════════════════════
# Module-level function find_all_manifests()
# ═══════════════════════════════════════════════════════════════════════════


class TestModuleFindAllManifests:
    """Tests for the module-level find_all_manifests() function."""

    def test_finds_all_manifests(self, manifests_tree):
        manifests = find_all_manifests(manifests_tree)
        assert len(manifests) == 2

    def test_results_are_sorted(self, manifests_tree):
        manifests = find_all_manifests(manifests_tree)
        paths_str = [str(p) for p in manifests]
        assert paths_str == sorted(paths_str)

    def test_filter_by_domain(self, manifests_tree):
        manifests = find_all_manifests(manifests_tree, domain="sales")
        assert len(manifests) == 1
        assert "sales" in str(manifests[0])

    def test_nonexistent_domain_returns_empty(self, manifests_tree):
        manifests = find_all_manifests(manifests_tree, domain="nonexistent")
        assert manifests == []

    def test_no_domains_directory(self, tmp_path):
        manifests = find_all_manifests(tmp_path)
        assert manifests == []

    def test_empty_domains_directory(self, tmp_path):
        (tmp_path / "examples").mkdir()
        manifests = find_all_manifests(tmp_path)
        assert manifests == []

    def test_picks_up_new_manifests(self, manifests_tree):
        """The module-level function is stateless — each call performs rglob()."""
        manifests1 = find_all_manifests(manifests_tree)
        initial_count = len(manifests1)

        new_domain = manifests_tree / "examples" / "new_domain" / "entity"
        new_domain.mkdir(parents=True)
        with open(new_domain / "manifest.yaml", "w") as f:
            yaml.dump({"spec_version": "1.0.0"}, f)

        manifests2 = find_all_manifests(manifests_tree)
        assert len(manifests2) == initial_count + 1


# ═══════════════════════════════════════════════════════════════════════════
# ManifestLoader.load_manifest() — class methods
# ═══════════════════════════════════════════════════════════════════════════


class TestManifestLoaderLoadManifest:
    """Tests for the ManifestLoader.load_manifest() method."""

    def test_load_valid_yaml(self, manifests_tree):
        loader = ManifestLoader(base_path=manifests_tree)
        manifest_path = manifests_tree / "examples" / "sales" / "orders" / "manifest.yaml"
        data = loader.load_manifest(manifest_path)
        assert data["spec_version"] == "1.0.0"
        assert data["metadata"]["name"] == "orders"

    def test_load_empty_yaml_returns_empty_dict(self, tmp_path):
        loader = ManifestLoader(base_path=tmp_path)
        empty_file = tmp_path / "empty.yaml"
        empty_file.write_text("---\n", encoding="utf-8")
        data = loader.load_manifest(empty_file)
        assert data == {}

    def test_load_nonexistent_file_raises(self, tmp_path):
        loader = ManifestLoader(base_path=tmp_path)
        with pytest.raises(FileNotFoundError):
            loader.load_manifest(tmp_path / "nonexistent.yaml")

    def test_load_invalid_yaml_raises(self, tmp_path):
        loader = ManifestLoader(base_path=tmp_path)
        bad_file = tmp_path / "bad.yaml"
        bad_file.write_text("key:\n  - item1\n item2\n", encoding="utf-8")
        with pytest.raises(yaml.YAMLError):
            loader.load_manifest(bad_file)

    def test_utf8_encoding(self, tmp_path):
        loader = ManifestLoader(base_path=tmp_path)
        manifest_data = {"metadata": {"description": "Üñïçödé café 日本語"}}
        manifest_path = tmp_path / "manifest.yaml"
        with open(manifest_path, "w", encoding="utf-8") as f:
            yaml.dump(manifest_data, f, allow_unicode=True)
        data = loader.load_manifest(manifest_path)
        assert "café" in data["metadata"]["description"]

    def test_caching_returns_same_object(self, manifests_tree):
        """Caching: the second call returns the same in-memory object."""
        loader = ManifestLoader(base_path=manifests_tree)
        path = manifests_tree / "examples" / "sales" / "orders" / "manifest.yaml"
        data1 = loader.load_manifest(path)
        data2 = loader.load_manifest(path)
        assert data1 is data2

    def test_caching_uses_resolved_path(self, manifests_tree):
        """Caching uses resolve() — the same file via different paths."""
        loader = ManifestLoader(base_path=manifests_tree)
        path_abs = manifests_tree / "examples" / "sales" / "orders" / "manifest.yaml"
        path_with_dots = manifests_tree / "examples" / "sales" / "orders" / "." / "manifest.yaml"

        data1 = loader.load_manifest(path_abs)
        data2 = loader.load_manifest(path_with_dots)
        assert data1 is data2

    def test_clear_cache_reloads(self, manifests_tree):
        """clear() forces the next call to re-read the file."""
        loader = ManifestLoader(base_path=manifests_tree)
        path = manifests_tree / "examples" / "sales" / "orders" / "manifest.yaml"
        data1 = loader.load_manifest(path)
        loader.clear_cache()
        data2 = loader.load_manifest(path)
        assert data1 is not data2
        assert data1 == data2

    def test_different_files_not_cached_together(self, manifests_tree):
        """Different files are cached separately."""
        loader = ManifestLoader(base_path=manifests_tree)
        path1 = manifests_tree / "examples" / "sales" / "orders" / "manifest.yaml"
        path2 = manifests_tree / "examples" / "warehouse" / "inventory" / "manifest.yaml"
        data1 = loader.load_manifest(path1)
        data2 = loader.load_manifest(path2)
        assert data1 is not data2
        assert data1["metadata"]["name"] != data2["metadata"]["name"]

    def test_cache_mutation_affects_subsequent_calls(self, manifests_tree):
        """The cache stores object references, not copies.

        This behavior is documented: callers must not mutate the returned data.
        """
        loader = ManifestLoader(base_path=manifests_tree)
        path = manifests_tree / "examples" / "sales" / "orders" / "manifest.yaml"
        data1 = loader.load_manifest(path)
        data1["metadata"]["name"] = "MODIFIED"

        data2 = loader.load_manifest(path)
        assert data2["metadata"]["name"] == "MODIFIED"


# ═══════════════════════════════════════════════════════════════════════════
# Module-level function load_manifest()
# ═══════════════════════════════════════════════════════════════════════════


class TestModuleLoadManifest:
    """Tests for the module-level load_manifest() function."""

    def test_load_valid_yaml(self, manifests_tree):
        manifest_path = manifests_tree / "examples" / "sales" / "orders" / "manifest.yaml"
        data = load_manifest(manifest_path)
        assert data["spec_version"] == "1.0.0"
        assert data["metadata"]["name"] == "orders"

    def test_load_empty_yaml_returns_empty_dict(self, tmp_path):
        empty_file = tmp_path / "empty.yaml"
        empty_file.write_text("---\n", encoding="utf-8")
        data = load_manifest(empty_file)
        assert data == {}

    def test_load_nonexistent_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_manifest(tmp_path / "nonexistent.yaml")

    def test_load_invalid_yaml_raises(self, tmp_path):
        bad_file = tmp_path / "bad.yaml"
        bad_file.write_text("key:\n  - item1\n item2\n", encoding="utf-8")
        with pytest.raises(yaml.YAMLError):
            load_manifest(bad_file)

    def test_utf8_encoding(self, tmp_path):
        manifest_data = {"metadata": {"description": "Üñïçödé café 日本語"}}
        manifest_path = tmp_path / "manifest.yaml"
        with open(manifest_path, "w", encoding="utf-8") as f:
            yaml.dump(manifest_data, f, allow_unicode=True)
        data = load_manifest(manifest_path)
        assert "café" in data["metadata"]["description"]

    def test_stateless_no_caching(self, tmp_path):
        """The module-level function is stateless — each call creates a new loader."""
        manifest_path = tmp_path / "manifest.yaml"
        manifest_data = {"spec_version": "1.0.0"}
        with open(manifest_path, "w") as f:
            yaml.dump(manifest_data, f)

        data1 = load_manifest(manifest_path)
        data2 = load_manifest(manifest_path)
        # Different objects (a new loader each time), same content
        assert data1 is not data2
        assert data1 == data2


# ═══════════════════════════════════════════════════════════════════════════
# ManifestLoader.load_avro_schema()
# ═══════════════════════════════════════════════════════════════════════════


class TestManifestLoaderLoadAvroSchema:
    """Tests for the ManifestLoader.load_avro_schema() method."""

    def test_load_valid_avsc(self, tmp_path, valid_avro_schema_file):
        loader = ManifestLoader(base_path=tmp_path)
        schema = loader.load_avro_schema(valid_avro_schema_file)
        assert schema["type"] == "record"
        assert schema["name"] == "TestRecord"
        assert len(schema["fields"]) == 2

    def test_load_nonexistent_avsc_raises(self, tmp_path):
        loader = ManifestLoader(base_path=tmp_path)
        with pytest.raises(FileNotFoundError):
            loader.load_avro_schema(tmp_path / "nonexistent.avsc")

    def test_load_invalid_json_raises(self, tmp_path):
        loader = ManifestLoader(base_path=tmp_path)
        bad_file = tmp_path / "bad.avsc"
        bad_file.write_text("{invalid json", encoding="utf-8")
        with pytest.raises(json.JSONDecodeError):
            loader.load_avro_schema(bad_file)

    def test_load_avro_schema_no_caching(self, tmp_path):
        """load_avro_schema() does NOT cache results (unlike load_manifest)."""
        loader = ManifestLoader(base_path=tmp_path)
        schema_file = tmp_path / "schema.avsc"
        schema = {
            "type": "record",
            "name": "TestRecord",
            "fields": [{"name": "id", "type": "string"}],
        }
        with open(schema_file, "w") as f:
            json.dump(schema, f)

        data1 = loader.load_avro_schema(schema_file)
        data2 = loader.load_avro_schema(schema_file)
        assert data1 is not data2
        assert data1 == data2

    def test_load_utf8_avro_schema(self, tmp_path):
        """UTF-8 in an Avro schema."""
        loader = ManifestLoader(base_path=tmp_path)
        schema = {
            "type": "record",
            "name": "TestRecord",
            "doc": "Üñïçödé café 日本語",
            "fields": [],
        }
        schema_file = tmp_path / "schema.avsc"
        with open(schema_file, "w", encoding="utf-8") as f:
            json.dump(schema, f, ensure_ascii=False)

        loaded = loader.load_avro_schema(schema_file)
        assert "café" in loaded["doc"]


# ═══════════════════════════════════════════════════════════════════════════
# Module-level function load_avro_schema()
# ═══════════════════════════════════════════════════════════════════════════


class TestModuleLoadAvroSchema:
    """Tests for the module-level load_avro_schema() function."""

    def test_load_valid_avsc(self, valid_avro_schema_file):
        schema = load_avro_schema(valid_avro_schema_file)
        assert schema["type"] == "record"
        assert schema["name"] == "TestRecord"
        assert len(schema["fields"]) == 2

    def test_load_nonexistent_avsc_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_avro_schema(tmp_path / "nonexistent.avsc")

    def test_load_invalid_json_raises(self, tmp_path):
        bad_file = tmp_path / "bad.avsc"
        bad_file.write_text("{invalid json", encoding="utf-8")
        with pytest.raises(json.JSONDecodeError):
            load_avro_schema(bad_file)


# ═══════════════════════════════════════════════════════════════════════════
# Edge cases and error handling
# ═══════════════════════════════════════════════════════════════════════════


class TestEdgeCases:
    """Edge cases and error handling."""

    def test_load_binary_file_as_yaml(self, tmp_path):
        """Loading a binary file as YAML."""
        loader = ManifestLoader(base_path=tmp_path)
        binary_file = tmp_path / "binary.yaml"
        with open(binary_file, "wb") as f:
            f.write(b"\x80\x81\x82\x83")

        with pytest.raises(Exception):  # yaml.YAMLError or UnicodeDecodeError
            loader.load_manifest(binary_file)

    def test_load_yaml_with_special_characters(self, tmp_path):
        """YAML with multibyte characters."""
        loader = ManifestLoader(base_path=tmp_path)
        manifest_data = {
            "metadata": {
                "description": "日本語 한국어 Ελληνικά العربية",
            }
        }
        manifest_path = tmp_path / "manifest.yaml"
        with open(manifest_path, "w", encoding="utf-8") as f:
            yaml.dump(manifest_data, f, allow_unicode=True)

        data = loader.load_manifest(manifest_path)
        assert "日本語" in data["metadata"]["description"]

    def test_very_large_yaml_file(self, tmp_path):
        """Caching a large YAML file."""
        loader = ManifestLoader(base_path=tmp_path)
        large_data = {
            "spec_version": "1.0.0",
            "metadata": {
                "fields": [{"name": f"field_{i}", "type": "string"} for i in range(1000)]
            },
        }
        manifest_path = tmp_path / "large.yaml"
        with open(manifest_path, "w") as f:
            yaml.dump(large_data, f)

        data1 = loader.load_manifest(manifest_path)
        data2 = loader.load_manifest(manifest_path)
        assert data1 is data2

    def test_empty_json_avro_schema(self, tmp_path):
        """An empty JSON object in an .avsc file."""
        loader = ManifestLoader(base_path=tmp_path)
        schema_file = tmp_path / "empty.avsc"
        with open(schema_file, "w") as f:
            json.dump({}, f)

        loaded = loader.load_avro_schema(schema_file)
        assert loaded == {}

    def test_find_manifests_pattern_is_case_sensitive(self, tmp_path):
        """rglob('manifest.yaml') is case-sensitive."""
        loader = ManifestLoader(base_path=tmp_path)
        domain = tmp_path / "examples" / "test" / "entity"
        domain.mkdir(parents=True)

        with open(domain / "manifest.yaml", "w") as f:
            yaml.dump({"spec_version": "1.0.0"}, f)

        manifests = loader.find_all_manifests()
        assert len(manifests) == 1
        assert manifests[0].name == "manifest.yaml"
