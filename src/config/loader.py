"""
Configuration Loader Module.

Provides a base configuration loader class that handles:
- Loading YAML and JSON configuration files.
- Schema validation using JSON Schema.
- Version-aware backward compatibility for older config formats.
- Merging of default values with user-provided overrides.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

import yaml
from loguru import logger

from src.config.schema_registry import SchemaRegistry
from src.config.version_compat import VersionCompatManager


class ConfigurationError(Exception):
    """Raised when a configuration file is invalid or cannot be loaded."""

    pass


class ConfigLoader:
    """
    Base configuration loader with schema validation and backward compatibility.

    This class handles loading configuration files (YAML/JSON), validating them
    against JSON schemas, and applying version-aware migrations for backward
    compatibility with older configuration formats.

    Attributes:
        config_dir: Base directory for configuration files.
        schema_registry: Registry of JSON schemas for validation.
        version_manager: Handles version-aware migrations.
    """

    SUPPORTED_EXTENSIONS = {".yaml", ".yml", ".json"}

    def __init__(
        self,
        config_dir: str | Path = "config",
        schema_dir: str | Path | None = None,
    ) -> None:
        """
        Initialize the configuration loader.

        Args:
            config_dir: Path to the directory containing configuration files.
            schema_dir: Path to the directory containing JSON schema files.
                        Defaults to config_dir/schemas/.
        """
        self.config_dir = Path(config_dir)
        schema_dir = Path(schema_dir) if schema_dir else self.config_dir / "schemas"
        self.schema_registry = SchemaRegistry(schema_dir)
        self.version_manager = VersionCompatManager()
        self._cache: Dict[str, Dict[str, Any]] = {}

        logger.info(f"ConfigLoader initialized — config_dir={self.config_dir}")

    def load(
        self,
        filename: str,
        schema_name: Optional[str] = None,
        *,
        validate: bool = True,
        use_cache: bool = True,
    ) -> Dict[str, Any]:
        """
        Load a configuration file with optional schema validation.

        Args:
            filename: Name or relative path of the config file within config_dir.
            schema_name: JSON schema name to validate against (without extension).
                         If None, auto-detected from filename.
            validate: Whether to validate against the schema.
            use_cache: Whether to use cached config if available.

        Returns:
            Parsed configuration as a dictionary.

        Raises:
            ConfigurationError: If the file cannot be loaded or fails validation.
            FileNotFoundError: If the configuration file does not exist.
        """
        file_path = self._resolve_path(filename)
        cache_key = str(file_path.resolve())

        if use_cache and cache_key in self._cache:
            logger.debug(f"Returning cached config for: {filename}")
            return self._cache[cache_key]

        logger.info(f"Loading configuration: {file_path}")
        data = self._read_file(file_path)

        # Apply version migrations if needed
        data = self.version_manager.migrate(data)

        # Validate against schema
        if validate:
            resolved_schema_name = schema_name or self._infer_schema_name(filename)
            if resolved_schema_name:
                self._validate(data, resolved_schema_name)

        if use_cache:
            self._cache[cache_key] = data

        logger.info(f"Configuration loaded successfully: {filename}")
        return data

    def load_hardware_config(self, filename: str = "hardware_config.yaml") -> Dict[str, Any]:
        """
        Load a hardware configuration file.

        Args:
            filename: Hardware config filename (default: hardware_config.yaml).

        Returns:
            Parsed hardware configuration.
        """
        return self.load(filename, schema_name="hardware_config_schema")

    def load_thresholds(self, filename: str = "thresholds.yaml") -> Dict[str, Any]:
        """
        Load a thresholds/limits configuration file.

        Args:
            filename: Thresholds config filename (default: thresholds.yaml).

        Returns:
            Parsed thresholds configuration.
        """
        return self.load(filename, schema_name="thresholds_schema")

    def load_environment(self, filename: str = "test_environment.yaml") -> Dict[str, Any]:
        """
        Load the test environment configuration file.

        Args:
            filename: Environment config filename (default: test_environment.yaml).

        Returns:
            Parsed environment configuration.
        """
        return self.load(filename, schema_name="test_environment_schema")

    def clear_cache(self) -> None:
        """Clear all cached configurations."""
        self._cache.clear()
        logger.debug("Configuration cache cleared.")

    def _resolve_path(self, filename: str) -> Path:
        """Resolve a filename to a full path, checking config_dir first."""
        path = Path(filename)
        if path.is_absolute() and path.exists():
            return path

        config_path = self.config_dir / filename
        if config_path.exists():
            return config_path

        if path.exists():
            return path

        raise FileNotFoundError(
            f"Configuration file not found: {filename} "
            f"(searched in {self.config_dir} and current directory)"
        )

    def _read_file(self, file_path: Path) -> Dict[str, Any]:
        """Read and parse a YAML or JSON file."""
        suffix = file_path.suffix.lower()
        if suffix not in self.SUPPORTED_EXTENSIONS:
            raise ConfigurationError(
                f"Unsupported file format '{suffix}'. "
                f"Supported: {self.SUPPORTED_EXTENSIONS}"
            )

        try:
            content = file_path.read_text(encoding="utf-8")
        except OSError as e:
            raise ConfigurationError(f"Failed to read file {file_path}: {e}") from e

        try:
            if suffix in {".yaml", ".yml"}:
                data = yaml.safe_load(content)
            else:
                data = json.loads(content)
        except (yaml.YAMLError, json.JSONDecodeError) as e:
            raise ConfigurationError(f"Failed to parse {file_path}: {e}") from e

        if not isinstance(data, dict):
            raise ConfigurationError(
                f"Configuration file must contain a mapping (dict), "
                f"got {type(data).__name__}: {file_path}"
            )

        return data

    def _validate(self, data: Dict[str, Any], schema_name: str) -> None:
        """Validate configuration data against a JSON schema."""
        try:
            self.schema_registry.validate(data, schema_name)
            logger.debug(f"Schema validation passed: {schema_name}")
        except Exception as e:
            raise ConfigurationError(
                f"Configuration validation failed against schema '{schema_name}': {e}"
            ) from e

    @staticmethod
    def _infer_schema_name(filename: str) -> Optional[str]:
        """
        Infer the schema name from the configuration filename.

        Examples:
            hardware_config.yaml -> hardware_config_schema
            thresholds.yaml -> thresholds_schema
            test_environment.yaml -> test_environment_schema
        """
        stem = Path(filename).stem
        # Strip .example suffix if present
        if stem.endswith(".example"):
            stem = stem.rsplit(".example", 1)[0]

        schema_map = {
            "hardware_config": "hardware_config_schema",
            "thresholds": "thresholds_schema",
            "test_environment": "test_environment_schema",
        }
        return schema_map.get(stem)

