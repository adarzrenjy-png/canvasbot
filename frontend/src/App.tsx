import { Activity, CircleCheck, Code2, Flame, Gauge, LoaderCircle, Maximize2, MessageSquare, SquareDashed, TriangleAlert } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError, type Build, type FeaResult, type Health, type PartPayload } from "./api";
import { AgentPanel } from "./components/AgentPanel";
import { ChecksPanel, VERDICT } from "./components/ChecksPanel";
import { CodeView } from "./components/CodeView";
import { FeatureTree } from "./components/FeatureTree";
import { ParamsPanel } from "./components/ParamsPanel";
import { type ThemeChoice, TopBar } from "./components/TopBar";
import { type TraceEvent, TracePanel } from "./components/TracePanel";
import { Viewport, type ViewportHandle } from "./components/Viewport";
import { STRESS_GRADIENT } from "./lib/colormap";

type Tab = "agents" | "checks" | "code" | "trace";
const PLA_DENSITY_G_CM3 = 1.24;

function readTheme(): ThemeChoice {
  try {
    const saved = localStorage.getItem("jig.theme");
    if (saved === "light" || saved === "dark" || saved === "system") return saved;
  } catch {
    /* storage unavailable */
  }
  return "system";
}

function useResolvedTheme(choice: ThemeChoice): "light" | "dark" {
  const query = "(prefers-color-scheme: dark)";
  const [systemDark, setSystemDark] = useState(() => window.matchMedia(query).matches);
  useEffect(() => {
    const media = window.matchMedia(query);
    const update = () => setSystemDark(media.matches);
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);
  return choice === "system" ? (systemDark ? "dark" : "light") : choice;
}

function partTitle(code: string): string {
  const match = code.match(/^\s*(?:"""|''')\s*([^\n"']+)/);
  return match ? match[1].trim() : "Untitled part";
}

const fmt = (n: number, digits = 1) => n.toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: digits });

export default function App() {
  const [themeChoice, setThemeChoice] = useState<ThemeChoice>(readTheme);
  const theme = useResolvedTheme(themeChoice);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);
  const chooseTheme = (choice: ThemeChoice) => {
    setThemeChoice(choice);
    try {
      localStorage.setItem("jig.theme", choice);
    } catch {
      /* storage unavailable */
    }
  };

  const [part, setPart] = useState<PartPayload | null>(null);
  const [shown, setShown] = useState<Build | null>(null); // last build that produced geometry
  const [busy, setBusy] = useState(false);
  const [history, setHistory] = useState<{ stack: string[]; index: number }>({ stack: [], index: -1 });
  const [selected, setSelected] = useState<string | null>(null);
  const [hovered, setHovered] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("agents");
  const [showEdges, setShowEdges] = useState(true);
  const [health, setHealth] = useState<Health | null>(null);
  const [backendDown, setBackendDown] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [pinging, setPinging] = useState(false);
  const [trace, setTrace] = useState<TraceEvent[]>([]);
  const [fea, setFea] = useState<{ result: FeaResult; buildId: string; code: string } | null>(null);
  const [feaRunning, setFeaRunning] = useState(false);
  const [showStress, setShowStress] = useState(false);
  const traceId = useRef(0);
  const viewport = useRef<ViewportHandle>(null);

  const log = useCallback((event: Omit<TraceEvent, "id" | "at">) => {
    setTrace((events) => [...events.slice(-199), { ...event, id: ++traceId.current, at: new Date() }]);
  }, []);

  const refreshHealth = useCallback(async () => {
    try {
      setHealth(await api.health());
      setBackendDown(false);
    } catch {
      setBackendDown(true);
    }
  }, []);

  useEffect(() => {
    refreshHealth();
    const timer = window.setInterval(refreshHealth, 15000);
    return () => window.clearInterval(timer);
  }, [refreshHealth]);

  const applyPart = useCallback(
    (payload: PartPayload, opts: { record: boolean; reason: string }) => {
      setPart(payload);
      const build = payload.build;
      if (build.ok) setShown(build);
      if (opts.record) {
        setHistory((h) => {
          const stack = [...h.stack.slice(0, h.index + 1), payload.code].slice(-100);
          return { stack, index: stack.length - 1 };
        });
      }
      if (build.ok) {
        const stats = build.stats!;
        log({
          agent: "Geometry check",
          kind: "check",
          status: stats.valid && stats.solids === 1 ? "ok" : "fail",
          title: `${opts.reason}: rebuilt in ${build.elapsed_ms} ms`,
          detail: `${stats.valid ? "Valid closed solid" : "Shape is NOT a valid solid"}, ${stats.solids} solid${stats.solids === 1 ? "" : "s"}, ${stats.faces} faces, ${fmt(stats.volume_mm3 / 1000, 2)} cm³`,
        });
      } else {
        const error = build.error;
        log({
          agent: "Builder",
          kind: "check",
          status: "fail",
          title: `${opts.reason}: build failed${error?.feature ? ` in “${error.feature}”` : ""}`,
          detail: `${error?.message ?? "Unknown error"}${error?.line ? ` (line ${error.line})` : ""}`,
        });
      }
    },
    [log],
  );

  const run = useCallback(
    async (task: () => Promise<PartPayload>, opts: { record: boolean; reason: string }) => {
      setBusy(true);
      setNotice(null);
      try {
        applyPart(await task(), opts);
      } catch (error) {
        setNotice(error instanceof ApiError ? error.message : String(error));
      } finally {
        setBusy(false);
      }
    },
    [applyPart],
  );

  const started = useRef(false);
  useEffect(() => {
    if (started.current) return; // StrictMode runs effects twice in dev
    started.current = true;
    run(() => api.sample("l_bracket"), { record: true, reason: "Loaded the starter bracket" });
  }, [run]);

  const program = part?.program ?? null;
  const features = program?.features ?? [];
  const params = program?.params ?? [];

  const commitParam = (name: string, value: number) => {
    if (!part) return;
    const before = params.find((p) => p.name === name);
    run(() => api.setParams(part.code, { [name]: value }), {
      record: true,
      reason: `You set ${name} ${before ? `${before.value} → ` : ""}${value}${before?.unit ? ` ${before.unit}` : ""}`,
    });
  };

  const toggleLock = async (name: string, locked: boolean) => {
    if (!part) return;
    try {
      const next = await api.setLock(part.code, name, locked);
      setPart({ ...part, ...next });
      setHistory((h) => {
        const stack = [...h.stack.slice(0, h.index + 1), next.code];
        return { stack, index: stack.length - 1 };
      });
      log({ agent: "You", kind: "system", status: "info", title: `${locked ? "Locked" : "Unlocked"} ${name}`, detail: locked ? "Agents will leave this value alone." : undefined });
    } catch (error) {
      setNotice(error instanceof ApiError ? error.message : String(error));
    }
  };

  const goTo = (index: number) => {
    const code = history.stack[index];
    if (code === undefined || busy) return;
    setHistory((h) => ({ ...h, index }));
    run(() => api.build(code), { record: false, reason: index < history.index ? "Undo" : "Redo" });
  };
  const canUndo = history.index > 0 && !busy;
  const canRedo = history.index < history.stack.length - 1 && !busy;

  const ping = async () => {
    setPinging(true);
    try {
      const result = await api.ping();
      log({
        agent: "Meta Model API",
        kind: "agent",
        status: "ok",
        title: `${result.model} replied “${result.reply}”`,
        detail: `${result.latency_ms} ms via ${result.provider}, about $${result.cost_usd.toFixed(5)}`,
      });
      setTab("trace");
    } catch (error) {
      log({ agent: "Meta Model API", kind: "agent", status: "fail", title: "Connection test failed", detail: error instanceof Error ? error.message : String(error) });
      setTab("trace");
    } finally {
      setPinging(false);
      refreshHealth();
    }
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const typing = (e.target as HTMLElement).closest("input, textarea, [contenteditable]");
      const mod = e.metaKey || e.ctrlKey;
      if (mod && e.key.toLowerCase() === "z" && !typing) {
        e.preventDefault();
        if (e.shiftKey) canRedo && goTo(history.index + 1);
        else canUndo && goTo(history.index - 1);
      } else if (mod && e.key.toLowerCase() === "y" && !typing) {
        e.preventDefault();
        canRedo && goTo(history.index + 1);
      } else if (!mod && !typing && e.key.toLowerCase() === "f") {
        viewport.current?.fit();
      } else if (e.key === "Escape" && !typing) {
        setSelected(null);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const feaStale = fea !== null && part !== null && fea.code !== part.code;
  const feaCurrent = fea && !feaStale && fea.result.ok ? fea.result : null;

  const runFea = async () => {
    if (!part || feaRunning) return;
    setFeaRunning(true);
    setTab("checks");
    log({ agent: "FEA Critic", kind: "check", status: "info", title: "Meshing the part and solving its load case on two meshes" });
    try {
      const payload = await api.analyze(part.code, part.build.ok ? part.build.id : null);
      const result = payload.fea;
      setFea({ result, buildId: payload.build.id, code: payload.code });
      if (result.ok && result.result) {
        const verdict = VERDICT[result.status]?.label ?? result.status;
        const sf = result.checks?.find((c) => c.id === "safety_factor");
        const fine = result.levels?.at(-1);
        log({
          agent: "FEA Critic",
          kind: "check",
          status: result.status === "pass" ? "ok" : "fail",
          title: `${verdict}: safety factor ${result.safety_factor!.toFixed(2)} (needs ${sf?.limit.toFixed(1)})`,
          detail: `Peak ${result.result.peak_von_mises_mpa.toFixed(1)} MPa of ${result.material!.allowable_mpa} MPa allowable, max movement ${result.result.max_displacement_mm.toFixed(2)} mm. ${fine?.elements.toLocaleString()} elements; stress moved ${((result.convergence?.stress_change ?? 0) * 100).toFixed(1)} % between meshes; forces balance.`,
        });
        setShowStress(true);
      } else {
        log({ agent: "FEA Critic", kind: "check", status: "fail", title: "FEA could not run", detail: result.error });
      }
    } catch (error) {
      log({ agent: "FEA Critic", kind: "check", status: "fail", title: "FEA request failed", detail: error instanceof Error ? error.message : String(error) });
    } finally {
      setFeaRunning(false);
    }
  };

  const reportHref = part?.build.ok
    ? api.reportUrl(feaCurrent && fea ? fea.buildId : part.build.id)
    : null;

  const downloads = useMemo(() => {
    const build = part?.build;
    if (!build?.ok) return [];
    return [
      { label: "STEP", href: api.downloadUrl(build.id, "step"), hint: "For any CAD tool" },
      { label: "STL", href: api.downloadUrl(build.id, "stl"), hint: "For slicers" },
      { label: "Python (.py)", href: api.downloadUrl(build.id, "py"), hint: "Runs on its own with build123d" },
      ...(reportHref ? [{ label: "Engineering report", href: reportHref, hint: feaCurrent ? "With FEA results" : "Run FEA first for results" }] : []),
    ];
  }, [part, reportHref, feaCurrent]);

  const failed = part && !part.build.ok ? part.build.error : null;
  const stats = shown?.stats;
  const selectedFeature = features.find((f) => f.id === selected) ?? null;
  const material = program?.material ?? null;

  return (
    <div className="app">
      <TopBar
        title={part ? partTitle(part.code) : "Loading…"}
        health={health}
        backendDown={backendDown}
        theme={themeChoice}
        onTheme={chooseTheme}
        canUndo={canUndo}
        canRedo={canRedo}
        onUndo={() => goTo(history.index - 1)}
        onRedo={() => goTo(history.index + 1)}
        downloads={downloads}
      />

      <main className="workspace">
        <aside className="card panel panel-left">
          <section className="panel-section">
            <h2 className="section-title">Features</h2>
            <FeatureTree features={features} build={part?.build} selected={selected} hovered={hovered} onSelect={setSelected} onHover={setHovered} />
          </section>
          <section className="panel-section panel-grow">
            <h2 className="section-title">
              Parameters
              {selectedFeature && (
                <button type="button" className="link-button" onClick={() => setSelected(null)}>
                  Show all
                </button>
              )}
            </h2>
            <ParamsPanel params={params} selectedFeature={selected} busy={busy} onCommit={commitParam} onToggleLock={toggleLock} />
          </section>
        </aside>

        <section className="card viewport">
          <Viewport
            ref={viewport}
            mesh={shown?.mesh}
            theme={theme}
            selectedFeature={selected}
            hoveredFeature={hovered}
            showEdges={showEdges}
            stressField={feaCurrent?.field ?? null}
            stressMax={feaCurrent?.result?.peak_von_mises_mpa ?? 0}
            showStress={showStress && feaCurrent !== null}
            onPickFeature={setSelected}
            onHoverFeature={setHovered}
          />
          <div className="viewport-toolbar">
            <button type="button" className="icon-button floating" onClick={() => viewport.current?.fit()} data-tip="Fit to view (F)" aria-label="Fit to view">
              <Maximize2 size={16} />
            </button>
            <button type="button" className={`icon-button floating${showEdges ? " is-on" : ""}`} onClick={() => setShowEdges((v) => !v)} data-tip="Show edges" aria-pressed={showEdges} aria-label="Show edges">
              <SquareDashed size={16} />
            </button>
            <button
              type="button"
              className={`icon-button floating${showStress && feaCurrent ? " is-on" : ""}`}
              onClick={() => setShowStress((v) => !v)}
              disabled={!feaCurrent}
              data-tip={feaCurrent ? "Show the stress heatmap" : "Run FEA to see stress"}
              aria-pressed={showStress}
              aria-label="Show stress"
            >
              <Flame size={16} />
            </button>
          </div>

          {feaCurrent && VERDICT[feaCurrent.status] && (
            <button type="button" className={`verdict-badge is-${VERDICT[feaCurrent.status].tone}`} onClick={() => setTab("checks")} data-tip="From FEA: safety factor = allowable stress ÷ peak stress. Click for the evidence.">
              <strong>{VERDICT[feaCurrent.status].label}</strong>
              <span>safety factor {feaCurrent.safety_factor!.toFixed(1)}</span>
            </button>
          )}

          {showStress && feaCurrent?.result && (
            <div className="stress-legend" aria-label="Stress scale">
              <span className="legend-title">von Mises stress (MPa)</span>
              <div className="legend-bar" style={{ background: STRESS_GRADIENT }} />
              <div className="legend-ticks">
                <span>0</span>
                <span>{(feaCurrent.result.peak_von_mises_mpa / 2).toFixed(1)}</span>
                <span>{feaCurrent.result.peak_von_mises_mpa.toFixed(1)}</span>
              </div>
            </div>
          )}

          <div className="viewport-status">
            {busy ? (
              <span className="status-chip">
                <LoaderCircle size={14} className="spin" /> Rebuilding…
              </span>
            ) : failed ? (
              <span className="status-chip is-fail">
                <TriangleAlert size={14} /> Build failed{failed.feature ? ` in ${failed.feature}` : ""}
              </span>
            ) : stats ? (
              <span className={`status-chip ${stats.valid ? "is-ok" : "is-fail"}`} data-tip="Checked by OpenCascade: the part is one closed, valid solid.">
                <CircleCheck size={14} /> {stats.valid ? "Valid solid" : "Invalid solid"}
              </span>
            ) : null}
          </div>

          {failed && (
            <div className="error-banner" role="alert">
              <TriangleAlert size={16} />
              <div>
                <strong>{failed.feature ? `“${failed.feature}” failed` : "The part did not build"}</strong>
                <p>{failed.message}</p>
                <p className="error-meta">Showing the last version that built. Undo, change a value, or fix the code.</p>
              </div>
              {failed.line && (
                <button type="button" className="button button-secondary" onClick={() => { setTab("code"); setSelected(failed.feature); }}>
                  Show line {failed.line}
                </button>
              )}
            </div>
          )}
          {notice && (
            <div className="error-banner is-notice" role="alert">
              <TriangleAlert size={16} />
              <div>
                <p>{notice}</p>
              </div>
              <button type="button" className="link-button" onClick={() => setNotice(null)}>
                Dismiss
              </button>
            </div>
          )}

          {stats && (
            <dl className="stats">
              <div data-tip="How much material the part uses.">
                <dt>Volume</dt>
                <dd>{fmt(stats.volume_mm3 / 1000, 2)} cm³</dd>
              </div>
              <div data-tip={material ? `Weight if made solid in ${material.name} (${material.density_g_cm3} g/cm³).` : "Estimated weight if printed solid in PLA (1.24 g/cm³). Set a material in the load case."}>
                <dt>Mass ({material ? material.name.replace(/ \(.*\)$/, "") : "PLA"})</dt>
                <dd>{fmt((stats.volume_mm3 / 1000) * (material?.density_g_cm3 ?? PLA_DENSITY_G_CM3), 1)} g</dd>
              </div>
              <div data-tip="The smallest box the part fits in, X × Y × Z.">
                <dt>Size</dt>
                <dd>{stats.bbox.size.map((v) => fmt(v, 1)).join(" × ")} mm</dd>
              </div>
              <div>
                <dt>Faces</dt>
                <dd>{stats.faces}</dd>
              </div>
            </dl>
          )}
        </section>

        <aside className="card panel panel-right">
          <div className="tabs" role="tablist">
            <button type="button" role="tab" aria-selected={tab === "agents"} className={`tab${tab === "agents" ? " is-active" : ""}`} onClick={() => setTab("agents")}>
              <MessageSquare size={15} /> Agents
            </button>
            <button type="button" role="tab" aria-selected={tab === "checks"} className={`tab${tab === "checks" ? " is-active" : ""}`} onClick={() => setTab("checks")}>
              <Gauge size={15} /> Checks
            </button>
            <button type="button" role="tab" aria-selected={tab === "code"} className={`tab${tab === "code" ? " is-active" : ""}`} onClick={() => setTab("code")}>
              <Code2 size={15} /> Code
            </button>
            <button type="button" role="tab" aria-selected={tab === "trace"} className={`tab${tab === "trace" ? " is-active" : ""}`} onClick={() => setTab("trace")}>
              <Activity size={15} /> Trace
              {trace.length > 0 && <span className="tab-count">{trace.length}</span>}
            </button>
          </div>
          <div className="tab-body">
            {tab === "agents" && <AgentPanel health={health} pinging={pinging} onPing={ping} />}
            {tab === "checks" && (
              <ChecksPanel program={program} health={health} fea={fea?.result ?? null} stale={feaStale} running={feaRunning} reportHref={reportHref} onRun={runFea} />
            )}
            {tab === "code" && part && (
              <CodeView code={part.code} features={features} selectedFeature={selected} errorLine={failed?.line ?? null} onSelectFeature={setSelected} />
            )}
            {tab === "trace" && <TracePanel events={trace} />}
          </div>
        </aside>
      </main>

      <footer className="footer">
        <span>FEA results are simulation estimates, not certification. Verify critical parts with physical testing.</span>
        <span className="footer-credit">Built with Meta Muse models · Jig {health?.version ?? ""}</span>
      </footer>
    </div>
  );
}
