"""Reads nodal results from a CalculiX .frd file (ASCII).

Result blocks start with a `-4  NAME` line and hold `-1` data lines: a node
number in columns 4-13, then values in 12-character fields. Fields can run
together when a value is negative, so they are read by position, not split on
spaces. Stresses arrive extrapolated to the nodes and averaged, in the order
SXX SYY SZZ SXY SYZ SZX.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np


def read_blocks(path: Path) -> dict[str, dict[int, list[float]]]:
    blocks: dict[str, dict[int, list[float]]] = {}
    current: dict[int, list[float]] | None = None
    with path.open(encoding="ascii", errors="replace") as handle:
        for line in handle:
            code = line[:3]
            if code == " -4":
                name = line[3:].split()[0]
                current = blocks.setdefault(name, {})
            elif code == " -1" and current is not None:
                node = int(line[3:13])
                body = line[13:].rstrip("\n")
                values = [float(body[i : i + 12]) for i in range(0, len(body) - 11, 12)]
                current[node] = values
            elif code == " -3":
                current = None
    return blocks


def von_mises(s: np.ndarray) -> np.ndarray:
    sxx, syy, szz, sxy, syz, szx = (s[:, i] for i in range(6))
    return np.sqrt(
        0.5 * ((sxx - syy) ** 2 + (syy - szz) ** 2 + (szz - sxx) ** 2)
        + 3.0 * (sxy**2 + syz**2 + szx**2)
    )


def nodal_results(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(node ids, displacement (n, 3), stress (n, 6)) for nodes present in both blocks."""
    blocks = read_blocks(path)
    if "DISP" not in blocks or "STRESS" not in blocks:
        raise ValueError("CalculiX results are missing displacements or stresses")
    disp, stress = blocks["DISP"], blocks["STRESS"]
    ids = np.array(sorted(set(disp) & set(stress)), dtype=np.int64)
    u = np.array([disp[i][:3] for i in ids])
    s = np.array([stress[i][:6] for i in ids])
    return ids, u, s
