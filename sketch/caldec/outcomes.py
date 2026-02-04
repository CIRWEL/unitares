"""
Automatic outcome evaluation from observable signals.

No human labeling needed - evaluate from tests, commands, files, APIs.
"""

from __future__ import annotations
from typing import Dict, List, Optional, Callable
from pathlib import Path

__all__ = ["evaluate", "Evaluator"]


def evaluate(outcomes: Dict) -> Optional[bool]:
    """
    Evaluate correctness from multiple outcome signals.

    Args:
        outcomes: Dict with optional keys:
            - test: {"exit_code": 0} or {"passed": 5, "failed": 0}
            - command: {"exit_code": 0} or {"success": True}
            - file: {"path": "/out.json", "exists": True}
            - api: {"status_code": 200} or {"success": True}

    Returns:
        True if all pass, False if any fail, None if can't evaluate.

    Example:
        result = evaluate({
            "test": {"exit_code": 0},
            "command": {"success": True},
            "file": {"path": "/output.json", "exists": True},
        })
    """
    e = Evaluator()
    signals = []

    if "test" in outcomes:
        sig = e.test(outcomes["test"])
        if sig is not None:
            signals.append(sig)

    if "command" in outcomes:
        sig = e.command(outcomes["command"])
        if sig is not None:
            signals.append(sig)

    if "file" in outcomes:
        f = outcomes["file"]
        sig = e.file(f.get("path", ""), f.get("exists", True))
        if sig is not None:
            signals.append(sig)

    if "api" in outcomes:
        sig = e.api(outcomes["api"])
        if sig is not None:
            signals.append(sig)

    if not signals:
        return None

    return all(signals)  # Conservative: any failure = failure


class Evaluator:
    """
    Evaluate outcomes from observable signals.

    Example:
        e = Evaluator()
        e.test({"passed": 5, "failed": 0})  # True
        e.command({"exit_code": 1})          # False
        e.file("/output.json", exists=True)  # True/False based on existence
    """

    def test(self, result: Dict) -> Optional[bool]:
        """Evaluate test result. Checks exit_code or passed/failed counts."""
        if not result:
            return None
        if "exit_code" in result:
            return result["exit_code"] == 0
        failed = result.get("failed", 0) + result.get("errors", 0)
        passed = result.get("passed", 0)
        if failed > 0:
            return False
        if passed > 0:
            return True
        return None

    def command(self, result: Dict) -> Optional[bool]:
        """Evaluate command result. Checks success flag or exit_code."""
        if not result:
            return None
        if "success" in result:
            return bool(result["success"])
        if "exit_code" in result:
            return result["exit_code"] == 0
        if result.get("error"):
            return False
        return None

    def file(self, path: str, exists: bool = True) -> Optional[bool]:
        """Check if file exists (or doesn't, if exists=False)."""
        if not path:
            return None
        try:
            return Path(path).exists() == exists
        except Exception:
            return None

    def api(self, response: Dict, ok_codes: List[int] = None) -> Optional[bool]:
        """Evaluate API response. Checks success flag or status code."""
        if not response:
            return None
        ok_codes = ok_codes or [200, 201, 204]
        if "success" in response:
            return bool(response["success"])
        status = response.get("status_code") or response.get("status")
        if status is not None:
            return status in ok_codes
        if response.get("error"):
            return False
        return None

    def custom(self, fn: Callable[[], bool]) -> Optional[bool]:
        """Evaluate using a custom function."""
        try:
            return bool(fn())
        except Exception:
            return None
