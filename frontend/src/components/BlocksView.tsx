import { ArrowDown, ArrowUp, Eye, EyeOff, GripVertical, Shapes, TriangleAlert } from "lucide-react";
import { Fragment, useEffect, useMemo, useState } from "react";
import type { Build, Feature, Param } from "../api";
import { ICONS, KIND_TIPS } from "../lib/featureKinds";
import { renderStepThumbnails } from "../lib/thumbnails";

interface Props {
  features: Feature[];
  params: Param[];
  build: Build | undefined;
  selected: string | null;
  busy: boolean;
  theme: "light" | "dark";
  onSelect: (id: string | null) => void;
  onReorder: (order: string[]) => void;
  onToggle: (id: string, enabled: boolean) => void;
  onCommitParam: (name: string, value: number) => void;
}

function InlineParam({ param, busy, onCommit }: { param: Param; busy: boolean; onCommit: Props["onCommitParam"] }) {
  const [draft, setDraft] = useState(String(param.value));
  useEffect(() => setDraft(String(param.value)), [param.value]);
  const commit = () => {
    const value = Number(draft);
    const ok =
      draft.trim() !== "" &&
      Number.isFinite(value) &&
      (param.min === null || value >= param.min) &&
      (param.max === null || value <= param.max);
    if (!ok) setDraft(String(param.value));
    else if (value !== param.value) onCommit(param.name, value);
  };
  return (
    <label className={`inline-param${param.locked ? " is-locked" : ""}`} data-tip={param.description}>
      <span className="inline-param-name">{param.name}</span>
      <input
        type="number"
        value={draft}
        disabled={busy}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
        onClick={(e) => e.stopPropagation()}
      />
      <span className="inline-param-unit">{param.unit}</span>
    </label>
  );
}

/** The description, with parameter names shown as `NAME = value unit` chips. */
function Described({ text, params }: { text: string; params: Map<string, Param> }) {
  const parts = text.split(/\b([A-Z][A-Z0-9_]{2,})\b/);
  return (
    <p className="block-desc">
      {parts.map((part, i) => {
        const param = i % 2 === 1 ? params.get(part) : undefined;
        return param ? (
          <span key={i} className="param-chip" data-tip={param.description}>
            {param.value} {param.unit}
          </span>
        ) : (
          <Fragment key={i}>{part}</Fragment>
        );
      })}
    </p>
  );
}

export function BlocksView(props: Props) {
  const { features, build, selected } = props;
  const [thumbs, setThumbs] = useState<Map<string, string>>(new Map());
  const [dragging, setDragging] = useState<string | null>(null);
  const paramMap = useMemo(() => new Map(props.params.map((p) => [p.name, p])), [props.params]);
  const runs = useMemo(() => new Map(build?.features.map((f) => [f.id, f]) ?? []), [build]);

  useEffect(() => {
    if (!build?.steps) return;
    // Let the panel paint first; thumbnails take a few milliseconds each.
    const handle = window.setTimeout(() => setThumbs(renderStepThumbnails(build.steps!)), 30);
    return () => window.clearTimeout(handle);
  }, [build, props.theme]);

  const move = (id: string, delta: number) => {
    const order = features.map((f) => f.id);
    const from = order.indexOf(id);
    const to = from + delta;
    if (to < 0 || to >= order.length) return;
    order.splice(to, 0, order.splice(from, 1)[0]);
    props.onReorder(order);
  };

  const dropOn = (target: string) => {
    if (!dragging || dragging === target) return;
    const order = features.map((f) => f.id).filter((id) => id !== dragging);
    order.splice(order.indexOf(target), 0, dragging);
    setDragging(null);
    props.onReorder(order);
  };

  return (
    <ol className="blocks" aria-label="Feature blocks">
      <li className="blocks-intro">
        Each block is one step of the part, run top to bottom. Blue in a picture is what that block adds. Drag blocks to
        reorder them, or switch one off to see the part without it.
      </li>
      {features.map((feature, index) => {
        const Icon = ICONS[feature.kind] ?? Shapes;
        const run = runs.get(feature.id);
        const failed = run && !run.ok;
        const notReached = build && !build.ok && !run;
        const used = feature.params.map((name) => paramMap.get(name)).filter((p): p is Param => !!p);
        const thumb = thumbs.get(feature.id);
        return (
          <li
            key={feature.id}
            className={`block kind-${feature.kind}${selected === feature.id ? " is-selected" : ""}${feature.enabled ? "" : " is-off"}${failed ? " is-failed" : ""}${dragging === feature.id ? " is-dragging" : ""}`}
            draggable={!props.busy}
            onDragStart={(e) => {
              setDragging(feature.id);
              e.dataTransfer.effectAllowed = "move";
            }}
            onDragEnd={() => setDragging(null)}
            onDragOver={(e) => e.preventDefault()}
            onDrop={() => dropOn(feature.id)}
            onClick={() => props.onSelect(selected === feature.id ? null : feature.id)}
          >
            <div className="block-rail">
              <GripVertical size={14} className="block-grip" />
              <span className="block-step">{index + 1}</span>
            </div>
            <div className="block-thumb">
              {thumb && feature.enabled ? (
                <img src={thumb} alt={`The part after ${feature.label}`} />
              ) : (
                <span className="block-thumb-empty">{feature.enabled ? (failed || notReached ? "Not built" : "…") : "Off"}</span>
              )}
            </div>
            <div className="block-body">
              <span className="block-kind" data-tip={KIND_TIPS[feature.kind]}>
                <Icon size={12} strokeWidth={2.2} />
                {feature.kind}
              </span>
              <header>
                <h4 title={feature.label}>{feature.label}</h4>
                <span className="block-actions" onClick={(e) => e.stopPropagation()}>
                  <button type="button" className="icon-button small" aria-label="Move up" disabled={index === 0 || props.busy} onClick={() => move(feature.id, -1)}>
                    <ArrowUp size={14} />
                  </button>
                  <button type="button" className="icon-button small" aria-label="Move down" disabled={index === features.length - 1 || props.busy} onClick={() => move(feature.id, 1)}>
                    <ArrowDown size={14} />
                  </button>
                  <button
                    type="button"
                    className={`icon-button small${feature.enabled ? "" : " is-on"}`}
                    aria-label={feature.enabled ? "Switch off" : "Switch on"}
                    data-tip={feature.enabled ? "Switch this block off (suppress it)" : "Switch this block back on"}
                    disabled={props.busy}
                    onClick={() => props.onToggle(feature.id, !feature.enabled)}
                  >
                    {feature.enabled ? <Eye size={14} /> : <EyeOff size={14} />}
                  </button>
                </span>
              </header>
              {feature.description ? (
                <Described text={feature.description} params={paramMap} />
              ) : (
                <p className="block-desc muted">{KIND_TIPS[feature.kind] ?? "No description yet."}</p>
              )}
              {used.length > 0 && feature.enabled && (
                <div className="block-params" onClick={(e) => e.stopPropagation()}>
                  {used.map((p) => (
                    <InlineParam key={p.name} param={p} busy={props.busy} onCommit={props.onCommitParam} />
                  ))}
                </div>
              )}
              {failed && (
                <p className="block-error">
                  <TriangleAlert size={13} /> {build?.error?.message}
                </p>
              )}
              {!feature.enabled && <p className="block-note">Switched off: skipped when the part is built.</p>}
              {notReached && feature.enabled && <p className="block-note">Not reached: an earlier block failed.</p>}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
