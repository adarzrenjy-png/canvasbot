"""Engineering materials with the source of every number.

Units match the solver: MPa for moduli and strengths, tonne/mm^3 for density
(so N, mm, s are consistent). `allowable_mpa` is the stress the safety factor is
measured against. For metals it is the yield strength. For 3D-printed plastics it
is the tensile strength with a knockdown for layer adhesion, because printed
parts usually fail between layers well before the datasheet value.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Material:
    id: str
    name: str
    youngs_mpa: float
    poisson: float
    density_t_mm3: float
    allowable_mpa: float
    allowable_basis: str
    process: str  # "printed", "machined", "tube", "sheet"
    source: str

    @property
    def density_g_cm3(self) -> float:
        return self.density_t_mm3 * 1e9

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["density_g_cm3"] = self.density_g_cm3
        return data


# Printed-plastic values are typical datasheet numbers for 100 % infill, printed
# flat. The 0.6 knockdown on tensile strength covers layer (Z) weakness; it is a
# common conservative design rule, not a measured property of any one printer.
MATERIALS: dict[str, Material] = {
    m.id: m
    for m in (
        Material(
            "pla",
            "PLA (3D printed)",
            3500,
            0.36,
            1.24e-9,
            0.6 * 50,
            "0.6 x 50 MPa tensile strength (layer-adhesion knockdown)",
            "printed",
            "Typical PLA filament datasheets, 100 % infill",
        ),
        Material(
            "petg",
            "PETG (3D printed)",
            2100,
            0.38,
            1.27e-9,
            0.6 * 50,
            "0.6 x 50 MPa tensile strength (layer-adhesion knockdown)",
            "printed",
            "Typical PETG filament datasheets, 100 % infill",
        ),
        Material(
            "abs",
            "ABS (3D printed)",
            2200,
            0.35,
            1.04e-9,
            0.6 * 40,
            "0.6 x 40 MPa tensile strength (layer-adhesion knockdown)",
            "printed",
            "Typical ABS filament datasheets, 100 % infill",
        ),
        Material(
            "pa_cf",
            "Nylon + carbon fibre (3D printed)",
            7000,
            0.35,
            1.15e-9,
            0.6 * 80,
            "0.6 x 80 MPa tensile strength (layer-adhesion knockdown)",
            "printed",
            "Typical PA-CF filament datasheets, XY direction, 100 % infill",
        ),
        Material(
            "al6061_t6",
            "Aluminium 6061-T6",
            68900,
            0.33,
            2.70e-9,
            276,
            "Tensile yield strength 276 MPa",
            "machined",
            "ASM Aerospace Specification Metals, 6061-T6",
        ),
        Material(
            "al7075_t6",
            "Aluminium 7075-T6",
            71700,
            0.33,
            2.81e-9,
            503,
            "Tensile yield strength 503 MPa",
            "machined",
            "ASM Aerospace Specification Metals, 7075-T6",
        ),
        Material(
            "steel_4130",
            "Steel 4130 (normalized)",
            205000,
            0.29,
            7.85e-9,
            435,
            "Tensile yield strength 435 MPa",
            "tube",
            "AISI 4130 normalized, typical published values",
        ),
        Material(
            "steel_1018",
            "Mild steel 1018 (cold drawn)",
            205000,
            0.29,
            7.87e-9,
            370,
            "Tensile yield strength 370 MPa",
            "machined",
            "AISI 1018 cold drawn, typical published values",
        ),
        Material(
            "ss_304",
            "Stainless steel 304 (annealed)",
            193000,
            0.29,
            8.00e-9,
            215,
            "Tensile yield strength 215 MPa",
            "sheet",
            "AISI 304 annealed, typical published values",
        ),
    )
}


def get_material(material_id: str) -> Material:
    try:
        return MATERIALS[material_id]
    except KeyError as error:
        known = ", ".join(sorted(MATERIALS))
        raise KeyError(f"Unknown material {material_id!r}. Known: {known}") from error
