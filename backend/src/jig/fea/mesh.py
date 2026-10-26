"""Quadratic tetrahedral meshing of a STEP part with gmsh.

Elements are 10-node tetrahedra (C3D10 in CalculiX). Linear tetrahedra are far
too stiff in bending, which is how brackets and mounts are loaded, so they are
never used. The mesh size comes from the part size and is refined around curved
faces (holes, fillets), where stress concentrates.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

# gmsh numbers the six midside nodes (0-1, 1-2, 0-2, 0-3, 2-3, 1-3); CalculiX's
# C3D10 wants (0-1, 1-2, 2-0, 0-3, 1-3, 2-3). Checked by tests/test_fea.py.
GMSH_TO_C3D10 = [0, 1, 2, 3, 4, 5, 6, 7, 9, 8]
TET10, TRI6 = 11, 9


@dataclass
class SurfaceMesh:
    tag: int
    area: float
    center: np.ndarray
    tris: np.ndarray  # (n, 6) node ids in gmsh tri6 order: corners, then 0-1, 1-2, 2-0


@dataclass
class Mesh:
    node_ids: np.ndarray
    coords: np.ndarray
    tets: np.ndarray  # (n, 10) node ids, already in C3D10 order
    surfaces: dict[int, SurfaceMesh] = field(default_factory=dict)
    size: float = 0.0

    def coord_lookup(self) -> dict[int, np.ndarray]:
        return dict(zip(self.node_ids.tolist(), self.coords, strict=True))


class MeshError(RuntimeError):
    pass


def mesh_step(step: Path, size: float, curvature_points: int = 18) -> Mesh:
    import gmsh  # imported here so the API process never loads gmsh

    gmsh.initialize(interruptible=False)
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("part")
        gmsh.model.occ.importShapes(str(step))
        gmsh.model.occ.synchronize()
        if not gmsh.model.getEntities(3):
            raise MeshError("The STEP file has no solid to mesh")
        gmsh.option.setNumber("Mesh.MeshSizeMax", size)
        gmsh.option.setNumber("Mesh.MeshSizeMin", size / 8)
        gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", curvature_points)
        gmsh.option.setNumber("Mesh.ElementOrder", 2)
        gmsh.option.setNumber("Mesh.SecondOrderLinear", 0)  # midside nodes on the true surface
        gmsh.option.setNumber("Mesh.Optimize", 1)
        gmsh.model.mesh.generate(3)

        tags, coords, _ = gmsh.model.mesh.getNodes()
        _, tet_nodes = gmsh.model.mesh.getElementsByType(TET10)
        if len(tet_nodes) == 0:
            raise MeshError("gmsh produced no 10-node tetrahedra")
        tets = tet_nodes.reshape(-1, 10)[:, GMSH_TO_C3D10].astype(np.int64)

        surfaces = {}
        for dim, tag in gmsh.model.getEntities(2):
            types, _, node_lists = gmsh.model.mesh.getElements(dim, tag)
            tris = [n for t, n in zip(types, node_lists, strict=True) if t == TRI6]
            if not tris:
                continue
            surfaces[tag] = SurfaceMesh(
                tag=tag,
                area=gmsh.model.occ.getMass(dim, tag),
                center=np.array(gmsh.model.occ.getCenterOfMass(dim, tag)),
                tris=np.concatenate(tris).reshape(-1, 6).astype(np.int64),
            )
        return Mesh(
            node_ids=tags.astype(np.int64),
            coords=coords.reshape(-1, 3),
            tets=tets,
            surfaces=surfaces,
            size=size,
        )
    finally:
        gmsh.finalize()


def match_surfaces(mesh: Mesh, face_info: list[dict], diagonal: float) -> dict[int, int]:
    """Map build face index -> gmsh surface tag by centre and area (STEP keeps faces 1:1)."""
    mapping: dict[int, int] = {}
    used: set[int] = set()
    for face in face_info:
        center = np.array(face["center"])
        best, best_score = None, None
        for tag, surface in mesh.surfaces.items():
            if tag in used:
                continue
            area_err = abs(surface.area - face["area"]) / max(face["area"], 1e-9)
            dist = float(np.linalg.norm(surface.center - center)) / max(diagonal, 1e-9)
            if area_err > 0.02 or dist > 0.01:
                continue
            score = area_err + dist
            if best_score is None or score < best_score:
                best, best_score = tag, score
        if best is None:
            raise MeshError(f"Could not find face {face['index']} of the part in the mesh")
        mapping[face["index"]] = best
        used.add(best)
    return mapping
