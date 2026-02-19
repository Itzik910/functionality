"""
Unit Tests for the Jira Xray Integration Module.

Covers:
- XrayClient: configuration, session management (API calls mocked).
- TestMapper: marker collection, filtering, bidirectional lookup.
- ResultReporter: JSON/XML export, statistics, TestResult formatting.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest

from src.jira_client.xray_client import XrayClient, XrayClientError, XrayConfig
from src.jira_client.test_mapper import TestMapper, TestMapping
from src.jira_client.result_reporter import (
    ExecutionReport,
    ResultReporter,
    TestResult,
)


# ---------------------------------------------------------------------------
# XrayClient Tests
# ---------------------------------------------------------------------------


class TestXrayClient:
    """Tests for the XrayClient class."""

    def test_init_with_params(self) -> None:
        """Test client initialization with individual parameters."""
        client = XrayClient(
            base_url="https://jira.example.com",
            project_key="RADAR",
            auth_method="token",
            api_token="test-token",
        )
        assert client.is_configured

    def test_init_with_config(self) -> None:
        """Test client initialization with XrayConfig dataclass."""
        config = XrayConfig(
            base_url="https://jira.example.com",
            project_key="RADAR",
            api_token="test-token",
        )
        client = XrayClient(config=config)
        assert client.is_configured

    def test_not_configured_without_url(self) -> None:
        """Test that client reports not configured when URL is missing."""
        client = XrayClient(project_key="RADAR")
        assert not client.is_configured

    def test_not_configured_without_project(self) -> None:
        """Test that client reports not configured when project key is missing."""
        client = XrayClient(base_url="https://jira.example.com")
        assert not client.is_configured

    def test_base_url_trailing_slash_stripped(self) -> None:
        """Test that trailing slash is stripped from base URL."""
        client = XrayClient(
            base_url="https://jira.example.com/",
            project_key="RADAR",
        )
        assert client._config.base_url == "https://jira.example.com"

    def test_close_session(self) -> None:
        """Test closing the client session."""
        client = XrayClient(
            base_url="https://jira.example.com",
            project_key="RADAR",
        )
        # Session not created yet
        client.close()  # Should not raise

    def test_endpoints_defined(self) -> None:
        """Test that all required API endpoints are defined."""
        assert "test_set_tests" in XrayClient.ENDPOINTS
        assert "test_execution" in XrayClient.ENDPOINTS
        assert "import_results_xray" in XrayClient.ENDPOINTS
        assert "import_results_junit" in XrayClient.ENDPOINTS


# ---------------------------------------------------------------------------
# TestMapper Tests
# ---------------------------------------------------------------------------


class _MockItem:
    """Mock Pytest item for testing the TestMapper."""

    def __init__(
        self,
        nodeid: str,
        name: str,
        xray_ids: Optional[List[str]] = None,
        other_markers: Optional[List[str]] = None,
        cls: Any = None,
        fspath: str = "",
    ) -> None:
        self.nodeid = nodeid
        self.name = name
        self._xray_ids = xray_ids or []
        self._other_markers = other_markers or []
        self.cls = cls
        self.fspath = fspath

    def iter_markers(self, name: Optional[str] = None):
        """Iterate over markers, optionally filtering by name."""
        markers = []

        # Xray markers
        for xray_id in self._xray_ids:
            m = MagicMock()
            m.name = "xray"
            m.args = (xray_id,)
            markers.append(m)

        # Other markers
        for marker_name in self._other_markers:
            m = MagicMock()
            m.name = marker_name
            m.args = ()
            markers.append(m)

        if name is not None:
            return [m for m in markers if m.name == name]
        return markers


class TestTestMapper:
    """Tests for the TestMapper class."""

    def _create_items(self) -> List[_MockItem]:
        """Create a set of mock Pytest items for testing."""
        return [
            _MockItem(
                nodeid="tests/test_radar.py::TestRadar::test_init",
                name="test_init",
                xray_ids=["RADAR-101"],
                other_markers=["functional"],
            ),
            _MockItem(
                nodeid="tests/test_radar.py::TestRadar::test_transmit",
                name="test_transmit",
                xray_ids=["RADAR-102"],
                other_markers=["functional"],
            ),
            _MockItem(
                nodeid="tests/test_psu.py::TestPSU::test_power_on",
                name="test_power_on",
                xray_ids=["RADAR-201"],
                other_markers=["functional"],
            ),
            _MockItem(
                nodeid="tests/test_utils.py::test_helper",
                name="test_helper",
                xray_ids=[],
            ),
        ]

    def test_collect_from_items(self) -> None:
        """Test collecting mappings from Pytest items."""
        mapper = TestMapper()
        items = self._create_items()
        mapper.collect_from_items(items)

        assert len(mapper) == 3  # 3 items with xray markers
        assert "RADAR-101" in mapper
        assert "RADAR-102" in mapper
        assert "RADAR-201" in mapper

    def test_get_by_test_id(self) -> None:
        """Test lookup by Jira Test ID."""
        mapper = TestMapper()
        mapper.collect_from_items(self._create_items())

        mapping = mapper.get_by_test_id("RADAR-101")
        assert mapping is not None
        assert mapping.test_id == "RADAR-101"
        assert mapping.function_name == "test_init"

    def test_get_by_test_id_not_found(self) -> None:
        """Test lookup returns None for unknown Test ID."""
        mapper = TestMapper()
        mapper.collect_from_items(self._create_items())

        assert mapper.get_by_test_id("RADAR-999") is None

    def test_get_by_nodeid(self) -> None:
        """Test lookup by Pytest node ID."""
        mapper = TestMapper()
        mapper.collect_from_items(self._create_items())

        mapping = mapper.get_by_nodeid("tests/test_radar.py::TestRadar::test_init")
        assert mapping is not None
        assert mapping.test_id == "RADAR-101"

    def test_unmapped_tests(self) -> None:
        """Test that unmapped tests are tracked."""
        mapper = TestMapper()
        mapper.collect_from_items(self._create_items())

        unmapped = mapper.get_unmapped_nodeids()
        assert "tests/test_utils.py::test_helper" in unmapped

    def test_get_all_test_ids(self) -> None:
        """Test retrieving all mapped test IDs."""
        mapper = TestMapper()
        mapper.collect_from_items(self._create_items())

        ids = mapper.get_all_test_ids()
        assert set(ids) == {"RADAR-101", "RADAR-102", "RADAR-201"}

    def test_filter_items_by_test_ids(self) -> None:
        """Test filtering items to a subset of test IDs."""
        mapper = TestMapper()
        items = self._create_items()
        mapper.collect_from_items(items)

        filtered = mapper.filter_items_by_test_ids(items, ["RADAR-101", "RADAR-201"])
        assert len(filtered) == 2

        nodeids = [item.nodeid for item in filtered]
        assert "tests/test_radar.py::TestRadar::test_init" in nodeids
        assert "tests/test_psu.py::TestPSU::test_power_on" in nodeids

    def test_filter_items_empty_test_ids(self) -> None:
        """Test filtering with empty test ID list returns nothing."""
        mapper = TestMapper()
        items = self._create_items()
        mapper.collect_from_items(items)

        filtered = mapper.filter_items_by_test_ids(items, [])
        assert len(filtered) == 0

    def test_generate_mapping_report(self) -> None:
        """Test mapping report generation."""
        mapper = TestMapper()
        mapper.collect_from_items(self._create_items())

        report = mapper.generate_mapping_report()
        assert report["total_mapped"] == 3
        assert report["total_unmapped"] == 1
        assert len(report["mapped"]) == 3

    def test_contains(self) -> None:
        """Test __contains__ for test ID lookup."""
        mapper = TestMapper()
        mapper.collect_from_items(self._create_items())

        assert "RADAR-101" in mapper
        assert "RADAR-999" not in mapper


# ---------------------------------------------------------------------------
# TestResult Tests
# ---------------------------------------------------------------------------


class TestTestResult:
    """Tests for the TestResult dataclass."""

    def test_valid_status(self) -> None:
        """Test creating a result with a valid status."""
        result = TestResult(test_id="RADAR-101", status="PASS")
        assert result.status == "PASS"

    def test_status_uppercased(self) -> None:
        """Test that status is automatically uppercased."""
        result = TestResult(test_id="RADAR-101", status="pass")
        assert result.status == "PASS"

    def test_invalid_status_defaults_to_todo(self) -> None:
        """Test that invalid status defaults to TODO."""
        result = TestResult(test_id="RADAR-101", status="INVALID")
        assert result.status == "TODO"

    def test_to_xray_dict_basic(self) -> None:
        """Test basic serialization to Xray format."""
        result = TestResult(test_id="RADAR-101", status="PASS")
        d = result.to_xray_dict()

        assert d["testKey"] == "RADAR-101"
        assert d["status"] == "PASS"

    def test_to_xray_dict_with_error(self) -> None:
        """Test serialization includes error message."""
        result = TestResult(
            test_id="RADAR-101",
            status="FAIL",
            error_message="Timeout exceeded",
        )
        d = result.to_xray_dict()

        assert d["status"] == "FAIL"
        assert "Timeout exceeded" in d["comment"]

    def test_to_xray_dict_with_timestamps(self) -> None:
        """Test serialization includes timestamps."""
        now = datetime.now()
        result = TestResult(
            test_id="RADAR-101",
            status="PASS",
            start_time=now,
            end_time=now,
        )
        d = result.to_xray_dict()

        assert "start" in d
        assert "finish" in d

    def test_to_xray_dict_with_defects(self) -> None:
        """Test serialization includes defect links."""
        result = TestResult(
            test_id="RADAR-101",
            status="FAIL",
            defects=["BUG-42", "BUG-43"],
        )
        d = result.to_xray_dict()
        assert d["defects"] == ["BUG-42", "BUG-43"]


# ---------------------------------------------------------------------------
# ExecutionReport Tests
# ---------------------------------------------------------------------------


class TestExecutionReport:
    """Tests for the ExecutionReport dataclass."""

    def test_add_result(self) -> None:
        """Test adding results to a report."""
        report = ExecutionReport()
        report.add_result(TestResult(test_id="RADAR-101", status="PASS"))
        report.add_result(TestResult(test_id="RADAR-102", status="FAIL"))

        assert report.total_tests == 2

    def test_statistics(self) -> None:
        """Test pass/fail/other statistics."""
        report = ExecutionReport()
        report.add_result(TestResult(test_id="T-1", status="PASS"))
        report.add_result(TestResult(test_id="T-2", status="PASS"))
        report.add_result(TestResult(test_id="T-3", status="FAIL"))
        report.add_result(TestResult(test_id="T-4", status="TODO"))

        assert report.passed == 2
        assert report.failed == 1
        assert report.other == 1
        assert report.pass_rate == 50.0

    def test_pass_rate_empty(self) -> None:
        """Test pass rate with no results."""
        report = ExecutionReport()
        assert report.pass_rate == 0.0


# ---------------------------------------------------------------------------
# ResultReporter Tests
# ---------------------------------------------------------------------------


class TestResultReporter:
    """Tests for the ResultReporter class."""

    def test_add_results(self) -> None:
        """Test adding results to the reporter."""
        reporter = ResultReporter(project_key="RADAR")
        reporter.add_result(TestResult(test_id="RADAR-101", status="PASS"))
        reporter.add_result(TestResult(test_id="RADAR-102", status="FAIL"))

        summary = reporter.get_summary()
        assert summary["total_tests"] == 2
        assert summary["passed"] == 1
        assert summary["failed"] == 1

    def test_to_xray_json(self) -> None:
        """Test Xray JSON format generation."""
        reporter = ResultReporter(project_key="RADAR")
        reporter.set_summary("Sanity Run v2.1")
        reporter.add_result(TestResult(test_id="RADAR-101", status="PASS"))
        reporter.add_result(TestResult(test_id="RADAR-102", status="FAIL",
                                       error_message="Timeout"))

        payload = reporter.to_xray_json()

        assert "tests" in payload
        assert len(payload["tests"]) == 2
        assert payload["tests"][0]["testKey"] == "RADAR-101"
        assert payload["tests"][0]["status"] == "PASS"
        assert payload["tests"][1]["status"] == "FAIL"
        assert "info" in payload
        assert payload["info"]["summary"] == "Sanity Run v2.1"

    def test_export_xray_json(self, tmp_path: Path) -> None:
        """Test exporting Xray JSON to file."""
        reporter = ResultReporter(project_key="RADAR")
        reporter.add_result(TestResult(test_id="RADAR-101", status="PASS"))

        output = tmp_path / "results.json"
        reporter.export_xray_json(str(output))

        assert output.exists()
        data = json.loads(output.read_text(encoding="utf-8"))
        assert len(data["tests"]) == 1
        assert data["tests"][0]["testKey"] == "RADAR-101"

    def test_export_junit_xml(self, tmp_path: Path) -> None:
        """Test exporting JUnit XML to file."""
        reporter = ResultReporter(project_key="RADAR")
        reporter.set_summary("Test Execution")
        reporter.add_result(TestResult(
            test_id="RADAR-101", status="PASS", duration_sec=1.5
        ))
        reporter.add_result(TestResult(
            test_id="RADAR-102", status="FAIL", duration_sec=2.3,
            error_message="Assert failed", traceback="line 42: assert False"
        ))
        reporter.add_result(TestResult(
            test_id="RADAR-103", status="TODO"
        ))

        output = tmp_path / "results.xml"
        reporter.export_junit_xml(str(output))

        assert output.exists()

        tree = ET.parse(str(output))
        root = tree.getroot()
        assert root.tag == "testsuite"
        assert root.get("tests") == "3"
        assert root.get("failures") == "1"

        testcases = root.findall("testcase")
        assert len(testcases) == 3

        # Check PASS test
        assert testcases[0].get("name") == "RADAR-101"
        assert testcases[0].find("failure") is None

        # Check FAIL test
        assert testcases[1].get("name") == "RADAR-102"
        failure = testcases[1].find("failure")
        assert failure is not None
        assert "Assert failed" in failure.get("message", "")

        # Check TODO test (skipped)
        assert testcases[2].get("name") == "RADAR-103"
        assert testcases[2].find("skipped") is not None

    def test_finalize_sets_end_time(self) -> None:
        """Test that finalize sets the end time."""
        reporter = ResultReporter(project_key="RADAR")
        reporter.add_result(TestResult(test_id="RADAR-101", status="PASS"))

        report = reporter.finalize()
        assert report.end_time is not None
        assert report.start_time is not None
        assert report.end_time >= report.start_time

    def test_get_summary(self) -> None:
        """Test summary generation."""
        reporter = ResultReporter(project_key="RADAR", environment="staging")
        reporter.add_result(TestResult(test_id="T-1", status="PASS"))
        reporter.add_result(TestResult(test_id="T-2", status="PASS"))
        reporter.add_result(TestResult(test_id="T-3", status="FAIL"))

        summary = reporter.get_summary()
        assert summary["project_key"] == "RADAR"
        assert summary["environment"] == "staging"
        assert summary["total_tests"] == 3
        assert summary["pass_rate"] == "66.7%"

    def test_export_with_existing_exec_key(self) -> None:
        """Test JSON export with existing Test Execution key."""
        reporter = ResultReporter(project_key="RADAR")
        reporter._report.test_exec_key = "RADAR-EXEC-1"
        reporter.add_result(TestResult(test_id="RADAR-101", status="PASS"))

        payload = reporter.to_xray_json()
        assert payload["testExecutionKey"] == "RADAR-EXEC-1"
        assert "info" not in payload  # No info block when using existing exec

