"""Core execution engine for sandboxed PyMOL Python scripts."""

from __future__ import annotations

import ast
import contextlib
import io
import math
import statistics
import sys
import time
import traceback
from pathlib import Path
from typing import Any

from pymol import cmd, stored

from .result import ExecutionResult
from .safety import CmdProxy, ExecutionTimedOut, ImportNormalizer, SafetyVisitor
from .scene import capture_viewport, get_scene_summary


class PyMOLExecutor:
    """Safely compiles and executes PyMOL-facing Python code in a constrained environment."""

    def __init__(self) -> None:
        self.locals: dict[str, Any] = {}
        self.safe_cmd = CmdProxy()

    def execute(self, code: str) -> ExecutionResult:
        """Execute a Python code string against the safe PyMOL API with timeout tracing."""
        if len(code) > 20_000:
            return ExecutionResult(False, "", "Code exceeds the 20,000 character limit")
        stream = io.StringIO()
        try:
            tree = ast.parse(code, mode="exec")
            SafetyVisitor().visit(tree)
            tree = ast.fix_missing_locations(ImportNormalizer().visit(tree))
            compiled = compile(tree, "<pymol-agent>", "exec")
            safe_builtins = {
                "abs": abs, "all": all, "any": any, "bool": bool, "dict": dict,
                "enumerate": enumerate, "float": float, "int": int, "len": len,
                "list": list, "max": max, "min": min, "next": next, "print": print,
                "range": range, "repr": repr, "reversed": reversed, "round": round,
                "set": set, "sorted": sorted, "str": str, "sum": sum, "tuple": tuple,
                "zip": zip, "Exception": Exception, "ValueError": ValueError,
                "RuntimeError": RuntimeError, "__import__": __import__,
                "isinstance": isinstance, "issubclass": issubclass,
                "hasattr": hasattr, "getattr": getattr,
                "callable": callable, "iter": iter,
            }
            from ..analysis import (
                analyze_interactions,
                apply_publication_preset,
                compare_conformations,
                load_structures_from_path,
                visualize_plddt,
            )

            namespace = {
                "__builtins__": safe_builtins,
                "cmd": self.safe_cmd,
                "stored": stored,
                "math": math,
                "statistics": statistics,
                "analyze_interactions": analyze_interactions,
                "compare_conformations": compare_conformations,
                "apply_publication_preset": apply_publication_preset,
                "visualize_plddt": visualize_plddt,
                "load_structures_from_path": load_structures_from_path,
                **self.locals,
            }
            deadline = time.monotonic() + 20.0

            def timeout_trace(_frame, _event, _arg):
                if time.monotonic() > deadline:
                    raise ExecutionTimedOut("Python execution exceeded 20 seconds")
                return timeout_trace

            previous_trace = sys.gettrace()
            try:
                sys.settrace(timeout_trace)
                with contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
                    exec(compiled, namespace, namespace)
            finally:
                sys.settrace(previous_trace)
                # Clear selection markers after each batch, including partial
                # failures, without deleting named selections used in later turns.
                with contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
                    cmd.deselect()
            self.locals = {
                key: value for key, value in namespace.items()
                if not key.startswith("__") and key not in {
                    "cmd", "stored", "math", "statistics", "analyze_interactions", "load_structures_from_path"
                }
            }
            output = stream.getvalue().strip()
            # Keep real output distinct from the success flag so silent visual
            # operations can use the agent's guarded direct confirmation.
            return ExecutionResult(True, output)
        except Exception as exc:
            message = "".join(traceback.format_exception_only(type(exc), exc)).strip()
            hint = ""
            if "Invalid selection name" in message:
                hint = (
                    "\n[PyMOL Hint]: Object names starting with digits (e.g. '1abc_...') "
                    "or containing hyphens cannot be used as bare words in selections. "
                    "Use 'model <object_name>' (e.g. 'model 1abc_complex and resi 94') or wrap in parentheses."
                )
            elif "ExecutiveDistance: no atoms selected" in message or "no atoms" in message.lower():
                hint = (
                    "\n[PyMOL Hint]: One or both selections in cmd.distance contained 0 atoms. "
                    "Verify atom/residue identifiers, or wrap cmd.distance in try...except so execution does not crash."
                )
            elif "cmd.load" in message or ("load" in message and "UnsafeCodeError" in message):
                hint = (
                    "\n[PyMOL Hint]: 'cmd.load' is disabled in Python scripts. "
                    "Use the dedicated 'load_local_structures' tool or 'load_structures_from_path(path)' instead."
                )
            elif "invalid model" in message.lower():
                hint = (
                    "\n[PyMOL Hint]: 'invalid model' usually means 'model <name>' was passed inside cmd.align/cmd.super "
                    "(pass bare object name string e.g. cmd.align('obj_a', 'obj_b')), or the object name does not exist. "
                    "For selections, use '(object_name)'."
                )
            elif "AttributeError" in message and "cmd" in message:
                hint = (
                    "\n[PyMOL Hint]: This cmd method does not exist. Use standard PyMOL API calls "
                    "(cmd.select, cmd.show, cmd.color, cmd.orient, cmd.distance, cmd.set, etc.)."
                )
            if hint:
                message = f"{message}{hint}"
            captured = stream.getvalue().strip()
            return ExecutionResult(False, captured, message)

    def scene_summary(self) -> dict[str, Any]:
        """Inspect active PyMOL scene objects and selections."""
        return get_scene_summary(self.safe_cmd)

    def capture_viewport(self) -> tuple[Path, str]:
        """Capture active 3D viewport to a PNG file and base64 URI."""
        return capture_viewport(self.safe_cmd)
