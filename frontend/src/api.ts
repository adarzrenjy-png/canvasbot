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
}

export interface Program {
  params: Param[];
  features: Feature[];
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
  features: { id: string; ok: boolean; ms: number }[];
  error?: BuildError;
  stats?: BuildStats;
  mesh?: MeshPayload;
  exports?: Record<string, string>;
  log?: string;
}

export interface PartPayload {
  code: string;
  program: Program | null;
  program_error: { message: string; line: number | null } | null;
  build: Build;
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
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* keep statusText */
    }
    throw new ApiError(detail, response.status);
  }
  return response.json() as Promise<T>;
}

export const api = {
  health: () => request<Health>("/api/health"),
  sample: (name: string) => request<PartPayload>(`/api/samples/${encodeURIComponent(name)}`),
  build: (code: string) =>
    request<PartPayload>("/api/parts/build", { method: "POST", body: JSON.stringify({ code }) }),
  setParams: (code: string, updates: Record<string, number>) =>
    request<PartPayload>("/api/parts/params", {
      method: "POST",
      body: JSON.stringify({ code, updates }),
    }),
  setLock: (code: string, name: string, locked: boolean) =>
    request<Omit<PartPayload, "build">>("/api/parts/lock", {
      method: "POST",
      body: JSON.stringify({ code, name, locked }),
    }),
  ping: () => request<PingResult>("/api/ai/ping", { method: "POST" }),
  downloadUrl: (buildId: string, kind: "step" | "stl" | "py") =>
    `/api/builds/${buildId}/download/${kind}`,
};
