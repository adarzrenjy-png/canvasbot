from __future__ import annotations

import pytest

from jig.cad.samples import L_BRACKET
from jig.cad.sandbox import validate


def messages(code: str) -> str:
    return " ".join(str(v) for v in validate(code))


def test_sample_part_is_allowed() -> None:
    assert validate(L_BRACKET) == []


@pytest.mark.parametrize(
    "code",
    [
        "import os",
        "import subprocess",
        "import build123d",
        "import build123d.exporters3d",
        "from os import path",
        "from build123d.topology import shape_core",
        "from . import x",
        "import socket",
    ],
)
def test_imports_outside_the_allowlist_are_rejected(code: str) -> None:
    assert "not allowed" in messages(code)


@pytest.mark.parametrize(
    "code",
    [
        "open('x.txt', 'w')",
        "eval('1')",
        "exec('x = 1')",
        "__import__('os')",
        "getattr(Box, 'x')",
        "globals()",
        "x = Box(1, 1, 1).__class__",
        "x = ().__class__.__mro__",
        "export_step(None, 'a.step')",
        "import_step('a.step')",
        "Box(1, 1, 1).export_stl('a.stl')",
        "m = Mesher()",
        "def f(__x):\n    return __x",
    ],
)
def test_escape_hatches_are_rejected(code: str) -> None:
    assert validate(code), code


def test_main_guard_may_export_because_it_never_runs() -> None:
    code = (
        "from build123d import *\n"
        'if __name__ == "__main__":\n'
        '    export_step(Box(1, 1, 1), "a.step")\n'
    )
    assert validate(code) == []


def test_a_fake_main_guard_is_still_checked() -> None:
    code = 'if __name__ == "__main__" or True:\n    open("x")\n'
    assert validate(code)


def test_underscore_loop_variable_is_fine() -> None:
    assert validate("import math\nfor _ in range(3):\n    x = math.pi\n") == []


def test_syntax_errors_carry_a_line() -> None:
    (violation,) = validate("x = (\n")
    assert violation.line >= 1
