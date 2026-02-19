"""
Xray REST API Client.

Provides a dedicated client for interacting with the Jira Xray REST API:
- Authentication (token-based or basic auth).
- Fetching Test IDs from Test Sets.
- Creating Test Executions.
- Uploading execution results.

Design Reference: Section 3 — "At pipeline start, the system queries the Xray API
to fetch the list of Test IDs from the specified Test Set."
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from loguru import logger

try:
    import requests
except ImportError:
    requests = None  # type: ignore[assignment]


class XrayClientError(Exception):
    """Raised when an Xray API operation fails."""

    def __init__(self, message: str, status_code: Optional[int] = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass
class XrayConfig:
    """Configuration for the Xray API client."""

    base_url: str
    project_key: str
    auth_method: str = "token"  # "token" or "basic"
    api_token: str = ""
    username: str = ""
    password: str = ""
    xray_api_version: str = "v2"
    timeout_sec: int = 30
    verify_ssl: bool = True


class XrayClient:
    """
    Client for the Jira Xray REST API.

    Handles authentication, test set fetching, test execution creation,
    and result uploading. Designed for both Xray Server/DC and Xray Cloud.

    Usage::

        client = XrayClient(
            base_url="https://jira.example.com",
            project_key="RADAR",
            auth_method="token",
            api_token="your-token-here",
        )
        test_ids = client.fetch_test_set("Sanity")
        # Returns: ["RADAR-101", "RADAR-102", "RADAR-103", ...]
    """

    # Xray REST API endpoints (Server/DC)
    ENDPOINTS = {
        "test_set_tests": "/rest/raven/1.0/api/testset/{test_set_key}/test",
        "test_execution": "/rest/raven/1.0/api/testexec",
        "import_results_xray": "/rest/raven/1.0/api/import/execution",
        "import_results_junit": "/rest/raven/1.0/api/import/execution/junit",
        # Xray Cloud endpoints
        "cloud_authenticate": "/api/v2/authenticate",
        "cloud_test_set_tests": "/api/v2/testset/{test_set_key}/tests",
        "cloud_import_results": "/api/v2/import/execution",
    }

    def __init__(
        self,
        base_url: str = "",
        project_key: str = "",
        auth_method: str = "token",
        api_token: str = "",
        username: str = "",
        password: str = "",
        xray_api_version: str = "v2",
        timeout_sec: int = 30,
        verify_ssl: bool = True,
        config: Optional[XrayConfig] = None,
    ) -> None:
        """
        Initialize the Xray client.

        Args:
            base_url: Jira instance base URL.
            project_key: Jira project key (e.g., "RADAR").
            auth_method: Authentication method ("token" or "basic").
            api_token: API token for token-based auth.
            username: Username for basic auth.
            password: Password for basic auth.
            xray_api_version: Xray API version.
            timeout_sec: Request timeout in seconds.
            verify_ssl: Whether to verify SSL certificates.
            config: Optional XrayConfig dataclass (overrides individual params).
        """
        if config:
            self._config = config
        else:
            self._config = XrayConfig(
                base_url=base_url.rstrip("/"),
                project_key=project_key,
                auth_method=auth_method,
                api_token=api_token,
                username=username,
                password=password,
                xray_api_version=xray_api_version,
                timeout_sec=timeout_sec,
                verify_ssl=verify_ssl,
            )

        self._session: Optional[Any] = None
        logger.info(
            f"XrayClient initialized — project={self._config.project_key}, "
            f"url={self._config.base_url}"
        )

    @property
    def is_configured(self) -> bool:
        """Check if the client has minimum configuration to operate."""
        return bool(self._config.base_url and self._config.project_key)

    def _get_session(self) -> Any:
        """
        Get or create an HTTP session with proper authentication headers.

        Returns:
            requests.Session configured with auth.

        Raises:
            XrayClientError: If requests library is not available.
        """
        if requests is None:
            raise XrayClientError(
                "The 'requests' library is required for Xray API integration. "
                "Install with: pip install requests"
            )

        if self._session is None:
            self._session = requests.Session()
            self._session.verify = self._config.verify_ssl
            self._session.headers.update({
                "Content-Type": "application/json",
                "Accept": "application/json",
            })

            if self._config.auth_method == "token":
                self._session.headers["Authorization"] = (
                    f"Bearer {self._config.api_token}"
                )
            elif self._config.auth_method == "basic":
                self._session.auth = (
                    self._config.username,
                    self._config.password,
                )

        return self._session

    def _request(
        self,
        method: str,
        endpoint: str,
        **kwargs: Any,
    ) -> Dict[str, Any] | List[Any]:
        """
        Make an authenticated API request.

        Args:
            method: HTTP method (GET, POST, PUT).
            endpoint: API endpoint path.
            **kwargs: Additional arguments for requests (json, data, params, files).

        Returns:
            Parsed JSON response.

        Raises:
            XrayClientError: If the request fails.
        """
        session = self._get_session()
        url = f"{self._config.base_url}{endpoint}"
        logger.debug(f"Xray API {method} {url}")

        try:
            response = session.request(
                method=method,
                url=url,
                timeout=self._config.timeout_sec,
                **kwargs,
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as e:
            status_code = e.response.status_code if e.response else None
            logger.error(f"Xray API HTTP error: {e} (status={status_code})")
            raise XrayClientError(
                f"Xray API request failed: {e}", status_code=status_code
            ) from e
        except requests.exceptions.ConnectionError as e:
            logger.error(f"Xray API connection error: {e}")
            raise XrayClientError(f"Cannot connect to Jira: {e}") from e
        except requests.exceptions.Timeout as e:
            logger.error(f"Xray API timeout: {e}")
            raise XrayClientError(
                f"Jira API request timed out after {self._config.timeout_sec}s"
            ) from e
        except Exception as e:
            logger.error(f"Xray API unexpected error: {e}")
            raise XrayClientError(f"Unexpected error: {e}") from e

    # ------------------------------------------------------------------
    # Test Set Operations
    # ------------------------------------------------------------------

    def fetch_test_set(self, test_set_key: str) -> List[str]:
        """
        Fetch all Test IDs from a Jira Xray Test Set.

        Args:
            test_set_key: The Jira issue key of the Test Set (e.g., "RADAR-500").

        Returns:
            List of Test ID strings (e.g., ["RADAR-101", "RADAR-102"]).

        Raises:
            XrayClientError: If the API call fails.
        """
        logger.info(f"Fetching tests from Test Set: {test_set_key}")

        endpoint = self.ENDPOINTS["test_set_tests"].format(
            test_set_key=test_set_key
        )
        response = self._request("GET", endpoint)

        if isinstance(response, list):
            test_ids = [test.get("key", "") for test in response if "key" in test]
        elif isinstance(response, dict):
            # Some Xray versions wrap in a dict
            tests = response.get("tests", response.get("issues", []))
            test_ids = [test.get("key", "") for test in tests if "key" in test]
        else:
            test_ids = []

        logger.info(f"Fetched {len(test_ids)} tests from {test_set_key}: {test_ids}")
        return test_ids

    def fetch_test_set_by_name(self, test_set_name: str) -> List[str]:
        """
        Fetch Test IDs by searching for a Test Set by its summary/name.

        This performs a JQL search to find the Test Set issue, then fetches
        its tests. Useful when you know the name (e.g., "Sanity") but not the key.

        Args:
            test_set_name: Human-readable name of the Test Set.

        Returns:
            List of Test ID strings.

        Raises:
            XrayClientError: If the Test Set is not found or API call fails.
        """
        logger.info(f"Searching for Test Set by name: '{test_set_name}'")

        jql = (
            f'project = "{self._config.project_key}" '
            f'AND issuetype = "Test Set" '
            f'AND summary ~ "{test_set_name}"'
        )
        endpoint = "/rest/api/2/search"
        response = self._request("GET", endpoint, params={"jql": jql, "maxResults": 1})

        issues = response.get("issues", []) if isinstance(response, dict) else []
        if not issues:
            raise XrayClientError(
                f"Test Set '{test_set_name}' not found in project "
                f"{self._config.project_key}"
            )

        test_set_key = issues[0]["key"]
        logger.info(f"Found Test Set: {test_set_name} -> {test_set_key}")
        return self.fetch_test_set(test_set_key)

    # ------------------------------------------------------------------
    # Test Execution Operations
    # ------------------------------------------------------------------

    def create_test_execution(
        self,
        summary: str,
        test_ids: List[str],
        description: str = "",
        environment: str = "",
        fix_version: str = "",
    ) -> str:
        """
        Create a new Test Execution issue in Jira.

        Args:
            summary: Summary/title of the Test Execution.
            test_ids: List of Test issue keys to include.
            description: Optional description.
            environment: Optional environment label.
            fix_version: Optional fix version.

        Returns:
            Key of the created Test Execution issue.

        Raises:
            XrayClientError: If creation fails.
        """
        logger.info(f"Creating Test Execution: '{summary}' with {len(test_ids)} tests")

        payload: Dict[str, Any] = {
            "fields": {
                "project": {"key": self._config.project_key},
                "summary": summary,
                "issuetype": {"name": "Test Execution"},
            }
        }
        if description:
            payload["fields"]["description"] = description
        if environment:
            payload["fields"]["environment"] = environment

        endpoint = "/rest/api/2/issue"
        response = self._request("POST", endpoint, json=payload)

        exec_key = response.get("key", "") if isinstance(response, dict) else ""
        logger.info(f"Test Execution created: {exec_key}")

        # Associate tests with the execution
        if exec_key and test_ids:
            assoc_endpoint = f"/rest/raven/1.0/api/testexec/{exec_key}/test"
            self._request("POST", assoc_endpoint, json={"add": test_ids})
            logger.info(f"Associated {len(test_ids)} tests with {exec_key}")

        return exec_key

    def import_execution_results(
        self,
        results_json: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Import test execution results to Xray via JSON format.

        Args:
            results_json: Xray-formatted results dictionary.

        Returns:
            API response with created/updated execution info.

        Raises:
            XrayClientError: If import fails.
        """
        logger.info("Importing execution results to Xray")
        endpoint = self.ENDPOINTS["import_results_xray"]
        response = self._request("POST", endpoint, json=results_json)
        result = response if isinstance(response, dict) else {"response": response}
        logger.info(f"Results imported: {result.get('testExecIssue', {}).get('key', 'N/A')}")
        return result

    def import_junit_results(
        self,
        junit_xml_path: str,
        project_key: Optional[str] = None,
        test_exec_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Import JUnit XML results to Xray.

        Args:
            junit_xml_path: Path to the JUnit XML file.
            project_key: Override project key (defaults to configured).
            test_exec_key: Existing Test Execution to update.

        Returns:
            API response.

        Raises:
            XrayClientError: If import fails.
        """
        logger.info(f"Importing JUnit results from: {junit_xml_path}")

        params: Dict[str, str] = {}
        if project_key or self._config.project_key:
            params["projectKey"] = project_key or self._config.project_key
        if test_exec_key:
            params["testExecKey"] = test_exec_key

        with open(junit_xml_path, "rb") as f:
            endpoint = self.ENDPOINTS["import_results_junit"]
            session = self._get_session()
            url = f"{self._config.base_url}{endpoint}"

            # Override content-type for XML upload
            headers = {"Content-Type": "text/xml"}
            response = session.post(
                url,
                data=f.read(),
                params=params,
                headers=headers,
                timeout=self._config.timeout_sec,
            )
            response.raise_for_status()
            result = response.json()

        logger.info(f"JUnit results imported successfully")
        return result

    def close(self) -> None:
        """Close the HTTP session."""
        if self._session is not None:
            self._session.close()
            self._session = None
            logger.debug("Xray client session closed")

