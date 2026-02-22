"""
Firmware Version Manager — downloads and manages radar firmware.

Wraps the GitLab API to download nightly and release firmware versions,
then uses the radar driver to flash them. Supports BSR32/BSRC (DR64) and
HRR (MBAG) projects.

Reference: git_version.py (gitlab_tools class)
"""

from __future__ import annotations

import os
import tarfile
import zipfile
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests
from loguru import logger


@dataclass
class FWVersion:
    """Firmware version metadata."""
    tag_name: str = ""
    filename: str = ""
    download_url: str = ""
    created_at: str = ""
    is_nightly: bool = False
    local_path: str = ""


class FirmwareManager:
    """
    Manages firmware downloading from GitLab and flashing to radars.

    Supports two version types:
    - nightly: Latest CI build, fetched from package registry
    - release: Tagged release versions

    The download location defaults to a local cache directory.
    """

    # GitLab endpoints
    GITLAB_URL = "https://gitlab.radar.iil.intel.com"
    PROJECT_ID = "2"  # Default project ID for BSR/HRR firmware
    NIGHTLY_PACKAGE_ID = "326"  # Package ID for nightly builds

    def __init__(
        self,
        gitlab_token: str,
        download_dir: str = "",
        simulate: bool = False,
    ) -> None:
        """
        Initialize FirmwareManager.

        Args:
            gitlab_token: GitLab private access token.
            download_dir: Local directory for firmware cache.
            simulate: If True, skip actual downloads and flash operations.
        """
        self.gitlab_token = gitlab_token
        self.download_dir = download_dir or os.path.join(
            os.path.expanduser("~"), ".radar_fw_cache"
        )
        self._simulate = simulate
        self.headers = {"Private-Token": gitlab_token}

        os.makedirs(self.download_dir, exist_ok=True)
        logger.info(f"FirmwareManager initialized — cache={self.download_dir}, simulate={simulate}")

    # --- Release versions ---

    def get_release_versions(self) -> List[str]:
        """Fetch all available release version tags from GitLab."""
        if self._simulate:
            return ["v5.4.1", "v5.4.0", "v5.3.2", "v5.3.1", "v5.3.0"]

        url = f"{self.GITLAB_URL}/api/v4/projects/{self.PROJECT_ID}/releases"
        try:
            response = requests.get(url, headers=self.headers, verify=False, timeout=30)
            response.raise_for_status()
            releases = response.json()
            versions = [r["tag_name"] for r in releases]
            logger.info(f"FirmwareManager: Found {len(versions)} release versions")
            return versions
        except requests.RequestException as e:
            logger.error(f"FirmwareManager: Error fetching releases: {e}")
            return []

    def download_release(self, version: str, extract: bool = True) -> Optional[FWVersion]:
        """
        Download a specific release version from GitLab.

        Args:
            version: Tag name (e.g., "v5.4.1").
            extract: If True, extract the archive after download.

        Returns:
            FWVersion with local_path set, or None on failure.
        """
        if self._simulate:
            local_path = os.path.join(self.download_dir, f"fw_updater_{version}")
            logger.info(f"FirmwareManager [MOCK]: Release {version} -> {local_path}")
            return FWVersion(
                tag_name=version,
                filename=f"fw_updater_package_{version}.tar.gz",
                is_nightly=False,
                local_path=local_path,
            )

        url = f"{self.GITLAB_URL}/api/v4/projects/{self.PROJECT_ID}/releases?tag_name={version}"
        try:
            response = requests.get(url, headers=self.headers, verify=False, timeout=30)
            response.raise_for_status()
            releases = response.json()

            if not releases:
                logger.error(f"FirmwareManager: Release '{version}' not found")
                return None

            # Find the matching release
            matching = [r for r in releases if version in r["name"]]
            if len(matching) != 1:
                logger.error(f"FirmwareManager: Expected 1 match for '{version}', got {len(matching)}")
                return None

            release = matching[0]
            assets = release.get("assets", {})
            links = assets.get("links", [])

            fw_links = [l for l in links if l.get("name") == "fw_updater_package"]
            if not fw_links:
                logger.error(f"FirmwareManager: No fw_updater_package asset in release '{version}'")
                return None

            download_url = fw_links[0]["direct_asset_url"]
            filename = download_url.split("/")[-1]
            local_file = os.path.join(self.download_dir, filename)

            if not os.path.exists(local_file):
                local_file = self._download_file(download_url, local_file)
                if local_file is None:
                    return None

            extracted_path = local_file
            if extract:
                extracted_path = self._extract_archive(local_file)

            return FWVersion(
                tag_name=version,
                filename=filename,
                download_url=download_url,
                is_nightly=False,
                local_path=extracted_path,
            )

        except requests.RequestException as e:
            logger.error(f"FirmwareManager: Error downloading release '{version}': {e}")
            return None

    # --- Nightly versions ---

    def download_latest_nightly(self, extract: bool = True) -> Optional[FWVersion]:
        """
        Download the latest nightly firmware build from GitLab packages.

        Returns:
            FWVersion with local_path set, or None on failure.
        """
        if self._simulate:
            local_path = os.path.join(self.download_dir, "fw_updater_nightly_latest")
            logger.info(f"FirmwareManager [MOCK]: Latest nightly -> {local_path}")
            return FWVersion(
                tag_name="nightly-latest",
                filename="fw_updater_nightly.tar.gz",
                is_nightly=True,
                local_path=local_path,
            )

        nightly_prefix = (
            f"{self.GITLAB_URL}/api/v4/projects/{self.PROJECT_ID}"
            f"/packages/generic/fw_updater_package/nightly/"
        )
        packages_url = (
            f"{self.GITLAB_URL}/api/v4/projects/{self.PROJECT_ID}"
            f"/packages/{self.NIGHTLY_PACKAGE_ID}/package_files"
        )

        try:
            # Fetch all package files (paginated)
            all_files: List[Dict[str, Any]] = []
            page = 1
            while True:
                response = requests.get(
                    packages_url,
                    headers=self.headers,
                    params={"page": page},
                    verify=False,
                    timeout=30,
                )
                if response.status_code != 200:
                    logger.error(f"FirmwareManager: Failed to fetch packages: {response.status_code}")
                    return None
                data = response.json()
                if not data:
                    break
                all_files.extend(data)
                page += 1

            if not all_files:
                logger.error("FirmwareManager: No nightly packages found")
                return None

            # Find the latest by creation date
            parsed_dates = [
                datetime.fromisoformat(f["created_at"]) for f in all_files
            ]
            latest_idx = parsed_dates.index(max(parsed_dates))
            latest_file = all_files[latest_idx]

            download_url = nightly_prefix + latest_file["file_name"]
            filename = latest_file["file_name"]
            local_file = os.path.join(self.download_dir, filename)

            if not os.path.exists(local_file):
                local_file = self._download_file(download_url, local_file)
                if local_file is None:
                    return None

            extracted_path = local_file
            if extract:
                extracted_path = self._extract_archive(local_file)

            return FWVersion(
                tag_name="nightly-latest",
                filename=filename,
                download_url=download_url,
                created_at=latest_file["created_at"],
                is_nightly=True,
                local_path=extracted_path,
            )

        except Exception as e:
            logger.error(f"FirmwareManager: Error downloading nightly: {e}")
            return None

    # --- Convenience ---

    def download_for_cycle(
        self, cycle_type: str, version: Optional[str] = None
    ) -> Optional[FWVersion]:
        """
        Download firmware appropriate for the test cycle type.

        Args:
            cycle_type: One of "nightly", "regression", "milestone".
            version: Specific version tag (for milestone/regression).

        Returns:
            FWVersion or None on failure.
        """
        if cycle_type == "nightly":
            return self.download_latest_nightly()
        elif cycle_type in ("regression", "milestone"):
            if version:
                return self.download_release(version)
            else:
                # For regression without a specific version, get latest nightly
                logger.warning(
                    f"FirmwareManager: No version specified for '{cycle_type}' cycle, "
                    "using latest nightly"
                )
                return self.download_latest_nightly()
        else:
            logger.error(f"FirmwareManager: Unknown cycle type '{cycle_type}'")
            return None

    # --- Internal helpers ---

    def _download_file(self, url: str, local_path: str) -> Optional[str]:
        """Download a file from URL to local path."""
        try:
            response = requests.get(
                url, headers=self.headers, stream=True, verify=False, timeout=120
            )
            response.raise_for_status()

            content_length = response.headers.get("content-length", "0")
            if content_length == "0":
                logger.error(f"FirmwareManager: Empty file at {url}")
                return None

            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            with open(local_path, "wb") as f:
                for chunk in response.iter_content(8192):
                    if chunk:
                        f.write(chunk)

            logger.info(f"FirmwareManager: Downloaded {local_path}")
            return local_path

        except requests.RequestException as e:
            logger.error(f"FirmwareManager: Download error: {e}")
            return None

    def _extract_archive(self, filepath: str) -> str:
        """Extract a compressed archive and return the extracted path."""
        extract_dir = filepath.rsplit(".", 1)[0]  # Remove extension
        if filepath.endswith(".tar.gz"):
            extract_dir = filepath[:-7]
        elif filepath.endswith(".tar.bz2"):
            extract_dir = filepath[:-8]

        if os.path.exists(extract_dir):
            logger.debug(f"FirmwareManager: Already extracted: {extract_dir}")
            return extract_dir

        try:
            if filepath.endswith(".zip"):
                with zipfile.ZipFile(filepath, "r") as zf:
                    zf.extractall(extract_dir)
            elif filepath.endswith(".tar.gz"):
                with tarfile.open(filepath, "r:gz") as tf:
                    tf.extractall(extract_dir)
            elif filepath.endswith(".tar.bz2"):
                with tarfile.open(filepath, "r:bz2") as tf:
                    tf.extractall(extract_dir)
            elif filepath.endswith(".tar"):
                with tarfile.open(filepath, "r") as tf:
                    tf.extractall(extract_dir)
            else:
                logger.warning(f"FirmwareManager: Unknown archive format: {filepath}")
                return filepath

            logger.info(f"FirmwareManager: Extracted to {extract_dir}")
            return extract_dir

        except Exception as e:
            logger.error(f"FirmwareManager: Extraction error: {e}")
            return filepath

