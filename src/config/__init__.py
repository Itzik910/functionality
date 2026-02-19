"""
Configuration Management Module.

Handles loading and validation of:
- Hardware configuration files (JSON/YAML).
- Threshold/limits files with version-aware backward compatibility.
- Environment-specific settings.
"""

from src.config.loader import ConfigLoader, ConfigurationError
from src.config.schema_registry import SchemaRegistry

__all__ = ["ConfigLoader", "ConfigurationError", "SchemaRegistry"]
