"""Static SVG pictures of a part for reports: shaded views, highlights, arrows, heatmaps.

A small painter's-algorithm renderer with no dependencies beyond numpy: project
the triangles orthographically, sort them back to front, and shade each by how
squarely it faces the light. Good enough to read a part on paper, and the report
stays one self-contained file.
"""

from __future__ import annotations

import base64
from array import array
from dataclasses import dataclass

import numpy as np

VIEW = np.array([1.0, -1.25, 0.95])  # from the part toward the camera, as in the app
LIGHT = np.array([0.45, -0.35, 0.82])


def decode(b64: str, typecode: str) -> np.ndarray:
    values = array(typecode)
    values.frombytes(base64.b64decode(b64))
    return np.array(values)


@dataclass
class Camera:
    right: np.ndarray
    up: np.ndarray
    forward: np.ndarray  # toward the viewer

    @classmethod
    def iso(cls, view: np.ndarray = VIEW) -> Camera:
        forward = view / np.linalg.norm(view)
        right = np.cross(np.array([0.0, 0.0, 1.0]), forward)
        right /= np.linalg.norm(right)
        up = np.cross(forward, right)
        return cls(right, up, forward)

    def project(self, points: np.ndarray) -> np.ndarray:
        return np.stack([points @ self.right, -(points @ self.up), points @ self.forward], axis=1)


def stress_color(t: float) -> str:
    """Blue -> cyan -> green -> yellow -> red, the usual FEA scale."""
    stops = [
        (0.0, (38, 84, 196)),
        (0.25, (46, 170, 220)),
        (0.5, (60, 190, 110)),
        (0.75, (240, 200, 60)),
        (1.0, (220, 50, 40)),
    ]
    t = min(1.0, max(0.0, t))
    for (t0, c0), (t1, c1) in zip(stops, stops[1:], strict=False):
        if t <= t1:
            k = (t - t0) / (t1 - t0)
            r, g, b = (round(a + (b_ - a) * k) for a, b_ in zip(c0, c1, strict=True))
            return f"#{r:02x}{g:02x}{b:02x}"
    return "#dc3228"


def _shade(hex_color: str, factor: float) -> str:
    r, g, b = (int(hex_color[i : i + 2], 16) for i in (1, 3, 5))
    return "#{:02x}{:02x}{:02x}".format(*(min(255, round(c * factor)) for c in (r, g, b)))


class Picture:
    """Collects triangles and annotations, then writes one SVG fitted to a box."""

    def __init__(self, width: int = 560, height: int = 380, camera: Camera | None = None):
        self.width, self.height = width, height
        self.camera = camera or Camera.iso()
        self.tris: list[tuple[np.ndarray, str]] = []  # (3x3 world points, base colour)
        self.arrows: list[tuple[np.ndarray, np.ndarray, str, str]] = []
        self.markers: list[tuple[np.ndarray, str, str]] = []

    def add_mesh(self, positions: np.ndarray, indices: np.ndarray, colors: list[str]) -> None:
        pts = positions.reshape(-1, 3)
        for tri, color in zip(indices.reshape(-1, 3), colors, strict=True):
            self.tris.append((pts[tri], color))

    def add_arrow(self, tip: np.ndarray, direction: np.ndarray, label: str, color: str) -> None:
        self.arrows.append((tip, direction, label, color))

    def add_marker(self, point: np.ndarray, label: str, color: str) -> None:
        self.markers.append((point, label, color))

    def svg(self, margin: float = 0.06, font: int = 17) -> str:
        if not self.tris:
            return ""
        cam = self.camera
        all_pts = np.concatenate([t for t, _ in self.tris])
        span = float(np.max(np.ptp(all_pts, axis=0))) or 1.0
        arrow_len = span * 0.35
        extra = [all_pts]
        for tip, direction, _, _ in self.arrows:
            d = direction / (np.linalg.norm(direction) or 1)
            extra.append(np.array([tip - d * arrow_len]))
        proj_all = cam.project(np.concatenate(extra))
        lo, hi = proj_all[:, :2].min(axis=0), proj_all[:, :2].max(axis=0)
        usable = np.array([self.width, self.height]) * (1 - 2 * margin)
        scale = float(np.min(usable / np.maximum(hi - lo, 1e-9)))
        offset = np.array([self.width, self.height]) / 2 - (lo + hi) / 2 * scale

        def to2d(points: np.ndarray) -> np.ndarray:
            p = cam.project(points)
            return p[:, :2] * scale + offset

        light = LIGHT / np.linalg.norm(LIGHT)
        items = []
        for pts, color in self.tris:
            n = np.cross(pts[1] - pts[0], pts[2] - pts[0])
            norm = np.linalg.norm(n)
            if norm == 0:
                continue
            n /= norm
            flat = to2d(pts)
            a, b = flat[1] - flat[0], flat[2] - flat[0]
            twice_area = abs(a[0] * b[1] - a[1] * b[0])
            if twice_area < 0.15:  # too small to see at this size
                continue
            depth = float(np.mean(pts @ cam.forward))
            factor = 0.55 + 0.5 * abs(float(n @ light))
            items.append((depth, flat, _shade(color, factor)))
        items.sort(key=lambda item: item[0])

        out = [
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {self.width} {self.height}" '
            f'width="{self.width}" height="{self.height}" role="img">',
            '<defs><marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
            'markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" '
            'fill="context-stroke"/></marker></defs>',
            '<g stroke-linejoin="round" stroke-width="0.4">',
        ]
        for _, p, fill in items:
            out.append(
                f'<path d="M{p[0, 0]:.0f} {p[0, 1]:.0f}L{p[1, 0]:.0f} {p[1, 1]:.0f}'
                f'L{p[2, 0]:.0f} {p[2, 1]:.0f}Z" fill="{fill}" stroke="{fill}"/>'
            )
        out.append("</g>")
        for tip, direction, label, color in self.arrows:
            d = direction / (np.linalg.norm(direction) or 1)
            start, end = to2d(np.array([tip - d * arrow_len, tip]))
            out.append(
                f'<line x1="{start[0]:.1f}" y1="{start[1]:.1f}" x2="{end[0]:.1f}" y2="{end[1]:.1f}" '
                f'stroke="{color}" stroke-width="4" marker-end="url(#ah)"/>'
            )
            out.append(_label(start, label, color, font))
        for point, label, color in self.markers:
            (p,) = to2d(np.array([point]))
            out.append(
                f'<circle cx="{p[0]:.1f}" cy="{p[1]:.1f}" r="8" fill="none" stroke="{color}" stroke-width="3"/>'
            )
            out.append(_label(p + np.array([12, -10]), label, color, font))
        out.append("</svg>")
        return "".join(out)


