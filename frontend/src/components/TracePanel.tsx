import { Bot, CircleCheck, CircleX, Cpu, Info } from "lucide-react";

export interface TraceEvent {
  id: number;
  at: Date;
  agent: string;
  kind: "agent" | "check" | "system";
  status: "ok" | "fail" | "info";
  title: string;
  detail?: string;
}

const time = new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" });

export function TracePanel({ events }: { events: TraceEvent[] }) {
  if (events.length === 0) {
    return (
      <p className="empty-note">
        Every step the agents and the deterministic checks take shows up here: which agent, what it
        decided, and what it changed.
      </p>
    );
  }
  return (
    <ol className="trace" aria-live="polite">
      {[...events].reverse().map((event) => {
        const Icon = event.kind === "agent" ? Bot : event.kind === "check" ? (event.status === "fail" ? CircleX : CircleCheck) : event.status === "info" ? Info : Cpu;
        return (
          <li key={event.id} className={`trace-item is-${event.kind} is-${event.status}`}>
            <span className="trace-icon">
              <Icon size={15} strokeWidth={1.9} />
            </span>
            <div className="trace-body">
              <div className="trace-head">
                <span className="trace-agent">{event.agent}</span>
                <time className="trace-time">{time.format(event.at)}</time>
              </div>
              <p className="trace-title">{event.title}</p>
              {event.detail && <p className="trace-detail">{event.detail}</p>}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
