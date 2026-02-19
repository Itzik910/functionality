"""
Jira Xray Client Module.

Provides integration with the Jira Xray REST API for:
- Fetching Test IDs from Test Sets.
- Mapping Test IDs to Pytest functions.
- Reporting test execution results (JSON/XML).
- Creating Test Execution issues and attaching reports.
"""

from src.jira_client.xray_client import XrayClient, XrayClientError
from src.jira_client.test_mapper import TestMapper, TestMapping
from src.jira_client.result_reporter import ResultReporter, TestResult, ExecutionReport

__all__ = [
    "XrayClient",
    "XrayClientError",
    "TestMapper",
    "TestMapping",
    "ResultReporter",
    "TestResult",
    "ExecutionReport",
]
