"""
Tests for the Configuration Management Module.

Covers:
- ConfigLoader: file loading, schema validation, caching.
- SchemaRegistry: schema loading and validation.
- VersionCompatManager: version migrations and backward compatibility.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest
import yaml

from src.config.loader import ConfigLoader, ConfigurationError
from src.config.schema_registry import SchemaRegistry, SchemaValidationError
from src.config.version_compat import VersionCompatManager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_config_dir(tmp_path: Path) -> Path:
    """Create a temporary config directory with schemas."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    schema_dir = config_dir / "schemas"
    schema_dir.mkdir()
    return config_dir


@pytest.fixture
def sample_hardware_config() -> dict:
    """Return a valid hardware configuration dictionary."""
    return {
        "schema_version": "1.0.0",
        "test_bench": {
            "id": "bench_001",
            "name": "Test Bench Alpha",
            "hardware_type": "radar_v2",
        },
        "uut": {
            "model": "RadarUnit_X100",
            "interface": "ethernet",
            "ip_address": "192.168.1.100",
            "port": 5000,
        },
        "psu": {
            "model": "PSU_3000",
            "interface": "serial",
            "port": "COM3",
            "voltage_range": {"min": 0.0, "max": 30.0},
            "current_limit": 5.0,
        },
        "ptp": {
            "enabled": True,
            "master_ip": "192.168.1.1",
            "domain": 0,
            "sync_timeout_sec": 30,
        },
        "host": {
            "ip_address": "192.168.1.10",
            "driver_library": "radar_driver_v2.dll",
        },
    }


@pytest.fixture
def sample_thresholds_config() -> dict:
    """Return a valid thresholds configuration dictionary."""
    return {
        "schema_version": "1.0.0",
        "radar_firmware_version": "2.1.0",
        "thresholds": {
            "signal_to_noise_ratio": {
                "min_db": 15.0,
                "max_db": None,
                "description": "Minimum acceptable SNR in dB",
            },
            "latency": {
                "max_ms": 50.0,
                "description": "Maximum processing latency",
            },
        },
    }


@pytest.fixture
def hardware_schema() -> dict:
    """Return a minimal hardware config JSON schema for testing."""
    return {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "object",
        "required": ["schema_version", "test_bench"],
        "properties": {
            "schema_version": {"type": "string"},
            "test_bench": {
                "type": "object",
                "required": ["id", "name", "hardware_type"],
                "properties": {
                    "id": {"type": "string"},
                    "name": {"type": "string"},
                    "hardware_type": {"type": "string"},
                },
            },
        },
    }


# ---------------------------------------------------------------------------
# ConfigLoader Tests
# ---------------------------------------------------------------------------


