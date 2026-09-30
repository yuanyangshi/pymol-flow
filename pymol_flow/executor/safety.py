"""AST safety inspection and API proxy sandboxing for PyMOL execution."""

from __future__ import annotations

import ast
from typing import Any

from pymol import cmd

from ..config import DOWNLOAD_DIR, ensure_app_dirs


class UnsafeCodeError(ValueError):
    """Raised when Python code attempts forbidden imports, calls, or attributes."""
    pass


class ExecutionTimedOut(TimeoutError):
    """Raised when execution duration exceeds the maximum execution deadline."""
    pass


class SafetyVisitor(ast.NodeVisitor):
    """Block OS access while leaving the PyMOL API broadly available."""

    ALLOWED_IMPORTS = {"pymol", "math", "statistics", "collections", "itertools"}
    BLOCKED_CALLS = {"open", "eval", "exec", "compile", "input", "__import__"}
    # These pymol.cmd entry points can escape into files, the network, or the
    # PyMOL command language (which itself exposes OS commands). File loading is
    # instead handled by the user-facing, extension-checked file picker.
    BLOCKED_CMD_METHODS = {
        "cd", "cls", "do", "exit", "load", "log", "mpng", "png", "pwd",
        "quit", "reinitialize", "run", "save", "system",
    }

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            root = alias.name.split(".", 1)[0]
            if root == "pymol" or root not in self.ALLOWED_IMPORTS:
                raise UnsafeCodeError(f"Import not allowed: {alias.name}")

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if not node.module or node.module.split(".", 1)[0] not in self.ALLOWED_IMPORTS:
            raise UnsafeCodeError(f"Import not allowed: {node.module}")
        if node.module == "pymol" and any(alias.name not in {"cmd", "stored"} for alias in node.names):
            raise UnsafeCodeError("Only cmd and stored may be imported from pymol")

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr.startswith("__"):
            raise UnsafeCodeError("Dunder attribute access is not allowed")
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if node.id.startswith("__") or node.id in self.BLOCKED_CALLS:
            raise UnsafeCodeError(f"Call not allowed: {node.id}")

    def visit_Call(self, node: ast.Call) -> None:
        function = node.func
        if (
            isinstance(function, ast.Attribute)
            and isinstance(function.value, ast.Name)
            and function.value.id == "cmd"
            and function.attr in self.BLOCKED_CMD_METHODS
        ):
            raise UnsafeCodeError(f"PyMOL method not available to the model: cmd.{function.attr}")
        self.generic_visit(node)


class ImportNormalizer(ast.NodeTransformer):
    """Make `from pymol import cmd` refer to the constrained live proxy."""

    def visit_ImportFrom(self, node: ast.ImportFrom) -> Any:
        if node.module != "pymol":
            return node
        replacement = []
        stored_aliases = [alias for alias in node.names if alias.name == "stored"]
        if stored_aliases:
            replacement.append(ast.ImportFrom(module="pymol", names=stored_aliases, level=0))
        for alias in node.names:
            if alias.name == "cmd" and alias.asname and alias.asname != "cmd":
                replacement.append(
                    ast.Assign(targets=[ast.Name(id=alias.asname, ctx=ast.Store())], value=ast.Name(id="cmd", ctx=ast.Load()))
                )
        return replacement or ast.Pass()


class CmdProxy:
    """Expose the real API while denying its filesystem/network escape hatches."""

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_") or name in SafetyVisitor.BLOCKED_CMD_METHODS:
            raise UnsafeCodeError(f"PyMOL method not available to the model: cmd.{name}")
        if name == "fetch":
            return self._safe_fetch
        if name == "delete":
            return self._safe_delete
        if name == "remove":
            return self._safe_remove
        return getattr(cmd, name)

    @staticmethod
    def _safe_delete(name: str = "", *args: Any, **kwargs: Any) -> Any:
        clean = str(name).strip().lower()
        if clean in {"all", "*"} or clean.startswith("all ") or clean.endswith(" all"):
            raise UnsafeCodeError(
                "Destructive batch deletion ('cmd.delete(\"all\")') is blocked for safety. "
                "Specify explicit object names to delete."
            )
        return cmd.delete(name, *args, **kwargs)

    @staticmethod
    def _safe_remove(selection: str = "", *args: Any, **kwargs: Any) -> Any:
        clean = str(selection).strip().lower()
        if clean in {"all", "*"} or clean == "(all)":
            raise UnsafeCodeError(
                "Destructive atom removal ('cmd.remove(\"all\")') is blocked for safety. "
                "Specify explicit selections or residue numbers."
            )
        return cmd.remove(selection, *args, **kwargs)

    @staticmethod
    def _safe_fetch(*args: Any, **kwargs: Any) -> Any:
        """Fetch public structure IDs into the private application directory."""
        from . import DOWNLOAD_DIR, ensure_app_dirs

        if len(args) > 9:
            raise UnsafeCodeError("cmd.fetch path/file arguments are managed by the application")
        ensure_app_dirs()
        positional = list(args)
        if len(positional) == 9:
            positional[8] = 0
            kwargs.pop("async_", None)
            kwargs.pop("async", None)
        else:
            kwargs.pop("async", None)
            kwargs["async_"] = 0
        kwargs.pop("file", None)
        kwargs["path"] = str(DOWNLOAD_DIR)
        return cmd.fetch(*positional, **kwargs)
