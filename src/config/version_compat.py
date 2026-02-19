"""
Version Compatibility Manager.

Handles backward compatibility for configuration files from older versions.
Implements a migration pipeline that transforms old config formats to
the current version, ensuring customers using older radar firmware can
still use the test environment without config file changes.

Design Reference: Section 2 of design document — "Full versioning support
to ensure backward compatibility for customers using older versions."
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Tuple

from loguru import logger


# Type alias for migration functions:
# (config_data) -> config_data
MigrationFunc = Callable[[Dict[str, Any]], Dict[str, Any]]


class VersionCompatManager:
    """
    Manages version-aware migrations for configuration files.

    Migrations are registered as functions that transform a config dict
    from one schema version to the next. When loading a config file with
    an older schema_version, all applicable migrations are applied in order.

    Example:
        manager = VersionCompatManager()

        @manager.register_migration("0.1.0", "1.0.0")
        def migrate_v0_to_v1(config):
            # Transform old format to new format
            if "old_field" in config:
                config["new_field"] = config.pop("old_field")
            return config
    """

    # The current expected schema version
    CURRENT_VERSION = "1.0.0"

    def __init__(self) -> None:
        """Initialize the version compatibility manager."""
        self._migrations: List[Tuple[str, str, MigrationFunc]] = []
        self._register_builtin_migrations()

    def register_migration(
        self, from_version: str, to_version: str
    ) -> Callable[[MigrationFunc], MigrationFunc]:
        """
        Decorator to register a migration function.

        Args:
            from_version: Source schema version (semver string).
            to_version: Target schema version (semver string).

        Returns:
            Decorator function.
        """

        def decorator(func: MigrationFunc) -> MigrationFunc:
            self._migrations.append((from_version, to_version, func))
            # Keep migrations sorted by from_version
            self._migrations.sort(key=lambda m: self._version_tuple(m[0]))
            logger.debug(f"Registered migration: {from_version} -> {to_version}")
            return func

        return decorator

    def migrate(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Apply all necessary migrations to bring a config to the current version.

        If the config has no schema_version field, it is assumed to be current
        and returned as-is with the current version injected.

        Args:
            config: Configuration dictionary to migrate.

        Returns:
            Migrated configuration dictionary.
        """
        current_version = config.get("schema_version")

        if current_version is None:
            logger.debug("No schema_version found — assuming current version.")
            config["schema_version"] = self.CURRENT_VERSION
            return config

        if current_version == self.CURRENT_VERSION:
            logger.debug(f"Config already at current version ({self.CURRENT_VERSION}).")
            return config

        logger.info(
            f"Migrating config from v{current_version} to v{self.CURRENT_VERSION}"
        )

        for from_ver, to_ver, migration_func in self._migrations:
            if self._version_tuple(from_ver) >= self._version_tuple(current_version) and \
               self._version_tuple(to_ver) <= self._version_tuple(self.CURRENT_VERSION):
                logger.debug(f"Applying migration: {from_ver} -> {to_ver}")
                try:
                    config = migration_func(config)
                    config["schema_version"] = to_ver
                except Exception as e:
                    logger.error(
                        f"Migration {from_ver} -> {to_ver} failed: {e}"
                    )
                    raise

        return config

    def _register_builtin_migrations(self) -> None:
        """
        Register built-in migrations for known version transitions.

        Add new migrations here as the schema evolves.
        """

        # Example: Migration from 0.1.0 to 1.0.0
        # This serves as a template for future migrations.
        @self.register_migration("0.1.0", "1.0.0")
        def _migrate_0_1_to_1_0(config: Dict[str, Any]) -> Dict[str, Any]:
            """
            Migrate from schema v0.1.0 to v1.0.0.

            Changes:
            - Renamed 'radar_type' to 'hardware_type' in test_bench.
            - Added 'ptp' section with defaults if missing.
            """
            # Handle renamed field: radar_type -> hardware_type
            test_bench = config.get("test_bench", {})
            if "radar_type" in test_bench and "hardware_type" not in test_bench:
                test_bench["hardware_type"] = test_bench.pop("radar_type")
                logger.debug("Migrated test_bench.radar_type -> hardware_type")

            # Ensure PTP section exists with defaults
            if "ptp" not in config:
                config["ptp"] = {
                    "enabled": False,
                    "master_ip": "0.0.0.0",
                    "domain": 0,
                    "sync_timeout_sec": 30,
                }
                logger.debug("Added default PTP section")

            return config

    @staticmethod
    def _version_tuple(version_str: str) -> Tuple[int, ...]:
        """Convert a semver string to a comparable tuple of ints."""
        try:
            return tuple(int(part) for part in version_str.split("."))
        except (ValueError, AttributeError):
            logger.warning(f"Invalid version string: {version_str}, treating as (0, 0, 0)")
            return (0, 0, 0)

    def get_migration_path(self, from_version: str) -> List[Tuple[str, str]]:
        """
        Get the ordered list of migrations needed from a given version.

        Args:
            from_version: Starting schema version.

        Returns:
            List of (from_version, to_version) tuples.
        """
        path = []
        for from_ver, to_ver, _ in self._migrations:
            if self._version_tuple(from_ver) >= self._version_tuple(from_version) and \
               self._version_tuple(to_ver) <= self._version_tuple(self.CURRENT_VERSION):
                path.append((from_ver, to_ver))
        return path

