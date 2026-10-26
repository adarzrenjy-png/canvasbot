// Typed client for the Jig backend. Shapes mirror backend/src/jig/app.py.

export interface Param {
  name: string;
  value: number;
  unit: string;
  description: string;
  min: number | null;
  max: number | null;
  locked: boolean;
  is_int: boolean;
  line: number;
  used_by: string[];
}

export interface Feature {
  id: string;
  kind: string;
  label: string;
  line_start: number;
  line_end: number;
  params: string[];
  description: string;
  enabled: boolean;
}

export interface Program {
  params: Param[];
  features: Feature[];
  analysis: Record<string, unknown> | null;
  material: { id: string; name: string; density_g_cm3: number; allowable_mpa: number } | null;
}

export interface BuildError {
  stage: string;
  message: string;
  line: number | null;
  feature: string | null;
}

export interface MeshFace {
  start: number;
  count: number;
  feature: string | null;
}

export interface MeshPayload {
  positions: string;
  indices: string;
  edges: string;
  faces: MeshFace[];
  triangles: number;
}

export interface BuildStats {
  valid: boolean;
  solids: number;
  faces: number;
  edges: number;
  volume_mm3: number;
  area_mm2: number;
  bbox: { min: number[]; max: number[]; size: number[] };
}

export interface Build {
  id: string;
  ok: boolean;
  elapsed_ms: number;
  features: { id: string; ok: boolean; ms: number; skipped?: boolean }[];
  error?: BuildError;
  stats?: BuildStats;
  mesh?: MeshPayload;
  exports?: Record<string, string>;
  log?: string;
  steps?: { id: string; mesh: MeshPayload | null }[];
}

export interface PartPayload {
  code: string;
  program: Program | null;
  program_error: { message: string; line: number | null } | null;
  build: Build;
}

export interface FeaField {
  positions: string;
  indices: string;
  von_mises: string;
  displacement: string;
  triangles: number;
}

export interface FeaCheck {
  id: string;
  label: string;
  value: number;
  limit: number;
  pass: boolean;
  detail: string;
}

export interface FeaLevel {
  mesh_size_mm: number;
  nodes: number;
  elements: number;
  solve_s: number;
  max_displacement_mm: number;
  peak_von_mises_mpa: number;
}

export type FeaStatus = "pass" | "fail" | "unconverged" | "invalid" | "error" | "unavailable" | "no_load_case";

export interface FeaResult {
  ok: boolean;
  status: FeaStatus;
  error?: string;
  safety_factor?: number;
  checks?: FeaCheck[];
  material?: { id: string; name: string; allowable_mpa: number; allowable_basis: string };
  fixtures?: { name: string; type: string; selector: string; faces: number[] }[];
  loads?: { name: string; selector: string; force_n: number[]; faces: number[] }[];
  levels?: FeaLevel[];
  convergence?: { stress_change: number; displacement_change: number; converged: boolean };
  equilibrium?: { error: number; ok: boolean };
  result?: {
    peak_von_mises_mpa: number;
    peak_at: number[];
    raw_peak_von_mises_mpa: number;
    max_displacement_mm: number;
  };
  field?: FeaField;
}

export interface BoardFinding {
  check: string;
  severity: "error" | "warning";
  message: string;
  at: [number, number] | null;
  nets: string[];
}

export interface BoardCheck {
  id: string;
  label: string;
  kind: "drc" | "erc";
  status: "pass" | "fail" | "warn";
  looked_at: number;
  findings: BoardFinding[];
}

export interface BoardNet {
  name: string;
  kind: "signal" | "power" | "ground";
  voltage: number | null;
  current: number;
  pins: string[];
  pour: string | null;
  ipc_width_mm: number;
  widest_mm: number | null;
  busiest: { current: number; width: number; sized_by: string; capacity: number } | null;
  length_mm: number;
  vias: number;
}

export interface BoardPart {
  ref: string;
  part: string;
  name: string;
  value: string;
  category: string;
  x: number;
  y: number;
  rotation: number;
  footprint: string;
  lcsc: string | null;
  label: string;
}

export interface BoardPayload {
  id: string;
  code: string;
  name: string;
  description: string;
  params: Param[];
  board: { width: number; height: number; thickness: number; layers: number; copper_oz: number };
  rules: Record<string, number>;
  parts: BoardPart[];
  nets: BoardNet[];
  routing: {
    tracks: number;
    vias: number;
    length_mm: number;
    passes: number;
    seconds: number;
    unrouted: { net: string; from: string; to: string }[];
    routed_nets: number;
    nets: number;
  };
  checks: { status: "pass" | "fail"; errors: number; warnings: number; checks: BoardCheck[] };
  svg: string;
  schematic: string;
  bom: Record<string, string | number>[];
  fab_files: string[];
}

export interface SessionSummary {
  spent_usd: number;
  budget_usd: number;
  remaining_usd: number;
  calls: number;
  warning: boolean;
  exhausted: boolean;
}

export interface Health {
  version: string;
  ai: {
    ready: boolean;
    providers: Record<string, { configured: boolean; key_env: string }>;
  };
  fea: {
    available: boolean;
    path: string | null;
    version: string | null;
    message: string;
    install_hint: string;
  };
  session: SessionSummary;
}

export interface PingResult {
  reply: string;
  provider: string;
  model: string;
  latency_ms: number;
  cost_usd: number;
  session: SessionSummary;
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    });
  } catch {
    throw new ApiError("Can't reach the Jig backend. Is it running?", 0);
  }
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail =
        typeof body.detail === "string"
          ? body.detail
          : typeof body.detail?.message === "string"
            ? `${body.detail.message}${body.detail.line ? ` (line ${body.detail.line})` : ""}`
            : JSON.stringify(body.detail);
    } catch {
      /* keep statusText */
    }
    throw new ApiError(detail, response.status);
  }
  return response.json() as Promise<T>;
}

