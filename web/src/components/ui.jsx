/* Small presentational pieces shared across the views. */

import { fmtTime } from "../api";

export function Card({ title, caption, actions, children, style }) {
  return (
    <section className="card" style={style}>
      {(title || actions) && (
        <header>
          {title && <h3>{title}</h3>}
          <span style={{ flex: 1 }} />
          {actions}
        </header>
      )}
      {caption && <p className="caption">{caption}</p>}
      {children}
    </section>
  );
}

/**
 * A single headline number. Status never travels on color alone — the delta
 * carries a directional glyph and a word alongside its color.
 */
export function StatTile({ label, value, unit, delta, deltaTone, hint }) {
  return (
    <div className="tile">
      <div className="label">{label}</div>
      <div className="value">
        {value}
        {unit && <span className="unit">{unit}</span>}
      </div>
      {delta && <div className={`delta ${deltaTone || ""}`}>{delta}</div>}
      {hint && <div className="delta muted">{hint}</div>}
    </div>
  );
}

/** Status badge: dot + text, so the state is legible without color. */
export function Badge({ tone = "neutral", children }) {
  return (
    <span className={`badge ${tone}`}>
      <i className="dot" />
      {children}
    </span>
  );
}

const STATUS_TONE = {
  complete: "good",
  running: "warning",
  pending: "neutral",
  awaiting_approval: "serious",
  failed: "critical",
};

export function StatusBadge({ status }) {
  return (
    <Badge tone={STATUS_TONE[status] || "neutral"}>
      {(status || "unknown").replace(/_/g, " ")}
    </Badge>
  );
}

/** Vertical pipeline timeline built from the streamed node events. */
export function PipelineTimeline({ events }) {
  if (!events?.length) {
    return <p className="empty">No run yet — configure a profile and start the pipeline.</p>;
  }
  return (
    <div className="timeline">
      {events.map((e, i) => (
        <div className="step" key={`${e.node}-${e.ts}-${i}`}>
          <div className="rail">
            <span className={`node ${e.status}`} />
            {i < events.length - 1 && <span className="line" />}
          </div>
          <div className="body">
            <div className="row" style={{ gap: 8 }}>
              <span className="name">{e.node.replace(/_/g, " ")}</span>
              <span className="time">{fmtTime(e.ts)}</span>
            </div>
            <div className="msg">{e.message}</div>
          </div>
        </div>
      ))}
    </div>
  );
}

export function ProgressBar({ pct }) {
  return (
    <div className="progress" role="progressbar" aria-valuenow={Math.round(pct)} aria-valuemin={0} aria-valuemax={100}>
      <i style={{ width: `${Math.max(0, Math.min(100, pct))}%` }} />
    </div>
  );
}
