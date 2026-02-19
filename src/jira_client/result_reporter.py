"""
Result Reporter Module.

Handles formatting and sending test execution results to Jira Xray.
Supports both Xray JSON format and JUnit XML format.

Design Reference: Section 3 — "After execution, the pipeline sends a results
file (JSON/XML) back to Xray. The integration automatically creates a Test
Execution issue, updates the pass/fail status for each template, and attaches
a detailed report (Allure/HTML)."
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger


@dataclass
class TestResult:
    """
    Result of a single test execution for Xray reporting.

    Attributes:
        test_id: Jira Test issue key (e.g., "RADAR-101").
        status: Result status ("PASS", "FAIL", "TODO", "EXECUTING", "ABORTED").
        comment: Optional result comment.
        duration_sec: Test execution duration in seconds.
        evidence: List of file paths to attach as evidence.
        defects: List of defect issue keys linked to this failure.
        start_time: When the test started.
        end_time: When the test finished.
        error_message: Error message if the test failed.
        traceback: Full error traceback if available.
    """

    test_id: str
    status: str = "TODO"
    comment: str = ""
    duration_sec: float = 0.0
    evidence: List[str] = field(default_factory=list)
    defects: List[str] = field(default_factory=list)
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    error_message: str = ""
    traceback: str = ""

    # Xray-compatible status values
    VALID_STATUSES = {"PASS", "FAIL", "TODO", "EXECUTING", "ABORTED"}

    def __post_init__(self) -> None:
        """Validate the status value."""
        self.status = self.status.upper()
        if self.status not in self.VALID_STATUSES:
            logger.warning(
                f"Invalid test result status '{self.status}' for {self.test_id}, "
                f"defaulting to 'TODO'. Valid: {self.VALID_STATUSES}"
            )
            self.status = "TODO"

    def to_xray_dict(self) -> Dict[str, Any]:
        """Convert to Xray JSON format for a single test."""
        result: Dict[str, Any] = {
            "testKey": self.test_id,
            "status": self.status,
        }
        if self.comment:
            result["comment"] = self.comment
        if self.start_time:
            result["start"] = self.start_time.isoformat()
        if self.end_time:
            result["finish"] = self.end_time.isoformat()
        if self.defects:
            result["defects"] = self.defects
        if self.error_message:
            result["comment"] = (
                f"{self.comment}\n\nError: {self.error_message}" if self.comment
                else f"Error: {self.error_message}"
            )
        if self.evidence:
            result["evidences"] = [
                {"filename": Path(e).name, "data": "(attached)"}
                for e in self.evidence
            ]
        return result


@dataclass
class ExecutionReport:
    """
    Complete test execution report for Xray.

    Wraps multiple TestResult objects into a full execution report
    that can be serialized to JSON or XML for Xray import.

    Attributes:
        test_exec_key: Existing Test Execution key to update (optional).
        summary: Summary for a new Test Execution issue.
        description: Description for the execution.
        project_key: Jira project key.
        environment: Test environment label.
        fix_version: Fix version for the execution.
        results: List of individual test results.
        start_time: When the execution started.
        end_time: When the execution finished.
    """

    test_exec_key: str = ""
    summary: str = ""
    description: str = ""
    project_key: str = ""
    environment: str = ""
    fix_version: str = ""
    results: List[TestResult] = field(default_factory=list)
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None

    def add_result(self, result: TestResult) -> None:
        """Add a test result to the execution report."""
        self.results.append(result)

    @property
    def total_tests(self) -> int:
        """Total number of test results."""
        return len(self.results)

    @property
    def passed(self) -> int:
        """Number of passed tests."""
        return sum(1 for r in self.results if r.status == "PASS")

    @property
    def failed(self) -> int:
        """Number of failed tests."""
        return sum(1 for r in self.results if r.status == "FAIL")

    @property
    def other(self) -> int:
        """Number of tests with other statuses."""
        return self.total_tests - self.passed - self.failed

    @property
    def pass_rate(self) -> float:
        """Pass rate as a percentage."""
        if self.total_tests == 0:
            return 0.0
        return (self.passed / self.total_tests) * 100


class ResultReporter:
    """
    Formats and exports test results for Jira Xray.

    Supports:
    - Xray JSON format (native import).
    - JUnit XML format (widely compatible).
    - Summary statistics generation.

    Usage::

        reporter = ResultReporter(project_key="RADAR")

        # Add results from test execution
        reporter.add_result(TestResult(test_id="RADAR-101", status="PASS"))
        reporter.add_result(TestResult(test_id="RADAR-102", status="FAIL",
                                        error_message="Timeout exceeded"))

        # Export to Xray JSON
        reporter.export_xray_json("results.json")

        # Or export to JUnit XML
        reporter.export_junit_xml("results.xml")
    """

    def __init__(
        self,
        project_key: str = "",
        environment: str = "",
        fix_version: str = "",
    ) -> None:
        """
        Initialize the result reporter.

        Args:
            project_key: Jira project key.
            environment: Test environment label.
            fix_version: Fix version label.
        """
        self.project_key = project_key
        self.environment = environment
        self.fix_version = fix_version
        self._report = ExecutionReport(
            project_key=project_key,
            environment=environment,
            fix_version=fix_version,
            start_time=datetime.now(),
        )
        logger.info(f"ResultReporter initialized — project={project_key}")

    def add_result(self, result: TestResult) -> None:
        """Add a test result to the report."""
        self._report.add_result(result)
        logger.debug(f"Result added: {result.test_id} -> {result.status}")

    def set_summary(self, summary: str) -> None:
        """Set the execution summary."""
        self._report.summary = summary

    def set_description(self, description: str) -> None:
        """Set the execution description."""
        self._report.description = description

    def finalize(self) -> ExecutionReport:
        """
        Finalize the report, setting the end time.

        Returns:
            The completed ExecutionReport.
        """
        self._report.end_time = datetime.now()
        logger.info(
            f"Report finalized: {self._report.total_tests} tests, "
            f"{self._report.passed} passed, {self._report.failed} failed, "
            f"pass rate: {self._report.pass_rate:.1f}%"
        )
        return self._report

    def to_xray_json(self) -> Dict[str, Any]:
        """
        Convert the report to Xray JSON import format.

        Returns:
            Dictionary in Xray JSON import format.
        """
        report = self._report
        payload: Dict[str, Any] = {
            "tests": [r.to_xray_dict() for r in report.results],
        }

        # Test Execution info
        if report.test_exec_key:
            payload["testExecutionKey"] = report.test_exec_key
        else:
            info: Dict[str, Any] = {}
            if report.summary:
                info["summary"] = report.summary
            if report.description:
                info["description"] = report.description
            if report.project_key:
                info["project"] = report.project_key
            if report.start_time:
                info["startDate"] = report.start_time.isoformat()
            if report.end_time:
                info["finishDate"] = report.end_time.isoformat()
            if info:
                payload["info"] = info

        return payload

    def export_xray_json(self, output_path: str) -> Path:
        """
        Export the report as Xray JSON format file.

        Args:
            output_path: Path to write the JSON file.

        Returns:
            Path to the written file.
        """
        path = Path(output_path)
        payload = self.to_xray_json()
        path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        logger.info(f"Xray JSON report exported to: {path}")
        return path

    def export_junit_xml(self, output_path: str) -> Path:
        """
        Export the report as JUnit XML format file.

        This format is widely compatible with CI/CD tools and
        can be imported by Xray via the JUnit endpoint.

        Args:
            output_path: Path to write the XML file.

        Returns:
            Path to the written file.
        """
        report = self._report
        path = Path(output_path)

        # Build JUnit XML
        testsuite = ET.Element("testsuite")
        testsuite.set("name", report.summary or f"{self.project_key} Test Execution")
        testsuite.set("tests", str(report.total_tests))
        testsuite.set("failures", str(report.failed))
        testsuite.set("errors", "0")
        testsuite.set("time", str(sum(r.duration_sec for r in report.results)))

        if report.start_time:
            testsuite.set("timestamp", report.start_time.isoformat())

        for result in report.results:
            testcase = ET.SubElement(testsuite, "testcase")
            testcase.set("name", result.test_id)
            testcase.set("classname", f"{self.project_key}.{result.test_id}")
            testcase.set("time", str(result.duration_sec))

            if result.status == "FAIL":
                failure = ET.SubElement(testcase, "failure")
                failure.set("message", result.error_message or "Test failed")
                if result.traceback:
                    failure.text = result.traceback

            elif result.status == "ABORTED":
                error = ET.SubElement(testcase, "error")
                error.set("message", result.error_message or "Test aborted")

            elif result.status == "TODO":
                skipped = ET.SubElement(testcase, "skipped")
                skipped.set("message", result.comment or "Not executed")

            # Add Xray test ID as a property
            properties = ET.SubElement(testcase, "properties")
            prop = ET.SubElement(properties, "property")
            prop.set("name", "test_key")
            prop.set("value", result.test_id)

        # Write XML
        tree = ET.ElementTree(testsuite)
        ET.indent(tree, space="  ")
        tree.write(str(path), encoding="unicode", xml_declaration=True)
        logger.info(f"JUnit XML report exported to: {path}")
        return path

    def get_summary(self) -> Dict[str, Any]:
        """
        Get a summary of the execution report.

        Returns:
            Dictionary with execution statistics.
        """
        report = self._report
        return {
            "project_key": self.project_key,
            "environment": self.environment,
            "total_tests": report.total_tests,
            "passed": report.passed,
            "failed": report.failed,
            "other": report.other,
            "pass_rate": f"{report.pass_rate:.1f}%",
            "start_time": str(report.start_time) if report.start_time else None,
            "end_time": str(report.end_time) if report.end_time else None,
        }

