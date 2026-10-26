import {
  Box,
  CircleDot,
  Combine,
  FlipHorizontal2,
  Grid3x3,
  Layers,
  type LucideIcon,
  PenLine,
  RotateCw,
  Rows3,
  Shapes,
  Spline,
  Square,
  Triangle,
  TriangleAlert,
  Waypoints,
} from "lucide-react";
import type { Build, Feature } from "../api";

const ICONS: Record<string, LucideIcon> = {
  sketch: PenLine,
  extrude: Box,
  revolve: RotateCw,
  loft: Layers,
  sweep: Waypoints,
  fillet: Spline,
  chamfer: Triangle,
  hole: CircleDot,
  shell: Square,
  pattern: Grid3x3,
  mirror: FlipHorizontal2,
  boolean: Combine,
  rib: Rows3,
  other: Shapes,
};

const KIND_TIPS: Record<string, string> = {
  extrude: "Extrude: pushes a flat profile out into a solid.",
  fillet: "Fillet: rounds a sharp edge. Inside fillets spread stress and make parts stronger.",
  chamfer: "Chamfer: cuts a sharp edge at an angle.",
  hole: "Hole: a round cut, usually for a bolt or shaft.",
  shell: "Shell: hollows a solid, leaving walls of a set thickness.",
  pattern: "Pattern: repeats a feature in a row or circle.",
  revolve: "Revolve: spins a profile around an axis.",
};

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