def _label(at: np.ndarray, text: str, color: str, font: int = 17) -> str:
    from html import escape

    return (
        f'<text x="{at[0]:.1f}" y="{at[1] - 6:.1f}" font-size="{font}" font-family="Inter, Arial, sans-serif" '
        f'font-weight="600" fill="{color}" paint-order="stroke" stroke="#fff" stroke-width="3">'
        f"{escape(text)}</text>"
    )


def face_colors(faces: list[dict], highlight: dict[int, str], base: str) -> list[str]:
    """One colour per triangle from per-face ranges of a build mesh payload."""
    colors: list[str] = []
    for i, face in enumerate(faces):
        colors += [highlight.get(i, base)] * (face["count"] // 3)
    return colors


def heat_colors(indices: np.ndarray, values: np.ndarray, vmax: float) -> list[str]:
    tri_values = values[indices.reshape(-1, 3)].mean(axis=1)
    return [stress_color(v / vmax if vmax > 0 else 0.0) for v in tri_values]


def scale_bar(vmax: float, unit: str = "MPa", width: int = 260) -> str:
    stops = "".join(
        f'<stop offset="{t:.2f}" stop-color="{stress_color(t)}"/>' for t in np.linspace(0, 1, 9)
    )
    ticks = "".join(
        f'<text x="{10 + t * (width - 20):.0f}" y="48" font-size="10" text-anchor="middle" '
        f'font-family="Inter, Arial, sans-serif" fill="#5b6b78">{vmax * t:.{1 if vmax < 100 else 0}f}</text>'
        for t in (0, 0.25, 0.5, 0.75, 1.0)
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} 54" width="{width}" height="54">'
        f'<defs><linearGradient id="sb">{stops}</linearGradient></defs>'
        f'<rect x="10" y="18" width="{width - 20}" height="14" rx="3" fill="url(#sb)"/>{ticks}'
        f'<text x="{width - 10}" y="12" font-size="10" text-anchor="end" font-family="Inter, Arial, sans-serif" '
        f'fill="#5b6b78">von Mises, {unit}</text></svg>'
    )


ISO_VIEWS = [np.array([sx, sy, 0.95]) for sx in (1.0, -1.0) for sy in (-1.25, 1.25)]


def best_view(face_info: list[dict], wanted: list[int]) -> np.ndarray:
    """The corner view that shows the most of the given faces (flat faces facing the
    camera count fully, curved ones half), so a picture never hides what it is about."""

    def score(view: np.ndarray) -> float:
        v = view / np.linalg.norm(view)
        total = 0.0
        for i in wanted:
            face = face_info[i]
            normal = face.get("normal")
            total += face["area"] * (max(0.0, float(np.dot(normal, v))) if normal else 0.5)
        return total

    return max(ISO_VIEWS, key=score)
