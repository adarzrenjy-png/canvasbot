import { Activity, Bot, Box, CircleCheck, CircleX, Code2, Cpu, Gauge, Layers, LoaderCircle, Maximize2, Network, TriangleAlert } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError, type BoardCheck, type BoardFinding, type BoardPayload, type Health, type PartPayload } from "../api";
import { useAgentRun } from "../lib/useAgentRun";
import { AgentPanel } from "./AgentPanel";
import { CodeView } from "./CodeView";
import { ParamsPanel } from "./ParamsPanel";
import type { TraceEvent } from "./TracePanel";
import { TracePanel } from "./TracePanel";
import { Viewport, type ViewportHandle } from "./Viewport";

const MARGIN = 3; // must match jig.pcb.render.board_svg's margin

export interface BoardChrome {
  title: string;
  downloads: { label: string; href: string; hint: string }[];
}

interface Props {
  theme: "light" | "dark";
  onChrome: (chrome: BoardChrome) => void;
  health: Health | null;
  pinging: boolean;
  onPing: () => void;
  onSpend: () => void;
}

type View = "layout" | "schematic" | "3d";
type Side = "agents" | "checks" | "code" | "trace";

function useZoom() {
  const [t, setT] = useState({ x: 0, y: 0, s: 1 });
  const drag = useRef<{ x: number; y: number; ox: number; oy: number } | null>(null);
  const onWheel = (e: React.WheelEvent<HTMLDivElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const px = e.clientX - rect.left;
    const py = e.clientY - rect.top;
    setT((prev) => {
      const s = Math.min(12, Math.max(0.5, prev.s * (e.deltaY < 0 ? 1.15 : 1 / 1.15)));
      return { s, x: px - ((px - prev.x) * s) / prev.s, y: py - ((py - prev.y) * s) / prev.s };
    });
  };
  const onPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    drag.current = { x: e.clientX, y: e.clientY, ox: t.x, oy: t.y };
  };
  const onPointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    const d = drag.current;
    if (!d || !e.buttons) return;
    setT((prev) => ({ ...prev, x: d.ox + e.clientX - d.x, y: d.oy + e.clientY - d.y }));
  };
  const onPointerUp = () => {
    drag.current = null;
  };
  const reset = () => setT({ x: 0, y: 0, s: 1 });
  return { t, handlers: { onWheel, onPointerDown, onPointerMove, onPointerUp, onPointerLeave: onPointerUp }, reset };
}

function svgAspect(svg: string): number {
  const m = /viewBox="[\d.\-]+ [\d.\-]+ ([\d.]+) ([\d.]+)"/.exec(svg) ?? /width="([\d.]+)" height="([\d.]+)"/.exec(svg);
  return m ? Number(m[1]) / Number(m[2]) : 1.5;
}

function Canvas({ svg, net, onNet, marker, layers, board, kind }: {
  svg: string;
  net: string | null;
  onNet: (net: string | null) => void;
  marker: [number, number] | null;
  layers: Record<string, boolean>;
  board: { width: number; height: number };
  kind: "layout" | "schematic";
}) {
  const { t, handlers, reset } = useZoom();
  const moved = useRef(false);
  const aspect = useMemo(() => svgAspect(svg), [svg]);
  const sel = net ? CSS.escape(net) : "";
  const highlight = net
    ? `.board-canvas.has-net [data-net="${sel}"] { opacity: 1; }
       .board-canvas.has-net .track[data-net="${sel}"] { stroke: #ffd43b; }
       .board-canvas.has-net .net[data-net="${sel}"] { fill: #e8590c; font-weight: 700; }`
    : "";
  const hidden = Object.entries(layers)
    .filter(([, on]) => !on)
    .map(([layer]) => `hide-${layer}`)
    .join(" ");
  const w = board.width + 2 * MARGIN;
  const h = board.height + 2 * MARGIN;
  return (
    <div
      className={`board-canvas kind-${kind}${net ? " has-net" : ""} ${hidden}`}
      {...handlers}
      onPointerDown={(e) => {
        moved.current = false;
        handlers.onPointerDown(e);
      }}
      onPointerMove={(e) => {
        if (e.buttons) moved.current = true;
        handlers.onPointerMove(e);
      }}
      onClick={(e) => {
        if (moved.current) return;
        const hit = (e.target as Element).closest("[data-net]");
        const name = hit?.getAttribute("data-net") || null;
        onNet(name && name !== net ? name : null);
      }}
      onDoubleClick={reset}
    >
      <style>{highlight}</style>
      <div className="board-stage" style={{ transform: `translate(${t.x}px, ${t.y}px) scale(${t.s})` }}>
        <div className="board-sheet" style={{ width: `min(100cqw - 64px, (100cqh - 120px) * ${aspect.toFixed(4)})` }}>
          <div className="board-svg" dangerouslySetInnerHTML={{ __html: svg }} />
          {marker && kind === "layout" && (
            <span
              className="board-marker"
              style={{ left: `${((marker[0] + MARGIN) / w) * 100}%`, top: `${((board.height - marker[1] + MARGIN) / h) * 100}%` }}
            />
          )}
        </div>
      </div>
    </div>
  );
}

