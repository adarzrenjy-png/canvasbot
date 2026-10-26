import { ImagePlus, LoaderCircle, Mic, Plug, Send, Sparkles } from "lucide-react";
import { useState } from "react";
import type { Health } from "../api";

export const EXAMPLE_PROMPTS = [
  "A motor mount for a 2212 drone motor that survives a 5g crash load",
  "An L-bracket holding a 2 kg camera 80 mm off a wall, printed in PETG",
  "A clamp for a 25 mm FSAE roll-hoop tube with an M6 tab for a harness mount",
];

interface Props {
  health: Health | null;
  pinging: boolean;
  onPing: () => void;
}

export function AgentPanel({ health, pinging, onPing }: Props) {
  const [prompt, setPrompt] = useState("");
  const ready = health?.ai.ready ?? false;
  return (
    <div className="agent-panel">
      <div className="agent-hero">
        <span className="agent-hero-icon">
          <Sparkles size={18} />
        </span>
        <div>
          <h2>Describe a part</h2>
          <p>
            Say what it holds, what loads it sees, and how you will make it. The agents plan it, model
            it, and check it before you see it.
          </p>
        </div>
      </div>

      <div className="examples">
        {EXAMPLE_PROMPTS.map((example) => (
          <button key={example} type="button" className="example-chip" onClick={() => setPrompt(example)}>
            {example}
          </button>
        ))}
      </div>

      <div className="composer">
        <textarea
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          placeholder="e.g. a bracket that holds a 2 kg camera 80 mm off a wall"
          rows={3}
          aria-label="Describe your part"
        />
        <div className="composer-bar">
          <button type="button" className="icon-button" disabled data-tip="Voice input (push to talk) arrives in a later milestone">
            <Mic size={16} />
          </button>
          <button type="button" className="icon-button" disabled data-tip="Photo input (sketch or mounting spot) arrives in a later milestone">
            <ImagePlus size={16} />
          </button>
          <span className="composer-note">The agent team arrives in the next milestone.</span>
          <button type="button" className="button button-primary" disabled>
            <Send size={15} /> Build
          </button>
        </div>
      </div>

      <div className={`connection-card${ready ? " is-ready" : ""}`}>
        <div>
          <h3>Meta Model API</h3>
          <p>
            {ready
              ? "Key found. Send one tiny test call to confirm the connection (costs a fraction of a cent)."
              : "No key yet. Add MODEL_API_KEY to the .env file next to README.md, then restart Jig."}
          </p>
        </div>
        <button type="button" className="button button-secondary" onClick={onPing} disabled={pinging || !ready}>
          {pinging ? <LoaderCircle size={15} className="spin" /> : <Plug size={15} />}
          Test connection
        </button>
      </div>
    </div>
  );
}
