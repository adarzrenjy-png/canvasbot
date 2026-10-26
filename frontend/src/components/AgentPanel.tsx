import { CircleCheck, CircleDashed, CircleX, ImagePlus, LoaderCircle, Mic, Plug, Send, Sparkles, Square } from "lucide-react";
import { useState } from "react";
import type { AgentCheck, AgentDomain, AgentResult, Health } from "../api";
import { type AgentRun, TEAM } from "../lib/useAgentRun";

export const EXAMPLE_PROMPTS: Record<AgentDomain, string[]> = {
  part: [
    "A motor mount for a 2212 drone motor that survives a 5g crash load",
    "An L-bracket holding a 2 kg camera 80 mm off a wall, printed in PETG",
    "A clamp for a 25 mm FSAE roll-hoop tube with an M6 tab for a harness mount",
  ],
  board: [
    "A Raspberry Pi Pico board that drives four hobby servos from a 5 V supply",
    "A 3.3 V regulator breakout with a power LED and a 4-pin header, fed from 5 V",
    "A Pico board with two buttons, a status LED and a screw terminal for 5 V in",
  ],
};

const COPY: Record<AgentDomain, { title: string; body: string; placeholder: string; change: string }> = {
  part: {
    title: "Describe a part",
    body: "Say what it holds, what loads it sees, and how you will make it. The agents plan it, model it, and check it before you see it.",
    placeholder: "e.g. a bracket that holds a 2 kg camera 80 mm off a wall",
    change: "Change this part",
  },
  board: {
    title: "Describe a board",
    body: "Say what it powers, what it connects, and the supply. The agents pick parts, place and route them, and run every rule check.",
    placeholder: "e.g. a Pico board that drives two servos from 5 V",
    change: "Change this board",
  },
};

interface Props {
  domain: AgentDomain;
  health: Health | null;
  pinging: boolean;
  onPing: () => void;
  run: AgentRun;
  canChange: boolean;
  onSubmit: (prompt: string, change: boolean) => void;
}

const VERDICT_TEXT = {
  pass: "PASS",
  fail: "FAIL",
  unverified: "NOT LOAD-TESTED",
};

function unverifiedReason(result: AgentResult): string {
  const fea = result.verdict.checks.find((c) => c.id === "fea") as AgentCheck | undefined;
  if (!fea || fea.status === "skip") {
    return `It builds and passes every geometry check, but FEA did not run${fea?.message ? ` (${fea.message})` : ""}, so its strength is not shown.`;
  }
  return `It builds and passes every geometry check. FEA ran (${fea.message}). Jig only calls a part PASS when that answer can be trusted, so check the stress picture before relying on it.`;
}

