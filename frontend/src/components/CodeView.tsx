import { useEffect, useMemo, useRef } from "react";
import type { Feature } from "../api";
import { highlightPython } from "../lib/highlight";

interface Props {
  code: string;
  features: Feature[];
  selectedFeature: string | null;
  errorLine: number | null;
  onSelectFeature: (feature: string | null) => void;
}

export function CodeView({ code, features, selectedFeature, errorLine, onSelectFeature }: Props) {
  const lines = useMemo(() => highlightPython(code), [code]);
  const scrollRef = useRef<HTMLDivElement>(null);
  const selected = features.find((f) => f.id === selectedFeature) ?? null;

  const featureAt = (line: number) => features.find((f) => line >= f.line_start && line <= f.line_end) ?? null;

  useEffect(() => {
    if (!selected || !scrollRef.current) return;
    const row = scrollRef.current.querySelector<HTMLElement>(`[data-line="${selected.line_start}"]`);
    row?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [selected]);

  return (
    <div className="code-view" ref={scrollRef} role="region" aria-label="Part source code">
      {lines.map((tokens, i) => {
        const n = i + 1;
        const inSelected = selected !== null && n >= selected.line_start && n <= selected.line_end;
        const owner = featureAt(n);
        return (
          <div
            key={n}
            data-line={n}
            className={`code-line${inSelected ? " is-selected" : ""}${owner ? " is-feature" : ""}${n === errorLine ? " is-error" : ""}`}
            onClick={() => owner && onSelectFeature(owner.id)}
          >
            <span className="code-gutter">{n}</span>
            <span className="code-text">
              {tokens.length === 0 ? " " : tokens.map((t, j) => (
                <span key={j} className={`tok-${t.kind}`}>
                  {t.text}
                </span>
              ))}
            </span>
          </div>
        );
      })}
    </div>
  );
}
