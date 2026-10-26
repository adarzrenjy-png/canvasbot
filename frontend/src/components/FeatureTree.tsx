import { Shapes, TriangleAlert } from "lucide-react";
import type { Build, Feature } from "../api";
import { ICONS, KIND_TIPS } from "../lib/featureKinds";

interface Props {
  features: Feature[];
  build: Build | undefined;
  selected: string | null;
  hovered: string | null;
  onSelect: (id: string | null) => void;
  onHover: (id: string | null) => void;
}

export function FeatureTree({ features, build, selected, hovered, onSelect, onHover }: Props) {
  const status = new Map(build?.features.map((f) => [f.id, f]) ?? []);
  return (
    <ol className="feature-tree" aria-label="Feature tree">
      {features.map((feature, index) => {
        const Icon = ICONS[feature.kind] ?? Shapes;
        const run = status.get(feature.id);
        const failed = run && !run.ok;
        const skipped = build && !build.ok && !run;
        return (
          <li key={feature.id}>
            <button
              type="button"
              className={`feature-row${selected === feature.id ? " is-selected" : ""}${hovered === feature.id ? " is-hovered" : ""}${failed ? " is-failed" : ""}${skipped ? " is-skipped" : ""}`}
              onClick={() => onSelect(selected === feature.id ? null : feature.id)}
              onMouseEnter={() => onHover(feature.id)}
              onMouseLeave={() => onHover(null)}
              aria-pressed={selected === feature.id}
            >
              <span className="feature-index">{index + 1}</span>
              <span className="feature-icon" data-tip={KIND_TIPS[feature.kind]}>
                <Icon size={16} strokeWidth={1.75} />
              </span>
              <span className="feature-label">{feature.label}</span>
              {failed ? (
                <TriangleAlert size={15} className="feature-alert" aria-label="This feature failed" />
              ) : run ? (
                <span className="feature-ms">{run.ms} ms</span>
              ) : null}
            </button>
          </li>
        );
      })}
    </ol>
  );
}