export function AgentPanel({ domain, health, pinging, onPing, run, canChange, onSubmit }: Props) {
  const [prompt, setPrompt] = useState("");
  const [change, setChange] = useState(false);
  const ready = health?.ai.ready ?? false;
  const copy = COPY[domain];
  const submit = () => {
    if (prompt.trim().length >= 3 && ready && !run.running) onSubmit(prompt.trim(), change && canChange);
  };
  const started = run.running || run.result || run.error;
  const result = run.result;

  return (
    <div className="agent-panel">
      <div className="agent-hero">
        <span className="agent-hero-icon">
          <Sparkles size={18} />
        </span>
        <div>
          <h2>{copy.title}</h2>
          <p>{copy.body}</p>
        </div>
      </div>

      {!started && (
        <div className="examples">
          {EXAMPLE_PROMPTS[domain].map((example) => (
            <button key={example} type="button" className="example-chip" onClick={() => setPrompt(example)}>
              {example}
            </button>
          ))}
        </div>
      )}

      <div className="composer">
        <textarea
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submit();
          }}
          placeholder={copy.placeholder}
          rows={3}
          aria-label={copy.title}
          disabled={run.running}
        />
        <div className="composer-bar">
          <button type="button" className="icon-button" disabled data-tip="Voice input (push to talk) arrives in a later milestone">
            <Mic size={16} />
          </button>
          <button type="button" className="icon-button" disabled data-tip="Photo input (sketch or mounting spot) arrives in a later milestone">
            <ImagePlus size={16} />
          </button>
          {canChange && (
            <label className="composer-toggle" data-tip="On: the agents edit what is on screen and keep your locked parameters. Off: they start a new design.">
              <input type="checkbox" checked={change} onChange={(e) => setChange(e.target.checked)} disabled={run.running} />
              {copy.change}
            </label>
          )}
          <span className="composer-spacer" />
          {run.running ? (
            <button type="button" className="button button-secondary" onClick={run.stop}>
              <Square size={13} /> Stop
            </button>
          ) : (
            <button type="button" className="button button-primary" onClick={submit} disabled={!ready || prompt.trim().length < 3} data-tip={ready ? "Ctrl/Cmd+Enter" : "Add MODEL_API_KEY to .env first"}>
              <Send size={15} /> Build
            </button>
          )}
        </div>
      </div>

      {started && (
        <section className="team-card" aria-live="polite">
          <header>
            <h3>Agent team</h3>
            <span className="team-cost" data-tip="Estimated Meta API spend for this request">
              ${run.cost.toFixed(4)}
            </span>
          </header>
          <ol className="team">
            {TEAM[domain].map(({ agent, job }) => {
              const member = run.team[agent];
              const state = member?.state ?? "idle";
              const Icon = state === "running" ? LoaderCircle : state === "done" ? CircleCheck : state === "fail" ? CircleX : CircleDashed;
              return (
                <li key={agent} className={`team-member is-${state}`}>
                  <Icon size={16} className={state === "running" ? "spin" : undefined} />
                  <div>
                    <div className="team-head">
                      <strong>{agent}</strong>
                      {member?.model && <span className="team-model">{member.model}</span>}
                    </div>
                    <p>{state === "idle" ? job : member?.last}</p>
                  </div>
                </li>
              );
            })}
          </ol>
          {run.error && (
            <p className="team-error" role="alert">
              {run.error}
            </p>
          )}
        </section>
      )}

      {result && (
        <section className={`result-card is-${result.verdict.status}`}>
          <header>
            <strong>{VERDICT_TEXT[result.verdict.status]}</strong>
            <span>
              {result.verdict.errors} errors · {result.verdict.warnings} warnings · {result.rounds} fix round{result.rounds === 1 ? "" : "s"}
            </span>
          </header>
          {result.plan && (
            <p>
              <b>{result.plan.name}.</b> {result.plan.summary}
            </p>
          )}
          {result.verdict.status === "unverified" && <p className="hint">{unverifiedReason(result)}</p>}
          {result.review && result.review.issues.length > 0 && (
            <div>
              <h4>Review notes</h4>
              <ul>
                {result.review.issues.map((issue, i) => (
                  <li key={i}>
                    <b>{issue.where}:</b> {issue.message}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {result.plan && result.plan.assumptions.length > 0 && (
            <div>
              <h4>Assumptions</h4>
              <ul>
                {result.plan.assumptions.map((a, i) => (
                  <li key={i}>{a}</li>
                ))}
              </ul>
            </div>
          )}
          <p className="hint">The verdict comes from Jig's checks on the real geometry, never from a model. Every step is in the Trace tab.</p>
        </section>
      )}

      {!ready && (
        <div className="connection-card">
          <div>
            <h3>Meta Model API</h3>
            <p>No key yet. Add MODEL_API_KEY to the .env file next to README.md, then restart Jig.</p>
          </div>
        </div>
      )}
      {ready && !started && (
        <div className="connection-card is-ready">
          <div>
            <h3>Meta Model API</h3>
            <p>Key found. Send one tiny test call to confirm the connection (costs a fraction of a cent).</p>
          </div>
          <button type="button" className="button button-secondary" onClick={onPing} disabled={pinging}>
            {pinging ? <LoaderCircle size={15} className="spin" /> : <Plug size={15} />}
            Test connection
          </button>
        </div>
      )}
    </div>
  );
}
