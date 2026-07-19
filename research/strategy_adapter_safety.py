from __future__ import annotations

import ast
from dataclasses import dataclass


ALLOWED_IMPORT_ROOTS = {"math", "statistics", "numpy", "pandas", "research"}
FORBIDDEN_CALLS = {
    "__import__",
    "eval",
    "exec",
    "compile",
    "open",
    "input",
    "breakpoint",
    "submit_order",
    "place_order",
    "cancel_order",
    "replace_order",
    "close_position",
    "unlink",
    "remove",
    "rmdir",
    "rename",
    "replace",
    "write_text",
    "write_bytes",
    "system",
    "popen",
    "run",
    "call",
    "check_output",
    "Popen",
    "import_module",
    "load_module",
}

FORBIDDEN_ATTRIBUTE_ROOTS = {"subprocess", "os", "sys", "importlib", "builtins", "ctypes", "socket"}


@dataclass(frozen=True)
class AdapterSafetyResult:
    safe: bool
    errors: tuple[str, ...]


def _call_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


class _SafetyVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.errors: list[str] = []

    def _check_import(self, module: str) -> None:
        root = module.split(".", 1)[0]
        if root not in ALLOWED_IMPORT_ROOTS:
            self.errors.append(f"forbidden_import.{root}")

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self._check_import(alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.level:
            self.errors.append("forbidden_relative_import")
        elif node.module:
            self._check_import(node.module)
        else:
            self.errors.append("forbidden_import.unknown")
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        root = node.value
        if isinstance(root, ast.Name) and root.id in FORBIDDEN_ATTRIBUTE_ROOTS:
            self.errors.append(f"forbidden_attribute_access.{root.id}")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        name = _call_name(node)
        if name in FORBIDDEN_CALLS:
            self.errors.append(f"forbidden_call.{name}")
        self.generic_visit(node)


def validate_adapter_source(source: str) -> AdapterSafetyResult:
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        line = exc.lineno or 0
        return AdapterSafetyResult(False, (f"syntax_error.line_{line}",))
    visitor = _SafetyVisitor()
    visitor.visit(tree)
    errors = tuple(sorted(set(visitor.errors)))
    return AdapterSafetyResult(safe=not errors, errors=errors)
