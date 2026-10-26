import { Download, Monitor, Moon, Redo2, Sun, Undo2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { Health } from "../api";

export type ThemeChoice = "system" | "light" | "dark";

interface Props {
  title: string;
  health: Health | null;
  backendDown: boolean;
  theme: ThemeChoice;
  onTheme: (theme: ThemeChoice) => void;
  canUndo: boolean;
  canRedo: boolean;
  onUndo: () => void;
  onRedo: () => void;
  downloads: { label: string; href: string; hint: string }[];
}

export function BrandMark() {
  return (
    <svg className="brand-mark" viewBox="0 0 32 32" aria-hidden="true">
      <rect width="32" height="32" rx="9" fill="var(--accent)" />
      <path d="M10 8h4.5v11.5H23V24H10z" fill="#fff" />
      <circle cx="18.5" cy="12" r="2" fill="#fff" />
    </svg>
  );
}

const THEME_ORDER: ThemeChoice[] = ["system", "light", "dark"];
const THEME_ICON = { system: Monitor, light: Sun, dark: Moon };

export function TopBar(props: Props) {
  const { health } = props;
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!menuOpen) return;
    const close = (e: MouseEvent) => {
      if (!menuRef.current?.contains(e.target as Node)) setMenuOpen(false);
    };
    window.addEventListener("mousedown", close);
    return () => window.removeEventListener("mousedown", close);
  }, [menuOpen]);

  const ThemeIcon = THEME_ICON[props.theme];
  const nextTheme = THEME_ORDER[(THEME_ORDER.indexOf(props.theme) + 1) % THEME_ORDER.length];
  const session = health?.session;

  return (
    <header className="topbar">
      <div className="brand">
        <BrandMark />
        <span className="brand-name">Jig</span>
        <span className="brand-divider" />
        <span className="part-title">{props.title}</span>
      </div>

      <div className="topbar-status">
        {props.backendDown ? (
          <span className="pill pill-danger" data-tip="Start it with: python scripts/jig.py dev">
            Backend offline
          </span>
        ) : (
          <>
            <span
              className={`pill ${health?.ai.ready ? "pill-ok" : "pill-warn"}`}
              data-tip={health?.ai.ready ? "Meta Model API key found." : "Add MODEL_API_KEY to .env to turn on the AI agents."}
            >
              <span className="dot" /> Meta API {health?.ai.ready ? "ready" : "needs key"}
            </span>
            <span
              className={`pill ${health?.fea.available ? "pill-ok" : "pill-warn"}`}
              data-tip={health?.fea.available ? `Finite element analysis (stress simulation) runs locally with CalculiX ${health.fea.version}.` : `${health?.fea.message ?? ""} ${health?.fea.install_hint ?? ""}`}
            >
              <span className="dot" /> FEA {health?.fea.available ? "ready" : "off"}
            </span>
            {session && (
              <span
                className={`pill ${session.exhausted ? "pill-danger" : session.warning ? "pill-warn" : ""}`}
                data-tip="Estimated Meta API spend this session. Jig stops calling models when the budget runs out."
              >
                ${session.spent_usd.toFixed(2)} of ${session.budget_usd.toFixed(0)}
              </span>
            )}
          </>
        )}
      </div>

      <div className="topbar-actions">
        <button type="button" className="icon-button" onClick={props.onUndo} disabled={!props.canUndo} data-tip="Undo (Ctrl/Cmd+Z)" aria-label="Undo">
          <Undo2 size={17} />
        </button>
        <button type="button" className="icon-button" onClick={props.onRedo} disabled={!props.canRedo} data-tip="Redo (Ctrl/Cmd+Shift+Z)" aria-label="Redo">
          <Redo2 size={17} />
        </button>
        <button type="button" className="icon-button" onClick={() => props.onTheme(nextTheme)} data-tip={`Theme: ${props.theme}`} aria-label={`Theme: ${props.theme}`}>
          <ThemeIcon size={17} />
        </button>
        <div className="menu-anchor" ref={menuRef}>
          <button type="button" className="button button-primary" onClick={() => setMenuOpen((v) => !v)} disabled={props.downloads.length === 0} aria-expanded={menuOpen}>
            <Download size={15} /> Export
          </button>
          {menuOpen && (
            <div className="menu" role="menu">
              {props.downloads.map((d) => (
                <a key={d.label} role="menuitem" className="menu-item" href={d.href} download onClick={() => setMenuOpen(false)}>
                  <span>{d.label}</span>
                  <span className="menu-hint">{d.hint}</span>
                </a>
              ))}
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
