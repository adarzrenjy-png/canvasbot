"""Static checks on part code before it is allowed to run.

Generated code runs in a separate, short-lived process (see runner.py) with a
timeout. Before that, this validator rejects anything outside a small allowlist:
only `build123d` and `math` may be imported, no file, process, or network access,
no reflection through underscore attributes, and none of build123d's own
import/export helpers (the runner does all file output itself).

The `if __name__ == "__main__":` block is exempt: it exists so an exported .py
runs standalone, and the runner strips it before executing anything.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass

ALLOWED_MODULES = frozenset({"build123d", "math"})
# `import build123d` would expose its submodules (and through them `os`), so only
# `from build123d import ...` is allowed; the runner also limits it to public names.
PLAIN_IMPORTS = frozenset({"math"})

FORBIDDEN_NAMES = frozenset(
    {
        "__import__",
        "breakpoint",
        "compile",
        "delattr",
        "dir",
        "eval",
        "exec",
        "exit",
        "getattr",
        "globals",
        "hasattr",
        "help",
        "input",
        "locals",
        "memoryview",
        "open",
        "quit",
        "setattr",
        "vars",
        # build123d classes that read or write files
        "Export2D",
        "ExportDXF",
        "ExportSVG",
        "Mesher",
    }
)
FORBIDDEN_PREFIXES = ("import_", "export_")


@dataclass(frozen=True)
class Violation:
    line: int
    message: str

    def __str__(self) -> str:
        return f"line {self.line}: {self.message}"


def is_main_guard(node: ast.stmt) -> bool:
    if not isinstance(node, ast.If):
        return False
    test = node.test
    return (
        isinstance(test, ast.Compare)
        and isinstance(test.left, ast.Name)
        and test.left.id == "__name__"
        and len(test.ops) == 1
        and isinstance(test.ops[0], ast.Eq)
        and len(test.comparators) == 1
        and isinstance(test.comparators[0], ast.Constant)
        and test.comparators[0].value == "__main__"
    )


def strip_main_guard(tree: ast.Module) -> ast.Module:
    tree.body = [node for node in tree.body if not is_main_guard(node)]
    return tree


def _check_name(name: str, line: int, out: list[Violation]) -> None:
    if name in FORBIDDEN_NAMES:
        out.append(Violation(line, f"'{name}' is not allowed in part code"))
    elif name.startswith("_") and name != "_":
        out.append(Violation(line, f"names starting with '_' are not allowed ('{name}')"))
    elif name.startswith(FORBIDDEN_PREFIXES):
        out.append(Violation(line, f"'{name}' does file I/O; Jig handles import and export"))


def validate(code: str) -> list[Violation]:
    """Return every violation; an empty list means the code may run."""
    try:
        tree = ast.parse(code)
    except SyntaxError as error:
        return [Violation(error.lineno or 0, f"syntax error: {error.msg}")]
    strip_main_guard(tree)
    out: list[Violation] = []
    for node in ast.walk(tree):
        line = getattr(node, "lineno", 0)
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name not in PLAIN_IMPORTS:
                    hint = (
                        " (use 'from build123d import *')"
                        if alias.name.startswith("build123d")
                        else ""
                    )
                    out.append(Violation(line, f"import of '{alias.name}' is not allowed{hint}"))
                elif alias.asname:
                    _check_name(alias.asname, line, out)
        elif isinstance(node, ast.ImportFrom):
            if node.level or node.module not in ALLOWED_MODULES:
                out.append(Violation(line, f"import from '{node.module}' is not allowed"))
            for alias in node.names:
                if alias.name != "*":
                    _check_name(alias.name, line, out)
                if alias.asname:
                    _check_name(alias.asname, line, out)
        elif isinstance(node, ast.Name):
            _check_name(node.id, line, out)
        elif isinstance(node, ast.Attribute):
            if node.attr.startswith("_"):
                out.append(Violation(line, f"attribute '{node.attr}' is not allowed"))
            elif node.attr.startswith(FORBIDDEN_PREFIXES) or node.attr in FORBIDDEN_NAMES:
                out.append(Violation(line, f"'.{node.attr}' does file I/O and is not allowed"))
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            _check_name(node.name, line, out)
            if isinstance(node, ast.AsyncFunctionDef):
                out.append(Violation(line, "async functions are not allowed"))
        elif isinstance(node, ast.arg):
            _check_name(node.arg, line, out)
        elif isinstance(node, ast.Global | ast.Nonlocal):
            out.append(Violation(line, "global and nonlocal are not allowed"))
    return out
