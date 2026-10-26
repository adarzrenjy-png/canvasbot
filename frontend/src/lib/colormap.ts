// The FEA stress scale, matching the engineering report: blue (low) to red (high).
const STOPS: [number, [number, number, number]][] = [
  [0, [38, 84, 196]],
  [0.25, [46, 170, 220]],
  [0.5, [60, 190, 110]],
  [0.75, [240, 200, 60]],
  [1, [220, 50, 40]],
];

export function stressRgb(t: number): [number, number, number] {
  const x = Math.min(1, Math.max(0, t));
  for (let i = 1; i < STOPS.length; i++) {
    const [t1, c1] = STOPS[i];
    if (x <= t1) {
      const [t0, c0] = STOPS[i - 1];
      const k = (x - t0) / (t1 - t0);
      return [0, 1, 2].map((j) => (c0[j] + (c1[j] - c0[j]) * k) / 255) as [number, number, number];
    }
  }
  return [220 / 255, 50 / 255, 40 / 255];
}

export const STRESS_GRADIENT = `linear-gradient(90deg, ${STOPS.map(([t, [r, g, b]]) => `rgb(${r} ${g} ${b}) ${t * 100}%`).join(", ")})`;
