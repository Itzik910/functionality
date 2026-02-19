"""
Test Mapper Module.

Implements the mapping mechanism between Jira Xray Test IDs and Pytest functions.
Uses Pytest markers (@pytest.mark.xray("TEST-ID")) to establish the link.

Design Reference: Section 3 — "Each Test ID from Jira is mapped to a corresponding
Pytest function (using markers or custom fields)."

The mapper supports:
- Collecting mappings from collected Pytest items via markers.
- Filtering collected tests to only run those in a given Test Set.
- Reverse lookup: finding the Jira Test ID for a given Pytest nodeid.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from loguru import logger

try:
    import pytest
except ImportError:
    pytest = None  # type: ignore[assignment]


@dataclass
class TestMapping:
    """
    Represents a mapping between a Pytest test and a Jira Xray Test ID.

    Attributes:
        test_id: Jira issue key (e.g., "RADAR-101").
        nodeid: Pytest node ID (e.g., "tests/functional/test_radar.py::TestRadar::test_init").
        function_name: Pytest function name (e.g., "test_init").
        class_name: Pytest class name if applicable.
        module_path: Path to the test module.
        markers: List of additional marker names on this test.
    """

    test_id: str
    nodeid: str
    function_name: str = ""
    class_name: str = ""
    module_path: str = ""
    markers: List[str] = field(default_factory=list)


class TestMapper:
    """
    Maps Jira Xray Test IDs to Pytest functions and vice versa.

    The mapper collects @pytest.mark.xray("TEST-ID") markers from
    Pytest items and builds a bidirectional mapping. It can also
    filter a test collection to only include tests from a given Test Set.

    Usage::

        mapper = TestMapper()

        # During collection phase (in conftest.py or plugin)
        mapper.collect_from_items(pytest_items)

        # Get mapping for a specific test ID
        mapping = mapper.get_by_test_id("RADAR-101")

        # Filter items to only run tests in a Test Set
        filtered = mapper.filter_items_by_test_ids(items, ["RADAR-101", "RADAR-102"])
    """

    def __init__(self) -> None:
        """Initialize an empty test mapper."""
        self._id_to_mapping: Dict[str, TestMapping] = {}
        self._nodeid_to_mapping: Dict[str, TestMapping] = {}
        self._unmapped_nodeids: Set[str] = set()

    def collect_from_items(self, items: list) -> None:
        """
        Collect test mappings from Pytest collected items.

        Iterates through all items, looks for @xray markers,
        and builds the mapping registry.

        Args:
            items: List of pytest.Item objects from collection.
        """
        self._id_to_mapping.clear()
        self._nodeid_to_mapping.clear()
        self._unmapped_nodeids.clear()

        for item in items:
            xray_markers = list(item.iter_markers(name="xray"))

            if xray_markers:
                for marker in xray_markers:
                    test_id = marker.args[0] if marker.args else None
                    if test_id:
                        mapping = TestMapping(
                            test_id=test_id,
                            nodeid=item.nodeid,
                            function_name=item.name,
                            class_name=(
                                item.cls.__name__ if hasattr(item, "cls") and item.cls else ""
                            ),
                            module_path=str(item.fspath) if hasattr(item, "fspath") else "",
                            markers=[
                                m.name for m in item.iter_markers()
                                if m.name != "xray"
                            ],
                        )
                        self._id_to_mapping[test_id] = mapping
                        self._nodeid_to_mapping[item.nodeid] = mapping
            else:
                self._unmapped_nodeids.add(item.nodeid)

        logger.info(
            f"TestMapper collected: {len(self._id_to_mapping)} mapped, "
            f"{len(self._unmapped_nodeids)} unmapped tests"
        )

    def get_by_test_id(self, test_id: str) -> Optional[TestMapping]:
        """
        Look up a mapping by Jira Test ID.

        Args:
            test_id: Jira issue key (e.g., "RADAR-101").

        Returns:
            TestMapping if found, None otherwise.
        """
        return self._id_to_mapping.get(test_id)

    def get_by_nodeid(self, nodeid: str) -> Optional[TestMapping]:
        """
        Look up a mapping by Pytest node ID.

        Args:
            nodeid: Pytest node ID string.

        Returns:
            TestMapping if found, None otherwise.
        """
        return self._nodeid_to_mapping.get(nodeid)

    def get_all_mappings(self) -> Dict[str, TestMapping]:
        """Return all test ID -> mapping entries."""
        return dict(self._id_to_mapping)

    def get_all_test_ids(self) -> List[str]:
        """Return all mapped Jira Test IDs."""
        return list(self._id_to_mapping.keys())

    def get_unmapped_nodeids(self) -> Set[str]:
        """Return nodeids of tests without @xray markers."""
        return set(self._unmapped_nodeids)

    def filter_items_by_test_ids(
        self,
        items: list,
        test_ids: List[str],
    ) -> list:
        """
        Filter Pytest items to only include those mapped to the given Test IDs.

        This is used to dynamically filter the test collection based on
        a Test Set fetched from Jira.

        Args:
            items: List of pytest.Item objects.
            test_ids: List of Jira Test IDs to keep.

        Returns:
            Filtered list of pytest.Item objects.
        """
        test_id_set = set(test_ids)
        filtered = []
        skipped = []

        for item in items:
            mapping = self._nodeid_to_mapping.get(item.nodeid)
            if mapping and mapping.test_id in test_id_set:
                filtered.append(item)
            else:
                skipped.append(item.nodeid)

        logger.info(
            f"Test filter: {len(filtered)} selected, "
            f"{len(skipped)} skipped (not in Test Set)"
        )
        if skipped:
            logger.debug(f"Skipped tests: {skipped[:10]}{'...' if len(skipped) > 10 else ''}")

        return filtered

    def generate_mapping_report(self) -> Dict[str, list]:
        """
        Generate a report of all mappings for debugging/documentation.

        Returns:
            Dictionary with 'mapped' and 'unmapped' lists.
        """
        mapped = [
            {
                "test_id": m.test_id,
                "nodeid": m.nodeid,
                "function": m.function_name,
                "class": m.class_name,
            }
            for m in self._id_to_mapping.values()
        ]
        unmapped = list(self._unmapped_nodeids)

        return {
            "mapped": mapped,
            "unmapped": unmapped,
            "total_mapped": len(mapped),
            "total_unmapped": len(unmapped),
        }

    def __len__(self) -> int:
        """Return the number of mapped tests."""
        return len(self._id_to_mapping)

    def __contains__(self, test_id: str) -> bool:
        """Check if a test ID is mapped."""
        return test_id in self._id_to_mapping

