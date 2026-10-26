import { CircleCheck, CircleX, FileText, Gauge, LoaderCircle, Play } from "lucide-react";
import type { FeaResult, Health, Program } from "../api";

interface Props {
  program: Program | null;
  health: Health | null;
  fea: FeaResult | null;
  stale: boolean;
  running: boolean;
  reportHref: string | null;
  onRun: () => void;
}

const fmt = (n: number, d = 1) => n.toLocaleString(undefined, { maximumFractionDigits: d, minimumFractionDigits: d });

export const VERDICT: Record<string, { label: string; tone: "ok" | "fail" | "warn" }> = {
  pass: { label: "PASS", tone: "ok" },
  fail: { label: "FAIL", tone: "fail" },
  unconverged: { label: "UNCONFIRMED", tone: "warn" },
  invalid: { label: "INVALID", tone: "warn" },
};

function forceWords(f: number[]): string {
  const mag = Math.hypot(f[0], f[1], f[2]);
  const axis = [0, 1, 2].reduce((a, b) => (Math.abs(f[b]) > Math.abs(f[a]) ? b : a), 0);
  if (Math.abs(f[axis]) / mag > 0.999) {
    const dir = axis === 2 ? (f[2] > 0 ? "up" : "down") : `${f[axis] > 0 ? "+" : "−"}${"XYZ"[axis]}`;
    return `${fmt(mag, 0)} N ${dir}`;
  }
  return `${fmt(mag, 0)} N`;
}

export function ChecksPanel({ program, health, fea, stale, running, reportHref, onRun }: Props) {
  const analysis = program?.analysis as
    | { material?: string; fixtures?: { name: string; type?: string }[]; loads?: { name: string }[]; min_safety_factor?: number }
    | null
    | undefined;
  const feaReady = health?.fea.available ?? false;
  const verdict = fea?.ok ? VERDICT[fea.status] : null;
  const sf = fea?.checks?.find((c) => c.id === "safety_factor");

  return (
    <div className="checks-panel">
      <section className="check-card">
        <header>
          <Gauge size={16} />
          <h3>Load case</h3>
        </header>
        {analysis ? (
          <ul className="load-case">
            <li data-tip="The material sets stiffness and the stress the part may reach.">
              <span>Material</span>
              <strong>{fea?.material?.name ?? analysis.material}</strong>
            </li>
            {(analysis.fixtures ?? []).map((f) => (
              <li key={f.name} data-tip={f.type === "support" ? "A support stops the face moving into or out of its plane, but lets it slide." : "A fixed face cannot move at all, like a bolted or clamped face."}>
                <span className="swatch fix" />
                <span>{f.type === "support" ? "Supported" : "Held"}</span>
                <strong>{f.name}</strong>
              </li>
            ))}
            {(fea?.loads ?? analysis.loads ?? []).map((l) => (
              <li key={l.name}>
                <span className="swatch load" />
                <span>Load</span>
                <strong>
                  {l.name}
                  {"force_n" in l ? `: ${forceWords((l as { force_n: number[] }).force_n)}` : ""}
                </strong>
              </li>
            ))}
            <li data-tip="Safety factor = the stress the material can take ÷ the highest stress in the part. 2.0 means it could carry twice the load.">
              <span>Needs</span>
              <strong>safety factor ≥ {fmt(analysis.min_safety_factor ?? 2, 1)}</strong>
            </li>
          </ul>
        ) : (
          <p className="empty-note">This part has no load case yet. The agents add one from your description; you can also write an ANALYSIS block in the Code tab.</p>
        )}
        <button type="button" className="button button-primary" onClick={onRun} disabled={running || !analysis || !feaReady}>
          {running ? <LoaderCircle size={15} className="spin" /> : <Play size={15} />}
          {running ? "Meshing and solving…" : fea ? "Run FEA again" : "Run FEA"}
        </button>
        {!feaReady && <p className="hint">{health?.fea.message} {health?.fea.install_hint}</p>}
        {running && <p className="hint">Solving on two meshes to check the answer converges. This takes about half a minute.</p>}
      </section>

      {fea && !fea.ok && (
        <section className="check-card is-warn">
          <p>{fea.error}</p>
        </section>
      )}

      {fea?.ok && verdict && (
        <section className={`check-card verdict-card is-${verdict.tone}${stale ? " is-stale" : ""}`}>
          <div className="verdict">
            <span className="verdict-label">{verdict.label}</span>
            <span className="verdict-sf" data-tip="Safety factor: allowable stress ÷ peak stress">
              SF {fmt(fea.safety_factor ?? 0, 2)}
              {sf && <small> / {fmt(sf.limit, 1)} needed</small>}
            </span>
          </div>
          {stale && <p className="hint">These results are for an earlier version of the part. Run FEA again.</p>}
          <ul className="result-list">
            {fea.checks?.map((c) => (
              <li key={c.id} className={c.pass ? "ok" : "bad"}>
                {c.pass ? <CircleCheck size={15} /> : <CircleX size={15} />}
                <span>
                  {c.label}: <strong>{fmt(c.value, 2)}</strong> (limit {fmt(c.limit, 2)})
                </span>
              </li>
            ))}
            <li className={fea.convergence?.converged ? "ok" : "bad"} data-tip="Solved on a coarse and a finer mesh. If the answer barely changes, it can be trusted.">
              {fea.convergence?.converged ? <CircleCheck size={15} /> : <CircleX size={15} />}
              <span>
                Mesh converged: stress moved {fmt((fea.convergence?.stress_change ?? 0) * 100, 1)} % between meshes
              </span>
            </li>
            <li className={fea.equilibrium?.ok ? "ok" : "bad"} data-tip="The forces at the held faces must cancel the applied loads, or the solve went wrong.">
              {fea.equilibrium?.ok ? <CircleCheck size={15} /> : <CircleX size={15} />}
              <span>Forces balance to {((fea.equilibrium?.error ?? 0) * 100).toFixed(4)} %</span>
            </li>
          </ul>
          <dl className="fea-numbers">
            <div data-tip="Von Mises stress: one number that combines all the ways the material is being pulled and sheared.">
              <dt>Peak stress</dt>
              <dd>{fmt(fea.result!.peak_von_mises_mpa, 1)} MPa</dd>
            </div>
            <div>
              <dt>Allowable</dt>
              <dd>{fmt(fea.material!.allowable_mpa, 0)} MPa</dd>
            </div>
            <div>
              <dt>Max movement</dt>
              <dd>{fmt(fea.result!.max_displacement_mm, 2)} mm</dd>
            </div>
            <div>
              <dt>Fine mesh</dt>
              <dd>{(fea.levels?.at(-1)?.elements ?? 0).toLocaleString()} elements</dd>
            </div>
          </dl>
          {reportHref && (
            <a className="button button-secondary" href={reportHref} target="_blank" rel="noreferrer">
              <FileText size={15} /> Open engineering report
            </a>
          )}
        </section>
      )}
    </div>
  );
}
