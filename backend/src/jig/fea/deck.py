"""Writes the CalculiX input deck (.inp) for a linear static load case.

Loads are applied as consistent nodal forces. For a 6-node triangle under a
uniform traction the exact equivalent loads are zero at the corners and one third
of the triangle's share at each midside node, so that is what each surface
triangle contributes. Spreading a force evenly over all nodes instead would be
wrong for quadratic elements.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

import numpy as np

from jig.fea.materials import Material
from jig.fea.mesh import Mesh


@dataclass
class BoundarySet:
    name: str
    surface_tags: list[int]
    dofs: tuple[int, ...] = (1, 2, 3)  # 1-3 = x, y, z; a support holds only its normal


@dataclass
class ForceSet:
    name: str
    surface_tags: list[int]
    force: tuple[float, float, float]


def surface_nodes(mesh: Mesh, tags: list[int]) -> np.ndarray:
    if not tags:
        return np.array([], dtype=np.int64)
    return np.unique(np.concatenate([mesh.surfaces[t].tris.ravel() for t in tags]))


def consistent_loads(mesh: Mesh, load: ForceSet) -> dict[int, np.ndarray]:
    xyz = mesh.coord_lookup()
    tris = np.concatenate([mesh.surfaces[t].tris for t in load.surface_tags])
    areas = np.array(
        [
            0.5 * np.linalg.norm(np.cross(xyz[b] - xyz[a], xyz[c] - xyz[a]))
            for a, b, c in tris[:, :3]
        ]
    )
    total = areas.sum()
    if total <= 0:
        raise ValueError(f"Load '{load.name}' landed on faces with no area")
    force = np.array(load.force, dtype=float)
    nodal: dict[int, np.ndarray] = defaultdict(lambda: np.zeros(3))
    for tri, area in zip(tris, areas, strict=True):
        share = force * (area / total) / 3.0
        for node in tri[3:]:
            nodal[int(node)] += share
    return dict(nodal)


def _chunks(values, size: int = 16):
    values = list(values)
    for i in range(0, len(values), size):
        yield values[i : i + size]


def write_deck(
    mesh: Mesh,
    material: Material,
    fixtures: list[BoundarySet],
    loads: list[ForceSet],
) -> str:
    out: list[str] = ["*HEADING", "Jig linear static analysis (units: mm, N, MPa, tonne)"]
    out.append("*NODE, NSET=NALL")
    out += [
        f"{nid}, {x:.9g}, {y:.9g}, {z:.9g}"
        for nid, (x, y, z) in zip(mesh.node_ids.tolist(), mesh.coords, strict=True)
    ]
    out.append("*ELEMENT, TYPE=C3D10, ELSET=EALL")
    out += [f"{i + 1}, " + ", ".join(str(int(n)) for n in tet) for i, tet in enumerate(mesh.tets)]

    for i, fixture in enumerate(fixtures):
        out.append(f"*NSET, NSET=FIX{i + 1}")
        out += [
            ", ".join(str(n) for n in row)
            for row in _chunks(surface_nodes(mesh, fixture.surface_tags).tolist())
        ]

    out += [
        f"*MATERIAL, NAME={material.id.upper()}",
        "*ELASTIC",
        f"{material.youngs_mpa:.6g}, {material.poisson:.4g}",
        "*DENSITY",
        f"{material.density_t_mm3:.6g}",
        f"*SOLID SECTION, ELSET=EALL, MATERIAL={material.id.upper()}",
        "*BOUNDARY",
    ]
    for i, fixture in enumerate(fixtures):
        out += [f"FIX{i + 1}, {dof}, {dof}, 0." for dof in fixture.dofs]

    out += ["*STEP", "*STATIC", "*CLOAD"]
    combined: dict[int, np.ndarray] = defaultdict(lambda: np.zeros(3))
    for load in loads:
        for node, value in consistent_loads(mesh, load).items():
            combined[node] += value
    for node in sorted(combined):
        for dof, value in enumerate(combined[node], start=1):
            if value != 0.0:
                out.append(f"{node}, {dof}, {value:.9g}")
    out += ["*NODE FILE", "U", "*EL FILE", "S", "*END STEP", ""]
    return "\n".join(out)
