"""
Schema Registry Module.

Manages JSON schemas for configuration validation.
Loads schemas from disk and provides validation capabilities using jsonschema.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from loguru import logger

try:
    import jsonschema
    from jsonschema import ValidationError as JsonSchemaValidationError
except ImportError:
    jsonschema = None  # type: ignore[assignment]
    JsonSchemaValidationError = Exception  # type: ignore[assignment, misc]


class SchemaValidationError(Exception):
    """Raised when a configuration fails schema validation."""

    def __init__(self, message: str, errors: list[str] | None = None) -> None:
        super().__init__(message)
        self.errors = errors or []


class SchemaRegistry:
    """
    Registry for JSON schemas used to validate configuration files.

    Schemas are loaded lazily from a directory on disk and cached
    for subsequent validations.

    Attributes:
        schema_dir: Directory containing JSON schema files.
    """

    def __init__(self, schema_dir: str | Path) -> None:
        """
        Initialize the schema registry.

        Args:
            schema_dir: Path to directory containing JSON schema files.
        """
        self.schema_dir = Path(schema_dir)
        self._schemas: Dict[str, Dict[str, Any]] = {}
        logger.debug(f"SchemaRegistry initialized — schema_dir={self.schema_dir}")

    def get_schema(self, schema_name: str) -> Dict[str, Any]:
        """
        Retrieve a JSON schema by name, loading from disk if not cached.

        Args:
            schema_name: Schema identifier (filename without .json extension).

        Returns:
            Parsed JSON schema as a dictionary.

        Raises:
            FileNotFoundError: If the schema file does not exist.
        """
        if schema_name in self._schemas:
            return self._schemas[schema_name]

        schema_path = self.schema_dir / f"{schema_name}.json"
        if not schema_path.exists():
            raise FileNotFoundError(
                f"Schema not found: {schema_name} (expected at {schema_path})"
            )

        try:
            content = schema_path.read_text(encoding="utf-8")
            schema = json.loads(content)
        except (OSError, json.JSONDecodeError) as e:
            raise SchemaValidationError(f"Failed to load schema {schema_name}: {e}")

        self._schemas[schema_name] = schema
        logger.debug(f"Schema loaded: {schema_name}")
        return schema

    def validate(self, data: Dict[str, Any], schema_name: str) -> None:
        """
        Validate a configuration dictionary against a named schema.

        Args:
            data: Configuration data to validate.
            schema_name: Name of the schema to validate against.

        Raises:
            SchemaValidationError: If validation fails, with details of all errors.
        """
        schema = self.get_schema(schema_name)

        if jsonschema is None:
            logger.warning(
                "jsonschema package not installed — skipping schema validation. "
                "Install with: pip install jsonschema"
            )
            return

        validator_cls = jsonschema.Draft7Validator
        validator = validator_cls(schema)
        errors = sorted(validator.iter_errors(data), key=lambda e: list(e.path))

        if errors:
            error_messages = []
            for error in errors:
                path = " -> ".join(str(p) for p in error.absolute_path) or "(root)"
                error_messages.append(f"  [{path}] {error.message}")

            all_errors = "\n".join(error_messages)
            raise SchemaValidationError(
                f"Schema validation failed for '{schema_name}' "
                f"({len(errors)} error(s)):\n{all_errors}",
                errors=error_messages,
            )

        logger.debug(f"Validation passed: {schema_name}")

    def list_schemas(self) -> list[str]:
        """List all available schema names in the schema directory."""
        if not self.schema_dir.exists():
            return []
        return [
            f.stem
            for f in self.schema_dir.glob("*.json")
            if f.is_file()
        ]

