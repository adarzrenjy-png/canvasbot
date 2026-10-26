import { useCallback, useRef, useState } from "react";
import { api, ApiError, type AgentDomain, type AgentEvent, type AgentResult, type BoardPayload, type PartPayload } from "../api";
import type { TraceEvent } from "../components/TracePanel";

export const TEAM: Record<AgentDomain, { agent: string; job: string }[]> = {
  part: [
    { agent: "Planner", job: "Turns your request into features, parameters and a load case" },
    { agent: "Modeler", job: "Writes the part as build123d code" },
    { agent: "Builder", job: "Builds it in a sandbox and measures it" },
    { agent: "Verifier", job: "Checks it with code, then reviews it against your request" },
    { agent: "FEA Critic", job: "Runs the load case with CalculiX" },
    { agent: "Fixer", job: "Repairs whatever failed, until it passes" },
  ],
  board: [
    { agent: "Planner", job: "Picks parts and nets from the library" },
    { agent: "Modeler", job: "Writes the board program and places parts" },
    { agent: "Router", job: "Routes copper sized for each net's current" },
    { agent: "Verifier", job: "Runs DRC and ERC, then reviews it against your request" },
    { agent: "Fixer", job: "Repairs whatever failed, until it passes" },
  ],
};

export interface Member {
  state: "idle" | "running" | "done" | "fail";
  model?: string;
  calls: number;
  cost: number;
  last?: string;
}

export interface AgentHandlers {
  onTrace: (event: Omit<TraceEvent, "id" | "at">) => void;
  onPart?: (part: PartPayload) => void;
  onBoard?: (board: BoardPayload) => void;
  onResult: (result: AgentResult) => void;
  onSpend?: () => void;
}

export function useAgentRun(domain: AgentDomain, handlers: AgentHandlers) {
  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState<{ agent: string; title: string } | null>(null);
  const [team, setTeam] = useState<Record<string, Member>>({});
  const [result, setResult] = useState<AgentResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [cost, setCost] = useState(0);
  const abort = useRef<AbortController | null>(null);
  const live = useRef(handlers);
  live.current = handlers;

  const update = (agent: string, change: (m: Member) => Partial<Member>) =>
    setTeam((t) => {
      const member = t[agent] ?? { state: "idle", calls: 0, cost: 0 };
      return { ...t, [agent]: { ...member, ...change(member) } };
    });

  const settle = () =>
    setTeam((t) => Object.fromEntries(Object.entries(t).map(([k, m]) => [k, m.state === "running" ? { ...m, state: "done" } : m])));

  const onEvent = useCallback((event: AgentEvent) => {
    const h = live.current;
    switch (event.type) {
      case "progress":
        setProgress(event);
        setTeam((t) => {
          const next = Object.fromEntries(Object.entries(t).map(([k, m]) => [k, m.state === "running" ? { ...m, state: "done" as const } : m]));
          const member = next[event.agent] ?? { state: "idle", calls: 0, cost: 0 };
          return { ...next, [event.agent]: { ...member, state: "running", last: event.title } };
        });
        break;
      case "call":
        update(event.agent, (m) => ({
          calls: m.calls + 1,
          cost: m.cost + event.cost_usd,
          model: `${event.model}${event.fell_back ? " (fallback)" : ""}`,
        }));
        setCost((c) => c + event.cost_usd);
        h.onSpend?.();
        break;
      case "trace":
        update(event.agent, (m) => ({ last: event.title, state: event.status === "fail" ? "fail" : m.state === "fail" ? "done" : m.state }));
        h.onTrace({ agent: event.agent, kind: event.kind, status: event.status, title: event.title, detail: event.detail || undefined });
        break;
      case "part":
        h.onPart?.(event.part);
        break;
      case "board":
        h.onBoard?.(event.board);
        break;
      case "result":
        settle();
        setResult(event);
        h.onResult(event);
        break;
      case "error":
        settle();
        setError(event.message);
        h.onTrace({ agent: "Agents", kind: "system", status: "fail", title: "The agent run stopped", detail: event.message });
        break;
    }
  }, []);

  const start = useCallback(
    async (prompt: string, code: string | null) => {
      abort.current?.abort();
      const controller = new AbortController();
      abort.current = controller;
      setRunning(true);
      setResult(null);
      setError(null);
      setTeam({});
      setCost(0);
      setProgress({ agent: "Planner", title: "Starting" });
      live.current.onTrace({ agent: "You", kind: "system", status: "info", title: prompt, detail: code ? "Change the current design" : "New design" });
      try {
        await api.runAgents({ domain, prompt, code }, onEvent, controller.signal);
        if (controller.signal.aborted) {
          setError("Stopped. The last design the agents built is still on screen.");
        }
      } catch (e) {
        setError(e instanceof ApiError ? e.message : String(e));
      } finally {
        settle();
        setProgress(null);
        setRunning(false);
        live.current.onSpend?.();
      }
    },
    [domain, onEvent],
  );

  const stop = useCallback(() => abort.current?.abort(), []);

  return { running, progress, team, result, error, cost, start, stop };
}

export type AgentRun = ReturnType<typeof useAgentRun>;
