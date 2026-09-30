"""Execution result data structures for PyMOL execution."""

from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass
class ExecutionResult:
    """Encapsulates outcome, output, and diagnostic error of a PyMOL command."""

    ok: bool
    output: str
    error: str = ""

    def as_json(self) -> str:
        """Serialize result as JSON string."""
        return json.dumps({"ok": self.ok, "output": self.output, "error": self.error})