class TestConfigLoader:
    """Tests for the ConfigLoader class."""

    def test_load_yaml_file(
        self, tmp_config_dir: Path, sample_hardware_config: dict
    ) -> None:
        """Test loading a valid YAML configuration file."""
        config_file = tmp_config_dir / "hardware_config.yaml"
        config_file.write_text(yaml.dump(sample_hardware_config), encoding="utf-8")

        loader = ConfigLoader(config_dir=tmp_config_dir)
        result = loader.load("hardware_config.yaml", validate=False)

        assert result["schema_version"] == "1.0.0"
        assert result["test_bench"]["id"] == "bench_001"
        assert result["uut"]["ip_address"] == "192.168.1.100"

    def test_load_json_file(
        self, tmp_config_dir: Path, sample_hardware_config: dict
    ) -> None:
        """Test loading a valid JSON configuration file."""
        config_file = tmp_config_dir / "hardware_config.json"
        config_file.write_text(json.dumps(sample_hardware_config), encoding="utf-8")

        loader = ConfigLoader(config_dir=tmp_config_dir)
        result = loader.load("hardware_config.json", validate=False)

        assert result["schema_version"] == "1.0.0"
        assert result["test_bench"]["name"] == "Test Bench Alpha"

    def test_load_file_not_found(self, tmp_config_dir: Path) -> None:
        """Test that FileNotFoundError is raised for missing files."""
        loader = ConfigLoader(config_dir=tmp_config_dir)
        with pytest.raises(FileNotFoundError, match="Configuration file not found"):
            loader.load("nonexistent.yaml", validate=False)

    def test_load_unsupported_format(self, tmp_config_dir: Path) -> None:
        """Test that ConfigurationError is raised for unsupported formats."""
        bad_file = tmp_config_dir / "config.txt"
        bad_file.write_text("some data", encoding="utf-8")

        loader = ConfigLoader(config_dir=tmp_config_dir)
        with pytest.raises(ConfigurationError, match="Unsupported file format"):
            loader.load("config.txt", validate=False)

    def test_load_invalid_yaml(self, tmp_config_dir: Path) -> None:
        """Test that ConfigurationError is raised for malformed YAML."""
        bad_file = tmp_config_dir / "bad.yaml"
        bad_file.write_text("key: [invalid yaml{", encoding="utf-8")

        loader = ConfigLoader(config_dir=tmp_config_dir)
        with pytest.raises(ConfigurationError, match="Failed to parse"):
            loader.load("bad.yaml", validate=False)

    def test_load_with_caching(
        self, tmp_config_dir: Path, sample_hardware_config: dict
    ) -> None:
        """Test that config loading uses cache on second call."""
        config_file = tmp_config_dir / "hardware_config.yaml"
        config_file.write_text(yaml.dump(sample_hardware_config), encoding="utf-8")

        loader = ConfigLoader(config_dir=tmp_config_dir)
        result1 = loader.load("hardware_config.yaml", validate=False)
        result2 = loader.load("hardware_config.yaml", validate=False)

        assert result1 is result2  # Same object from cache

    def test_clear_cache(
        self, tmp_config_dir: Path, sample_hardware_config: dict
    ) -> None:
        """Test that cache clearing forces a re-read."""
        config_file = tmp_config_dir / "hardware_config.yaml"
        config_file.write_text(yaml.dump(sample_hardware_config), encoding="utf-8")

        loader = ConfigLoader(config_dir=tmp_config_dir)
        result1 = loader.load("hardware_config.yaml", validate=False)
        loader.clear_cache()
        result2 = loader.load("hardware_config.yaml", validate=False)

        assert result1 is not result2  # Different objects after cache clear
        assert result1 == result2  # But same content

    def test_load_with_schema_validation(
        self,
        tmp_config_dir: Path,
        sample_hardware_config: dict,
        hardware_schema: dict,
    ) -> None:
        """Test loading with schema validation enabled."""
        config_file = tmp_config_dir / "hardware_config.yaml"
        config_file.write_text(yaml.dump(sample_hardware_config), encoding="utf-8")

        schema_dir = tmp_config_dir / "schemas"
        schema_file = schema_dir / "hardware_config_schema.json"
        schema_file.write_text(json.dumps(hardware_schema), encoding="utf-8")

        loader = ConfigLoader(config_dir=tmp_config_dir)
        result = loader.load("hardware_config.yaml", schema_name="hardware_config_schema")

        assert result["test_bench"]["hardware_type"] == "radar_v2"

    def test_load_fails_schema_validation(
        self,
        tmp_config_dir: Path,
        hardware_schema: dict,
    ) -> None:
        """Test that invalid config fails schema validation."""
        # Missing required 'test_bench' field
        invalid_config = {"schema_version": "1.0.0"}
        config_file = tmp_config_dir / "hardware_config.yaml"
        config_file.write_text(yaml.dump(invalid_config), encoding="utf-8")

        schema_dir = tmp_config_dir / "schemas"
        schema_file = schema_dir / "hardware_config_schema.json"
        schema_file.write_text(json.dumps(hardware_schema), encoding="utf-8")

        loader = ConfigLoader(config_dir=tmp_config_dir)
        with pytest.raises(ConfigurationError, match="validation failed"):
            loader.load("hardware_config.yaml", schema_name="hardware_config_schema")


# ---------------------------------------------------------------------------
# SchemaRegistry Tests
# ---------------------------------------------------------------------------