export type AgentDomain = "part" | "board";

export interface AgentCheck {
  id: string;
  label: string;
  status: "pass" | "fail" | "warn" | "skip";
  message: string;
  line: number | null;
  feature: string | null;
}

export interface AgentReview {
  matches_request: boolean | null;
  summary: string;
  issues: { severity: "blocking" | "minor"; where: string; message: string }[];
}

export interface AgentResult {
  type: "result";
  domain: AgentDomain;
  verdict: { status: "pass" | "fail" | "unverified"; errors: number; warnings: number; checks: (AgentCheck | BoardCheck)[] };
  review: AgentReview | null;
  plan: { name: string; summary: string; assumptions: string[] } | null;
  rounds: number;
  cost_usd: number;
  part?: PartPayload;
  fea?: FeaResult | null;
  board?: BoardPayload;
}

export type AgentEvent =
  | { type: "progress"; agent: string; title: string }
  | { type: "trace"; agent: string; kind: "agent" | "check" | "system"; status: "ok" | "fail" | "info"; title: string; detail: string }
  | { type: "call"; agent: string; model: string; provider: string; fell_back: boolean; cost_usd: number; latency_ms: number; session: SessionSummary }
  | { type: "part"; part: PartPayload }
  | { type: "board"; board: BoardPayload }
  | AgentResult
  | { type: "error"; message: string };

/** Run the agent team; calls onEvent for every streamed event (one JSON object per line). */
async function runAgents(
  body: { domain: AgentDomain; prompt: string; code?: string | null; fea?: boolean },
  onEvent: (event: AgentEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  let response: Response;
  try {
    response = await fetch("/api/agents/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal,
    });
  } catch (error) {
    if (signal?.aborted) return;
    throw new ApiError("Can't reach the Jig backend. Is it running?", 0);
  }
  if (!response.ok || !response.body) {
    throw new ApiError(`The agent run could not start (HTTP ${response.status})`, response.status);
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    let chunk: ReadableStreamReadResult<Uint8Array>;
    try {
      chunk = await reader.read();
    } catch {
      if (signal?.aborted) return;
      throw new ApiError("The connection to the agents dropped", 0);
    }
    if (chunk.done) break;
    buffer += decoder.decode(chunk.value, { stream: true });
    let newline: number;
    while ((newline = buffer.indexOf("\n")) >= 0) {
      const line = buffer.slice(0, newline).trim();
      buffer = buffer.slice(newline + 1);
      if (line) onEvent(JSON.parse(line) as AgentEvent);
    }
  }
  if (buffer.trim()) onEvent(JSON.parse(buffer) as AgentEvent);
}

export const api = {
  runAgents,
  health: () => request<Health>("/api/health"),
  sample: (name: string) => request<PartPayload>(`/api/samples/${encodeURIComponent(name)}`),
  build: (code: string) =>
    request<PartPayload>("/api/parts/build", { method: "POST", body: JSON.stringify({ code }) }),
  setParams: (code: string, updates: Record<string, number>) =>
    request<PartPayload>("/api/parts/params", {
      method: "POST",
      body: JSON.stringify({ code, updates }),
    }),
  setFeatureOrder: (code: string, order: string[]) =>
    request<PartPayload>("/api/parts/features/order", { method: "POST", body: JSON.stringify({ code, order }) }),
  setFeatureEnabled: (code: string, feature: string, enabled: boolean) =>
    request<PartPayload>("/api/parts/features/enabled", {
      method: "POST",
      body: JSON.stringify({ code, feature, enabled }),
    }),
  setLock: (code: string, name: string, locked: boolean) =>
    request<Omit<PartPayload, "build">>("/api/parts/lock", {
      method: "POST",
      body: JSON.stringify({ code, name, locked }),
    }),
  ping: () => request<PingResult>("/api/ai/ping", { method: "POST" }),
  analyze: (code: string, buildId: string | null) =>
    request<PartPayload & { fea: FeaResult }>("/api/parts/analyze", {
      method: "POST",
      body: JSON.stringify({ code, build_id: buildId }),
    }),
  reportUrl: (buildId: string) => `/api/builds/${buildId}/report`,
  boardSample: (name: string) => request<BoardPayload>(`/api/boards/samples/${encodeURIComponent(name)}`),
  designBoard: (code: string) =>
    request<BoardPayload>("/api/boards/design", { method: "POST", body: JSON.stringify({ code }) }),
  boardParams: (code: string, updates: Record<string, number>) =>
    request<BoardPayload>("/api/boards/params", { method: "POST", body: JSON.stringify({ code, updates }) }),
  boardLock: (code: string, name: string, locked: boolean) =>
    request<BoardPayload>("/api/boards/lock", { method: "POST", body: JSON.stringify({ code, name, locked }) }),
  boardModel: (boardId: string) => request<PartPayload>(`/api/boards/${boardId}/model3d`, { method: "POST" }),
  boardFabUrl: (boardId: string) => `/api/boards/${boardId}/fab.zip`,
  boardReportUrl: (boardId: string) => `/api/boards/${boardId}/report`,
  boardSourceUrl: (boardId: string) => `/api/boards/${boardId}/board.py`,
  downloadUrl: (buildId: string, kind: "step" | "stl" | "py") =>
    `/api/builds/${buildId}/download/${kind}`,
};
