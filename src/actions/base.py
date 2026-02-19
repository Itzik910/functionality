"""
Atomic Action Base Module.

Provides the foundational classes and patterns for all atomic actions.
Every radar operation (init, transmit, receive, PSU control, PTP sync)
is encapsulated as an atomic action — a reusable, self-contained function
with standardized input/output and error handling.

Design Reference: Section 2 of design document —
"Test code is built from atomic actions (functions) that represent radar operations."
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional

from loguru import logger


class ActionStatus(Enum):
    """Status of an atomic action execution."""

    SUCCESS = "success"
    FAILURE = "failure"
    SKIPPED = "skipped"
    TIMEOUT = "timeout"
    ERROR = "error"


@dataclass
class ActionResult:
    """
    Result of an atomic action execution.

    Carries the status, return data, timing information,
    and any error details for reporting and debugging.

    Attributes:
        status: Execution status (success, failure, etc.).
        data: Arbitrary return data from the action.
        message: Human-readable result description.
        duration_ms: Execution time in milliseconds.
        error: Exception details if the action failed.
        metadata: Additional key-value metadata for reporting.
    """

    status: ActionStatus = ActionStatus.SUCCESS
    data: Any = None
    message: str = ""
    duration_ms: float = 0.0
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_success(self) -> bool:
        """Check if the action completed successfully."""
        return self.status == ActionStatus.SUCCESS

    @property
    def is_failure(self) -> bool:
        """Check if the action failed."""
        return self.status in (ActionStatus.FAILURE, ActionStatus.ERROR, ActionStatus.TIMEOUT)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the result to a dictionary for reporting."""
        return {
            "status": self.status.value,
            "data": self.data,
            "message": self.message,
            "duration_ms": round(self.duration_ms, 3),
            "error": self.error,
            "metadata": self.metadata,
        }


class AtomicAction(ABC):
    """
    Abstract base class for all atomic actions.

    Provides a standardized execution pattern with:
    - Pre-action validation
    - Timed execution
    - Post-action cleanup
    - Automatic error handling and result packaging

    Subclasses must implement the `_execute` method.

    Example usage::

        class InitRadar(AtomicAction):
            def _execute(self, ip: str, port: int, **kwargs) -> Any:
                # Perform radar initialization
                connection = connect_to_radar(ip, port)
                return {"connection_id": connection.id}

        action = InitRadar(name="init_radar")
        result = action.run(ip="192.168.1.100", port=5000)
        assert result.is_success
    """

    def __init__(self, name: str, timeout_sec: float = 30.0) -> None:
        """
        Initialize the atomic action.

        Args:
            name: Human-readable name of the action (used in logs/reports).
            timeout_sec: Maximum execution time in seconds.
        """
        self.name = name
        self.timeout_sec = timeout_sec

    def run(self, **kwargs: Any) -> ActionResult:
        """
        Execute the action with standardized error handling and timing.

        Args:
            **kwargs: Action-specific parameters.

        Returns:
            ActionResult with status, data, timing, and error details.
        """
        logger.info(f"[Action: {self.name}] Starting with params: {list(kwargs.keys())}")
        start_time = time.perf_counter()

        try:
            # Pre-validation
            self._validate(**kwargs)

            # Execute the action
            data = self._execute(**kwargs)

            elapsed_ms = (time.perf_counter() - start_time) * 1000

            # Check for timeout
            if elapsed_ms > self.timeout_sec * 1000:
                logger.warning(
                    f"[Action: {self.name}] Completed but exceeded timeout "
                    f"({elapsed_ms:.1f}ms > {self.timeout_sec * 1000:.0f}ms)"
                )
                return ActionResult(
                    status=ActionStatus.TIMEOUT,
                    data=data,
                    message=f"Action '{self.name}' exceeded timeout",
                    duration_ms=elapsed_ms,
                )

            logger.info(f"[Action: {self.name}] Completed in {elapsed_ms:.1f}ms")
            return ActionResult(
                status=ActionStatus.SUCCESS,
                data=data,
                message=f"Action '{self.name}' completed successfully",
                duration_ms=elapsed_ms,
            )

        except Exception as e:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            logger.error(f"[Action: {self.name}] Failed: {e}")
            return ActionResult(
                status=ActionStatus.ERROR,
                message=f"Action '{self.name}' failed: {e}",
                duration_ms=elapsed_ms,
                error=str(e),
            )

        finally:
            self._cleanup(**kwargs)

    def _validate(self, **kwargs: Any) -> None:
        """
        Pre-execution validation hook. Override to add checks.

        Raises:
            ValueError: If validation fails.
        """
        pass

    @abstractmethod
    def _execute(self, **kwargs: Any) -> Any:
        """
        Core action logic. Must be implemented by subclasses.

        Args:
            **kwargs: Action-specific parameters.

        Returns:
            Action-specific return data.
        """
        ...

    def _cleanup(self, **kwargs: Any) -> None:
        """Post-execution cleanup hook. Override for resource cleanup."""
        pass