function CheckRow({ check, onFinding }: { check: BoardCheck; onFinding: (f: BoardFinding) => void }) {
  const Icon = check.status === "pass" ? CircleCheck : check.status === "fail" ? CircleX : TriangleAlert;
  return (
    <li className={`board-check is-${check.status}`}>
      <div className="board-check-head">
        <Icon size={15} />
        <span className="board-check-kind">{check.kind.toUpperCase()}</span>
        <span className="board-check-label">{check.label}</span>
        <span className="board-check-count" data-tip="How many items this check measured">{check.looked_at}</span>
      </div>
      {check.findings.length > 0 && (
        <ul className="board-findings">
          {check.findings.map((f, i) => (
            <li key={i}>
              <button type="button" className={`finding is-${f.severity}`} onClick={() => onFinding(f)}>
                {f.message}
              </button>
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}

export function BoardWorkspace({ theme, onChrome, health, pinging, onPing, onSpend }: Props) {
  const [board, setBoard] = useState<BoardPayload | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [net, setNet] = useState<string | null>(null);
  const [marker, setMarker] = useState<[number, number] | null>(null);
  const [view, setView] = useState<View>("layout");
  const [side, setSide] = useState<Side>("agents");
  const [layers, setLayers] = useState({ top: true, bottom: true, silk: true });
  const [model, setModel] = useState<PartPayload | null>(null);
  const [modelBusy, setModelBusy] = useState(false);
  const [trace, setTrace] = useState<TraceEvent[]>([]);
  const traceId = useRef(0);
  const viewport = useRef<ViewportHandle>(null);

  const log = useCallback((event: Omit<TraceEvent, "id" | "at">) => {
    setTrace((events) => [...events.slice(-199), { ...event, id: ++traceId.current, at: new Date() }]);
  }, []);

  const apply = useCallback(
    (payload: BoardPayload, reason: string) => {
      setBoard(payload);
      setModel(null);
      const c = payload.checks;
      log({
        agent: "Router",
        kind: "check",
        status: payload.routing.unrouted.length ? "fail" : "ok",
        title: `${reason}: routed ${payload.routing.routed_nets} of ${payload.routing.nets} nets in ${payload.routing.seconds.toFixed(1)} s`,
        detail: `${payload.routing.tracks} tracks, ${payload.routing.vias} vias, ${payload.routing.length_mm.toFixed(0)} mm of copper track`,
      });
      log({
        agent: "Rule checks",
        kind: "check",
        status: c.status === "pass" ? "ok" : "fail",
        title: `${c.status === "pass" ? "PASS" : "FAIL"}: ${c.errors} errors, ${c.warnings} warnings across ${c.checks.length} DRC and ERC checks`,
      });
    },
    [log],
  );

  const run = useCallback(
    async (task: () => Promise<BoardPayload>, reason: string) => {
      setBusy(true);
      setNotice(null);
      try {
        apply(await task(), reason);
      } catch (error) {
        setNotice(error instanceof ApiError ? error.message : String(error));
      } finally {
        setBusy(false);
      }
    },
    [apply],
  );

  const agents = useAgentRun("board", {
    onTrace: log,
    onBoard: (payload) => {
      setBoard(payload);
      setModel(null);
      setMarker(null);
    },
    onResult: (result) => {
      if (result.board) apply(result.board, "The agents finished");
    },
    onSpend,
  });

  const boardRef = useRef(board);
  boardRef.current = board;
  const started = useRef(false);
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    setBusy(true);
    api
      .boardSample("pico_servo")
      .then((payload) => {
        if (!boardRef.current) apply(payload, "Loaded the starter board");
      })
      .catch((error) => setNotice(error instanceof ApiError ? error.message : String(error)))
      .finally(() => setBusy(false));
  }, [apply]);

  useEffect(() => {
    if (!board) {
      onChrome({ title: "Loading board…", downloads: [] });
      return;
    }
    const downloads = [
      { label: "Fabrication files (.zip)", href: api.boardFabUrl(board.id), hint: "Gerbers, drills, BOM, CPL" },
      { label: "Board report", href: api.boardReportUrl(board.id), hint: "Schematic, checks, BOM" },
      { label: "Board program (.py)", href: api.boardSourceUrl(board.id), hint: "Rebuilds this board in Jig" },
    ];
    if (model?.build.ok) {
      downloads.push({ label: "3D board (STEP)", href: api.downloadUrl(model.build.id, "step"), hint: "For enclosure design" });
    }
    onChrome({ title: board.name, downloads });
  }, [board, model, onChrome]);

  useEffect(() => {
    if (view !== "3d" || !board || model || modelBusy) return;
    setModelBusy(true);
    api
      .boardModel(board.id)
      .then((payload) => {
        setModel(payload);
        log({ agent: "Builder", kind: "check", status: payload.build.ok ? "ok" : "fail", title: "Built the board in 3D for fit checks", detail: "Board blank, drilled holes and a block for every part" });
      })
      .catch((error) => setNotice(error instanceof Error ? error.message : String(error)))
      .finally(() => setModelBusy(false));
  }, [view, board, model, modelBusy, log]);

  const errorsFirst = useMemo(() => {
    if (!board) return [];
    const order = { fail: 0, warn: 1, pass: 2 };
    return [...board.checks.checks].sort((a, b) => order[a.status] - order[b.status]);
  }, [board]);

  const showFinding = (f: BoardFinding) => {
    setView("layout");
    setMarker(f.at);
    setNet(f.nets[0] ?? null);
  };

  const params = board?.params ?? [];
  const passed = board?.checks.status === "pass";

  return (
    <main className="workspace">
      <aside className="card panel panel-left">
        <section className="panel-section">
          <h2 className="section-title">Parameters</h2>
          <ParamsPanel
            params={params}
            selectedFeature={null}
            busy={busy || agents.running}
            onCommit={(name, value) => board && run(() => api.boardParams(board.code, { [name]: value }), `You set ${name} to ${value}`)}
            onToggleLock={(name, locked) => board && run(() => api.boardLock(board.code, name, locked), `${locked ? "Locked" : "Unlocked"} ${name}`)}
          />
        </section>
        <section className="panel-section panel-grow">
          <h2 className="section-title">
            Nets
            {net && (
              <button type="button" className="link-button" onClick={() => setNet(null)}>
                Clear
              </button>
            )}
          </h2>
          <ul className="net-list">
            {board?.nets.map((n) => (
              <li key={n.name}>
                <button type="button" className={`net-row kind-${n.kind}${net === n.name ? " is-selected" : ""}`} onClick={() => setNet(net === n.name ? null : n.name)}>
                  <span className="net-dot" />
                  <span className="net-name">{n.name}</span>
                  <span className="net-meta">
                    {n.voltage !== null ? `${n.voltage} V · ` : ""}
                    {n.current} A{n.pour ? " · pour" : ""}
                  </span>
                </button>
              </li>
            ))}
          </ul>
          <h2 className="section-title" style={{ marginTop: 16 }}>
            Parts
          </h2>
          <ul className="part-list">
            {board?.parts
              .filter((p) => p.category !== "mechanical")
              .map((p) => (
                <li key={p.ref} data-tip={`${p.name}${p.lcsc ? ` · LCSC ${p.lcsc}` : ""} · footprint ${p.footprint}`}>
                  <span className="part-ref">{p.ref}</span>
                  <span className="part-name">{p.value || p.name}</span>
                </li>
              ))}
          </ul>
        </section>
      </aside>

      <section className="card viewport board-view">
        <div className="segmented view-switch" role="radiogroup" aria-label="Board view">
          {(
            [
              ["layout", "Layout", Layers],
              ["schematic", "Schematic", Network],
              ["3d", "3D", Box],
            ] as const
          ).map(([id, label, Icon]) => (
            <button key={id} type="button" role="radio" aria-checked={view === id} className={view === id ? "is-active" : ""} onClick={() => setView(id)}>
              <Icon size={14} /> {label}
            </button>
          ))}
        </div>

        {board && view === "layout" && (
          <>
            <Canvas svg={board.svg} net={net} onNet={setNet} marker={marker} layers={layers} board={board.board} kind="layout" />
            <div className="layer-toggles">
              {(["top", "bottom", "silk"] as const).map((layer) => (
                <label key={layer} className={`layer-toggle layer-${layer}`}>
                  <input type="checkbox" checked={layers[layer]} onChange={(e) => setLayers((l) => ({ ...l, [layer]: e.target.checked }))} />
                  {layer === "silk" ? "Silkscreen" : `${layer[0].toUpperCase()}${layer.slice(1)} copper`}
                </label>
              ))}
            </div>
          </>
        )}
        {board && view === "schematic" && (
          <Canvas svg={board.schematic} net={net} onNet={setNet} marker={null} layers={{}} board={board.board} kind="schematic" />
        )}
        {view === "3d" && (
          <>
            <Viewport
              ref={viewport}
              mesh={model?.build.mesh}
              theme={theme}
              selectedFeature={null}
              hoveredFeature={null}
              showEdges
              stressField={null}
              stressMax={0}
              showStress={false}
              onPickFeature={() => undefined}
              onHoverFeature={() => undefined}
            />
            <div className="viewport-toolbar">
              <button type="button" className="icon-button floating" onClick={() => viewport.current?.fit()} aria-label="Fit to view">
                <Maximize2 size={16} />
              </button>
            </div>
            {modelBusy && (
              <div className="viewport-status">
                <span className="status-chip">
                  <LoaderCircle size={14} className="spin" /> Building the board in 3D…
                </span>
              </div>
            )}
          </>
        )}

        {board && (
          <button type="button" className={`verdict-badge is-${passed ? "ok" : "fail"}`} onClick={() => setSide("checks")} data-tip="Design rule check (DRC) and electrical rule check (ERC). Click for every check.">
            <strong>{passed ? "PASS" : "FAIL"}</strong>
            <span>
              {board.checks.errors} errors · {board.checks.warnings} warnings
            </span>
          </button>
        )}
        {busy && (
          <div className="viewport-status">
            <span className="status-chip">
              <LoaderCircle size={14} className="spin" /> Routing and checking…
            </span>
          </div>
        )}
        {notice && (
          <div className="error-banner" role="alert">
            <TriangleAlert size={16} />
            <div>
              <strong>The board program has a problem</strong>
              <p>{notice}</p>
            </div>
            <button type="button" className="link-button" onClick={() => setNotice(null)}>
              Dismiss
            </button>
          </div>
        )}
        {board && (
          <dl className="stats">
            <div>
              <dt>Board</dt>
              <dd>
                {board.board.width} × {board.board.height} mm
              </dd>
            </div>
            <div>
              <dt>Routed</dt>
              <dd>
                {board.routing.routed_nets}/{board.routing.nets} nets
              </dd>
            </div>
            <div>
              <dt>Copper</dt>
              <dd>
                {board.routing.tracks} tracks · {board.routing.vias} vias
              </dd>
            </div>
            <div>
              <dt>Parts</dt>
              <dd>{board.parts.length}</dd>
            </div>
          </dl>
        )}
      </section>

      <aside className="card panel panel-right">
        <div className="tabs" role="tablist">
          <button type="button" role="tab" aria-selected={side === "agents"} className={`tab${side === "agents" ? " is-active" : ""}`} onClick={() => setSide("agents")}>
            <Bot size={15} /> Agents
          </button>
          <button type="button" role="tab" aria-selected={side === "checks"} className={`tab${side === "checks" ? " is-active" : ""}`} onClick={() => setSide("checks")}>
            <Gauge size={15} /> Checks
          </button>
          <button type="button" role="tab" aria-selected={side === "code"} className={`tab${side === "code" ? " is-active" : ""}`} onClick={() => setSide("code")}>
            <Code2 size={15} /> Code
          </button>
          <button type="button" role="tab" aria-selected={side === "trace"} className={`tab${side === "trace" ? " is-active" : ""}`} onClick={() => setSide("trace")}>
            <Activity size={15} /> Trace
            {trace.length > 0 && <span className="tab-count">{trace.length}</span>}
          </button>
        </div>
        <div className="tab-body">
          {side === "agents" && (
            <AgentPanel
              domain="board"
              health={health}
              pinging={pinging}
              onPing={onPing}
              run={agents}
              canChange={Boolean(board)}
              onSubmit={(prompt, change) => agents.start(prompt, change && board ? board.code : null)}
            />
          )}
          {side === "checks" && board && (
            <div className="checks-panel">
              <section className="check-card">
                <header>
                  <Cpu size={16} />
                  <h3>Design and electrical rules</h3>
                </header>
                <p className="hint">
                  The DRC measures the routed copper on its own, without trusting the router; the ERC reads the circuit. Only these
                  decide PASS. Click a finding to see it on the board.
                </p>
                <ul className="board-checks">
                  {errorsFirst.map((c) => (
                    <CheckRow key={c.id} check={c} onFinding={showFinding} />
                  ))}
                </ul>
                <a className="button button-secondary" href={api.boardReportUrl(board.id)} target="_blank" rel="noreferrer">
                  Open board report
                </a>
              </section>
            </div>
          )}
          {side === "code" && board && <CodeView code={board.code} features={[]} selectedFeature={null} errorLine={null} onSelectFeature={() => undefined} />}
          {side === "trace" && <TracePanel events={trace} />}
        </div>
      </aside>
    </main>
  );
}
