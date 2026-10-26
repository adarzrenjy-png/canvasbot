import { Lock, LockOpen } from "lucide-react";
import { useEffect, useState } from "react";
import type { Param } from "../api";

interface Props {
  params: Param[];
  selectedFeature: string | null;
  busy: boolean;
  onCommit: (name: string, value: number) => void;
  onToggleLock: (name: string, locked: boolean) => void;
}

function ParamRow({ param, busy, onCommit, onToggleLock }: {
  param: Param;
  busy: boolean;
  onCommit: Props["onCommit"];
  onToggleLock: Props["onToggleLock"];
}) {
  const [draft, setDraft] = useState(String(param.value));
  useEffect(() => setDraft(String(param.value)), [param.value]);

  const parsed = Number(draft);
  const outOfRange =
    Number.isFinite(parsed) &&
    ((param.min !== null && parsed < param.min) || (param.max !== null && parsed > param.max));
  const invalid = draft.trim() === "" || !Number.isFinite(parsed) || outOfRange;

  const commit = () => {
    if (invalid) {
      setDraft(String(param.value));
      return;
    }
    if (parsed !== param.value) onCommit(param.name, param.is_int ? Math.round(parsed) : parsed);
  };

  const step = param.is_int ? 1 : param.value >= 20 ? 1 : 0.5;
  const range = param.min !== null || param.max !== null ? `Allowed ${param.min ?? "–"} to ${param.max ?? "–"} ${param.unit}` : "";
  return (
    <div className={`param-row${param.locked ? " is-locked" : ""}`}>
      <label className="param-label" htmlFor={`param-${param.name}`} data-tip={[param.description, range].filter(Boolean).join(". ")}>
        <span className="param-desc">{param.description || param.name}</span>
        <code className="param-name">{param.name}</code>
      </label>
      <div className={`param-input${invalid ? " is-invalid" : ""}`}>
        <input
          id={`param-${param.name}`}
          type="number"
          inputMode="decimal"
          step={step}
          min={param.min ?? undefined}
          max={param.max ?? undefined}
          value={draft}
          disabled={busy}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === "Enter") (e.target as HTMLInputElement).blur();
            if (e.key === "Escape") setDraft(String(param.value));
          }}
        />
        <span className="param-unit">{param.unit}</span>
      </div>
      <button
        type="button"
        className={`icon-button lock-button${param.locked ? " is-on" : ""}`}
        onClick={() => onToggleLock(param.name, !param.locked)}
        aria-pressed={param.locked}
        data-tip={param.locked ? "Locked: agents will not change this value. Click to unlock." : "Lock this value so agents never change it."}
      >
        {param.locked ? <Lock size={14} /> : <LockOpen size={14} />}
      </button>
    </div>
  );
}

export function ParamsPanel({ params, selectedFeature, busy, onCommit, onToggleLock }: Props) {
  const visible = selectedFeature ? params.filter((p) => p.used_by.includes(selectedFeature)) : params;
  if (params.length === 0) return <p className="empty-note">This part has no parameters yet.</p>;
  return (
    <div className="params">
      {selectedFeature && (
        <p className="params-filter">
          Showing the {visible.length} parameter{visible.length === 1 ? "" : "s"} this feature uses.
        </p>
      )}
      {visible.map((param) => (
        <ParamRow
          key={param.name}
          param={param}
          busy={busy}
          onCommit={onCommit}
          onToggleLock={onToggleLock}
        />
      ))}
    </div>
  );
}
