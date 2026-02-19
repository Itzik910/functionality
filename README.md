# Radar Automated Test Environment

## Project Vision

This project implements a comprehensive **Automated Test Environment** for complex radar systems. It provides an end-to-end framework for testing radar devices (UUT — Unit Under Test) through a Host PC, managing hardware peripherals, orchestrating test execution, and reporting results — all integrated with Jira Xray for full traceability from requirements to test results.

---

## System Topology & Hardware Overview

| Component | Description |
|---|---|
| **Unit Under Test (UUT)** | Radar device that transmits/receives data, performs internal processing, and communicates with a Host PC via Ethernet (ETH). |
| **Host Environment** | PC running a dedicated driver library exposing functional APIs to interact with the radar. |
| **Power Supply Unit (PSU)** | Software-controlled power supply providing power to the radar. |
| **PTP Time Synchronization** | Managed by the Host; the radar requires valid PTP sync to operate. |

### Test Types Supported
- Functional
- Durability
- New feature integration
- Full regression

---

## High-Level Architecture

```
[GitLab CI/CD]
     |
     v
[Resource Manager] <----> [Test Benches Pool]
     |                          |
     v                          v
[Jira Xray API]           [Host PC + UUT + PSU/PTP]
     |
     v
[Reporting & Dashboard]
```

| Block | Role |
|---|---|
| **GitLab CI/CD** | Orchestrates the entire process, including automatic and manual triggers. |
| **Resource Manager** | Handles job queuing, allocation, and monitoring of test benches. |
| **Test Benches Pool** | Physical stations with various hardware, managed by the Resource Manager. |
| **Jira Xray API** | Fetching test sets, mapping test IDs to code, and reporting results. |
| **Reporting** | Generates Allure/HTML reports, error tracebacks, log attachments, and dashboards. |

---

## Technology Stack

- **Language:** Python
- **Test Framework:** Pytest
- **Reporting:** Allure, HTML
- **Test Management:** Jira Xray REST API
- **CI/CD:** GitLab CI/CD Pipelines
- **Configuration:** JSON / YAML

---

## Codebase & Git Strategy

### Test Code Repository
- Modular, generic repository based on Pytest.
- Test code is built from **atomic "actions"** (functions) that represent radar operations.
- Maintained in sync with requirements documentation.

### Embedded Code Repository
- Contains the radar's embedded code.
- Dedicated pipelines for daily (nightly) and official (bi-weekly) builds.

### Configuration & Limits Repository
- Stores configuration and threshold files.
- Full versioning support for backward compatibility with customers using older versions.

---

## Jira Xray Integration

### Test Targeting
- **Jira as Source of Truth:** Requirements are covered by Test Templates in Xray.
- **Test Sets:** Organized into sets (e.g., "Sanity", "Regression_v2.1", "Customer_X_Acceptance").
- **Test Fetching:** At pipeline start, the system queries the Xray API to fetch Test IDs from the specified Test Set.
- **Mapping:** Each Test ID is mapped to a corresponding Pytest function (using markers or custom fields).

### Result Reporting
- After execution, the pipeline sends a results file (JSON/XML) back to Xray.
- Automatically creates a Test Execution issue, updates pass/fail status, and attaches detailed reports.

---

## Resource Management & Job Allocation

- **Job Queue:** Centralized queue with allocation to available test benches based on required hardware type.
- **Job Parameters:** Build version, hardware type, configuration file, threshold file.
- **Triggering:** Automatic (post-build) and manual (authorized users).

---

## Output & Reporting

- Reports separated by test type and hardware type.
- Deep error tracebacks for quick debugging (latency, data processing failures).
- API logs and PSU/PTP data attached to each failure for comprehensive analysis.

---

## Key Design Principles

1. **Modularity & Flexibility** — Test code decoupled from embedded code; atomic actions for reusable logic; external configuration management.
2. **Bidirectional Jira Xray Integration** — Dynamic test set fetching and automated result reporting.
3. **Smart Resource Management** — Centralized queue, scalable to additional hardware/test benches.
4. **Comprehensive Reporting** — Allure/HTML reports, tracebacks, and log attachments for every run.

---

## Example Workflow

1. **Trigger** — Automatic (post-build) or manual (user-initiated) trigger in GitLab.
2. **Test Set Fetch** — Fetch the relevant Test Set from Jira Xray via API.
3. **Test Mapping** — Map Test IDs to Pytest functions.
4. **Resource Allocation** — Resource Manager assigns the job to an available test bench.
5. **Test Execution** — Tests run with the specified configuration and thresholds.
6. **Result Collection** — Gather results, logs, and tracebacks.
7. **Reporting** — Send results to Jira Xray, generate Allure/HTML reports, update dashboards.

---

## Project Structure (Planned)

```
functionality/
├── src/                  # Core logic (Resource Manager, Jira Client, etc.)
├── tests/                # Pytest-based test suites and Atomic Actions
├── config/               # Thresholds and hardware configuration (JSON/YAML)
├── scripts/              # CI/CD and utility scripts
├── requirements.txt      # Python dependencies
├── PROJECT_HISTORY.md    # Change log — source of truth
└── README.md             # This file
```

---

## References & Resources

- [Xray Test Management REST API Documentation](https://docs.getxray.app/display/XRAY/REST+API)
- [Pytest + Allure Integration Guide](https://docs.qameta.io/allure/#_pytest)
- [GitLab CI/CD Pipelines Documentation](https://docs.gitlab.com/ee/ci/pipelines/)