class TestSchemaRegistry:
    """Tests for the SchemaRegistry class."""

    def test_load_schema(self, tmp_config_dir: Path, hardware_schema: dict) -> None:
        """Test loading a schema from disk."""
        schema_dir = tmp_config_dir / "schemas"
        schema_file = schema_dir / "test_schema.json"
        schema_file.write_text(json.dumps(hardware_schema), encoding="utf-8")

        registry = SchemaRegistry(schema_dir)
        schema = registry.get_schema("test_schema")

        assert schema["type"] == "object"
        assert "test_bench" in schema["properties"]

    def test_schema_caching(self, tmp_config_dir: Path, hardware_schema: dict) -> None:
        """Test that schemas are cached after first load."""
        schema_dir = tmp_config_dir / "schemas"
        schema_file = schema_dir / "test_schema.json"
        schema_file.write_text(json.dumps(hardware_schema), encoding="utf-8")

        registry = SchemaRegistry(schema_dir)
        schema1 = registry.get_schema("test_schema")
        schema2 = registry.get_schema("test_schema")

        assert schema1 is schema2

    def test_schema_not_found(self, tmp_config_dir: Path) -> None:
        """Test that FileNotFoundError is raised for missing schemas."""
        schema_dir = tmp_config_dir / "schemas"
        registry = SchemaRegistry(schema_dir)

        with pytest.raises(FileNotFoundError, match="Schema not found"):
            registry.get_schema("nonexistent_schema")

    def test_validate_valid_data(
        self, tmp_config_dir: Path, hardware_schema: dict, sample_hardware_config: dict
    ) -> None:
        """Test validation with valid data passes."""
        schema_dir = tmp_config_dir / "schemas"
        schema_file = schema_dir / "hw_schema.json"
        schema_file.write_text(json.dumps(hardware_schema), encoding="utf-8")

        registry = SchemaRegistry(schema_dir)
        # Should not raise
        registry.validate(sample_hardware_config, "hw_schema")

    def test_validate_invalid_data(
        self, tmp_config_dir: Path, hardware_schema: dict
    ) -> None:
        """Test validation with invalid data raises SchemaValidationError."""
        schema_dir = tmp_config_dir / "schemas"
        schema_file = schema_dir / "hw_schema.json"
        schema_file.write_text(json.dumps(hardware_schema), encoding="utf-8")

        invalid_data = {"schema_version": 123}  # Wrong type, missing fields

        registry = SchemaRegistry(schema_dir)
        with pytest.raises(SchemaValidationError, match="validation failed"):
            registry.validate(invalid_data, "hw_schema")

    def test_list_schemas(self, tmp_config_dir: Path, hardware_schema: dict) -> None:
        """Test listing available schemas."""
        schema_dir = tmp_config_dir / "schemas"
        (schema_dir / "schema_a.json").write_text("{}", encoding="utf-8")
        (schema_dir / "schema_b.json").write_text("{}", encoding="utf-8")

        registry = SchemaRegistry(schema_dir)
        schemas = registry.list_schemas()

        assert sorted(schemas) == ["schema_a", "schema_b"]


# ---------------------------------------------------------------------------
# VersionCompatManager Tests
# ---------------------------------------------------------------------------


class TestVersionCompatManager:
    """Tests for the VersionCompatManager class."""

    def test_current_version_no_migration(self) -> None:
        """Test that current version config is returned as-is."""
        manager = VersionCompatManager()
        config = {"schema_version": "1.0.0", "data": "test"}
        result = manager.migrate(config)

        assert result["schema_version"] == "1.0.0"
        assert result["data"] == "test"

    def test_missing_version_gets_current(self) -> None:
        """Test that config without schema_version gets current version injected."""
        manager = VersionCompatManager()
        config = {"data": "test"}
        result = manager.migrate(config)

        assert result["schema_version"] == "1.0.0"
        assert result["data"] == "test"

    def test_builtin_migration_radar_type_rename(self) -> None:
        """Test built-in migration: radar_type -> hardware_type."""
        manager = VersionCompatManager()
        config = {
            "schema_version": "0.1.0",
            "test_bench": {
                "id": "bench_001",
                "name": "Old Bench",
                "radar_type": "radar_v1",
            },
        }
        result = manager.migrate(config)

        assert "radar_type" not in result["test_bench"]
        assert result["test_bench"]["hardware_type"] == "radar_v1"

    def test_builtin_migration_adds_ptp_defaults(self) -> None:
        """Test built-in migration: PTP section added with defaults."""
        manager = VersionCompatManager()
        config = {
            "schema_version": "0.1.0",
            "test_bench": {"id": "b1", "name": "B1", "hardware_type": "rv1"},
        }
        result = manager.migrate(config)

        assert "ptp" in result
        assert result["ptp"]["enabled"] is False
        assert result["ptp"]["sync_timeout_sec"] == 30

    def test_custom_migration_registration(self) -> None:
        """Test registering and applying a custom migration."""
        manager = VersionCompatManager()
        manager.CURRENT_VERSION = "2.0.0"

        @manager.register_migration("1.0.0", "2.0.0")
        def _migrate_1_to_2(config: dict) -> dict:
            config["new_field"] = "added_by_migration"
            return config

        config = {"schema_version": "1.0.0", "data": "test"}
        result = manager.migrate(config)

        assert result["new_field"] == "added_by_migration"
        assert result["schema_version"] == "2.0.0"

    def test_get_migration_path(self) -> None:
        """Test getting the migration path from a given version."""
        manager = VersionCompatManager()
        path = manager.get_migration_path("0.1.0")

        assert len(path) >= 1
        assert path[0] == ("0.1.0", "1.0.0")

    def test_version_tuple_parsing(self) -> None:
        """Test version string to tuple conversion."""
        assert VersionCompatManager._version_tuple("1.2.3") == (1, 2, 3)
        assert VersionCompatManager._version_tuple("0.1.0") == (0, 1, 0)
        assert VersionCompatManager._version_tuple("invalid") == (0, 0, 0)

