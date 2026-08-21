/*
 * Charts.
 *
 * Hand-built SVG rather than a chart library: it keeps the bundle free of any
 * external dependency and lets each mark follow the spec exactly — thin marks,
 * 4px rounded data-ends anchored to the baseline, a 2px surface gap between
 * adjacent fills, a 2px surface ring on overlapping marks, recessive grid and
 * axes, and selective direct labels rather than a number on every mark.
 *
 * Color follows the entity, never its rank. Magnitude-only charts use one blue
 * sequential hue; the ESG breakdown is the only categorical chart and uses
 * validated slots 1-3 with a legend plus direct labels plus a table view.
 */

import { useCallback, useState } from "react";
import { fmtCompactUSD, fmtNum, fmtPct, fmtUSD } from "../api";

// ── tooltip ────────────────────────────────────────────────────────────────

export function useTooltip() {
  const [tip, setTip] = useState(null);
  const show = useCallback((event, content) => {
    setTip({ x: event.clientX, y: event.clientY, content });
  }, []);
  const hide = useCallback(() => setTip(null), []);
  return { tip, show, hide };
}

export function Tooltip({ tip }) {
  if (!tip) return null;
  // Flip toward the centre near a viewport edge so the panel never clips.
  const flipX = tip.x > window.innerWidth - 300;
  const flipY = tip.y > window.innerHeight - 180;
  return (
    <div
      className="tooltip"
      style={{
        left: flipX ? undefined : tip.x + 14,
        right: flipX ? window.innerWidth - tip.x + 14 : undefined,
        top: flipY ? undefined : tip.y + 14,
        bottom: flipY ? window.innerHeight - tip.y + 14 : undefined,
      }}
    >
      {tip.content}
    </div>
  );
}

export function TipBody({ title, rows }) {
  return (
    <>
      <div className="t-title">{title}</div>
      {rows.map(([label, value]) => (
        <div className="t-row" key={label}>
          <span>{label}</span>
          <b>{value}</b>
        </div>
      ))}
    </>
  );
}

// ── shared helpers ─────────────────────────────────────────────────────────

const niceTicks = (max, count = 4) => {
  if (!(max > 0)) return [0];
  const raw = max / count;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].find((m) => m * mag >= raw) * mag;
  const ticks = [];
  for (let v = 0; v <= max + step * 0.5; v += step) ticks.push(v);
  return ticks;
};

/** Sequential blue ramp, light to dark, for continuous magnitude. */
const seqStep = (t) => {
  const steps = ["--seq-200", "--seq-300", "--seq-400", "--seq-500", "--seq-600", "--seq-700"];
  const clamped = Math.max(0, Math.min(0.999, t));
  return `var(${steps[Math.floor(clamped * steps.length)]})`;
};

function Empty({ label }) {
  return <p className="empty">{label}</p>;
}

// ── cost distribution ──────────────────────────────────────────────────────

/**
 * Histogram of simulated total cost across every Monte Carlo iteration, with
 * the P5 / median / P95 percentile positions marked. One measure, so one hue.
 */
export function CostDistribution({ result, height = 260 }) {
  const { tip, show, hide } = useTooltip();
  const hist = result?.cost_histogram;
  if (!hist?.counts?.length) return <Empty label="No distribution data" />;

  const W = 720, H = height, PAD = { t: 16, r: 16, b: 34, l: 56 };
  const plotW = W - PAD.l - PAD.r, plotH = H - PAD.t - PAD.b;

  const counts = hist.counts;
  const maxCount = Math.max(...counts);
  const lo = hist.edges[0], hi = hist.edges[hist.edges.length - 1];
  const span = hi - lo || 1;

  const xOf = (v) => PAD.l + ((v - lo) / span) * plotW;
  const barW = plotW / counts.length;
  const ticks = niceTicks(maxCount);

  const marks = [
    { key: "P5", value: result.cost_p5 },
    { key: "Median", value: result.cost_p50 },
    { key: "P95", value: result.cost_p95 },
  ].filter((m) => Number.isFinite(m.value));

  return (
    <>
      <svg className="chart" viewBox={`0 0 ${W} ${H}`} role="img"
           aria-label={`Cost distribution across ${fmtNum(result.iterations)} iterations`}>
        {ticks.map((t) => (
          <line key={t} className="grid-line" x1={PAD.l} x2={W - PAD.r}
                y1={PAD.t + plotH - (t / maxCount) * plotH} y2={PAD.t + plotH - (t / maxCount) * plotH} />
        ))}
        {ticks.map((t) => (
          <text key={`l${t}`} className="tick" x={PAD.l - 8} textAnchor="end"
                y={PAD.t + plotH - (t / maxCount) * plotH + 3}>{fmtNum(t)}</text>
        ))}

        {counts.map((c, i) => {
          const h = (c / maxCount) * plotH;
          const x = PAD.l + i * barW;
          const centre = hist.centres[i];
          return (
            <g key={i}>
              {c > 0 && (
                <rect x={x + 1} y={PAD.t + plotH - h} width={Math.max(1, barW - 2)} height={h}
                      rx={Math.min(4, Math.max(0, (barW - 2) / 2))} fill="var(--series-1)" />
              )}
              <rect className="hit" x={x} y={PAD.t} width={barW} height={plotH}
                    onMouseMove={(e) => show(e, (
                      <TipBody title={fmtUSD(centre)} rows={[
                        ["Iterations", fmtNum(c)],
                        ["Share", fmtPct((100 * c) / result.iterations)],
                      ]} />
                    ))}
                    onMouseLeave={hide} />
            </g>
          );
        })}

        {marks.map((m) => (
          <g key={m.key}>
            <line x1={xOf(m.value)} x2={xOf(m.value)} y1={PAD.t} y2={PAD.t + plotH}
                  stroke="var(--series-2)" strokeWidth="2" strokeDasharray={m.key === "Median" ? "none" : "4 3"} />
            <text className="mark-label" x={xOf(m.value)} y={PAD.t - 4} textAnchor="middle"
                  fill="var(--text-secondary)">{m.key}</text>
          </g>
        ))}

        <line className="baseline" x1={PAD.l} x2={W - PAD.r} y1={PAD.t + plotH} y2={PAD.t + plotH} />
        <text className="tick" x={PAD.l} y={H - 16}>{fmtCompactUSD(lo)}</text>
        <text className="tick" x={W - PAD.r} y={H - 16} textAnchor="end">{fmtCompactUSD(hi)}</text>
        <text className="axis-label" x={PAD.l + plotW / 2} y={H - 3} textAnchor="middle">
          Total landed cost per iteration
        </text>
        <text className="axis-label" transform={`rotate(-90 12 ${PAD.t + plotH / 2})`}
              x={12} y={PAD.t + plotH / 2} textAnchor="middle">Iterations</text>
      </svg>
      <Tooltip tip={tip} />
    </>
  );
}

// ── scenario comparison ────────────────────────────────────────────────────

/**
 * Mean cost per scenario with its P5-P95 band. One measure across categories,
 * so a single hue; the band is the same hue at reduced opacity, not a second
 * series. Sorted by risk so the worst case reads first.
 */
export function ScenarioCompare({ results, onSelect, selectedId }) {
  const { tip, show, hide } = useTooltip();
  if (!results?.length) return <Empty label="Run a simulation to compare scenarios" />;

  const rows = [...results].sort((a, b) => b.risk_score - a.risk_score);
  const ROW = 46, W = 720, PAD = { t: 8, r: 96, b: 30, l: 190 };
  const H = PAD.t + rows.length * ROW + PAD.b;
  const plotW = W - PAD.l - PAD.r;
  const max = Math.max(...rows.map((r) => r.cost_p95)) * 1.02 || 1;
  const xOf = (v) => (v / max) * plotW;
  const ticks = niceTicks(max, 4);

  return (
    <>
      <svg className="chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Cost by scenario">
        {ticks.map((t) => (
          <g key={t}>
            <line className="grid-line" x1={PAD.l + xOf(t)} x2={PAD.l + xOf(t)} y1={PAD.t} y2={PAD.t + rows.length * ROW} />
            <text className="tick" x={PAD.l + xOf(t)} y={H - 14} textAnchor="middle">{fmtCompactUSD(t)}</text>
          </g>
        ))}

        {rows.map((r, i) => {
          const y = PAD.t + i * ROW;
          const isSel = r.scenario_id === selectedId;
          return (
            <g key={r.scenario_id}
               onMouseMove={(e) => show(e, (
                 <TipBody title={r.scenario_name} rows={[
                   ["Mean cost", fmtUSD(r.cost_mean)],
                   ["P5 – P95", `${fmtCompactUSD(r.cost_p5)} – ${fmtCompactUSD(r.cost_p95)}`],
                   ["Mean delay", `${fmtNum(r.delay_mean, 1)} days`],
                   ["Service level", fmtPct(r.service_level_pct)],
                   ["Risk score", fmtNum(r.risk_score, 2)],
                 ]} />
               ))}
               onMouseLeave={hide}
               onClick={() => onSelect?.(r.scenario_id)}
               style={{ cursor: onSelect ? "pointer" : "default" }}>
              <rect x={0} y={y} width={W} height={ROW} fill={isSel ? "var(--page)" : "transparent"} rx="4" />
              <text className="axis-label" x={PAD.l - 10} y={y + ROW / 2 + 4} textAnchor="end"
                    fontWeight={isSel ? 600 : 400}
                    fill={isSel ? "var(--text-primary)" : "var(--text-secondary)"}>
                {r.scenario_name.length > 26 ? `${r.scenario_name.slice(0, 25)}…` : r.scenario_name}
              </text>

              {/* P5–P95 band: same hue, recessive */}
              <rect x={PAD.l + xOf(r.cost_p5)} y={y + ROW / 2 - 9}
                    width={Math.max(2, xOf(r.cost_p95) - xOf(r.cost_p5))} height={18}
                    rx="4" fill="var(--series-1)" opacity="0.18" />
              {/* mean */}
              <rect x={PAD.l} y={y + ROW / 2 - 5} width={Math.max(2, xOf(r.cost_mean))} height={10}
                    rx="4" fill="var(--series-1)" />
              {/* P95 cap, ringed against the band it overlaps */}
              <rect x={PAD.l + xOf(r.cost_p95) - 1.5} y={y + ROW / 2 - 11} width={3} height={22}
                    fill="var(--series-2)" stroke="var(--surface)" strokeWidth="2" rx="1.5" />

              <text className="mark-label" x={W - PAD.r + 10} y={y + ROW / 2 + 4}>
                {fmtCompactUSD(r.cost_mean)}
              </text>
            </g>
          );
        })}
        <line className="baseline" x1={PAD.l} x2={PAD.l} y1={PAD.t} y2={PAD.t + rows.length * ROW} />
      </svg>
      <div className="legend">
        <span className="item"><i className="swatch" style={{ background: "var(--series-1)" }} /> Mean cost</span>
        <span className="item"><i className="swatch" style={{ background: "var(--series-1)", opacity: 0.25 }} /> P5–P95 range</span>
        <span className="item"><i className="swatch" style={{ background: "var(--series-2)" }} /> P95 tail</span>
      </div>
      <Tooltip tip={tip} />
    </>
  );
}

// ── pareto front ───────────────────────────────────────────────────────────

/**
 * Cost against portfolio ESG for the non-dominated iterations of one scenario.
 * A single scenario at a time keeps this to one series, which is what a scatter
 * needs — an all-pairs form caps out at three categorical hues.
 */
export function ParetoFront({ result, height = 260 }) {
  const { tip, show, hide } = useTooltip();
  const pts = result?.pareto_front;
  if (!pts?.length) return <Empty label="No Pareto-optimal points for this scenario" />;
  if (pts.length === 1) {
    return (
      <p className="empty">
        A single optimum at {fmtUSD(pts[0].cost)} / ESG {fmtNum(pts[0].esg_score, 1)} — the ESG
        floor binds in every iteration, so there is no cost-versus-ESG trade-off to plot.
      </p>
    );
  }

  const W = 720, H = height, PAD = { t: 18, r: 24, b: 40, l: 62 };
  const plotW = W - PAD.l - PAD.r, plotH = H - PAD.t - PAD.b;

  const costs = pts.map((p) => p.cost), esgs = pts.map((p) => p.esg_score);
  const cLo = Math.min(...costs), cHi = Math.max(...costs);
  const eLo = Math.min(...esgs), eHi = Math.max(...esgs);
  const cSpan = cHi - cLo || 1, eSpan = eHi - eLo || 1;

  const xOf = (c) => PAD.l + ((c - cLo) / cSpan) * plotW;
  const yOf = (e) => PAD.t + plotH - ((e - eLo) / eSpan) * plotH;
  const path = pts.map((p, i) => `${i ? "L" : "M"}${xOf(p.cost)},${yOf(p.esg_score)}`).join(" ");

  return (
    <>
      <svg className="chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Pareto front: cost versus ESG">
        {[0, 0.25, 0.5, 0.75, 1].map((f) => (
          <line key={f} className="grid-line" x1={PAD.l} x2={W - PAD.r}
                y1={PAD.t + plotH * f} y2={PAD.t + plotH * f} />
        ))}
        <path d={path} fill="none" stroke="var(--series-1)" strokeWidth="2"
              strokeLinejoin="round" strokeLinecap="round" opacity="0.5" />
        {pts.map((p, i) => (
          <circle key={i} cx={xOf(p.cost)} cy={yOf(p.esg_score)} r="5"
                  fill="var(--series-1)" stroke="var(--surface)" strokeWidth="2"
                  onMouseMove={(e) => show(e, (
                    <TipBody title={`Iteration ${p.iteration}`} rows={[
                      ["Total cost", fmtUSD(p.cost)],
                      ["Portfolio ESG", fmtNum(p.esg_score, 1)],
                    ]} />
                  ))}
                  onMouseLeave={hide} />
        ))}
        <line className="baseline" x1={PAD.l} x2={W - PAD.r} y1={PAD.t + plotH} y2={PAD.t + plotH} />
        <line className="baseline" x1={PAD.l} x2={PAD.l} y1={PAD.t} y2={PAD.t + plotH} />
        <text className="tick" x={PAD.l} y={H - 20}>{fmtCompactUSD(cLo)}</text>
        <text className="tick" x={W - PAD.r} y={H - 20} textAnchor="end">{fmtCompactUSD(cHi)}</text>
        <text className="tick" x={PAD.l - 8} y={PAD.t + 4} textAnchor="end">{fmtNum(eHi, 1)}</text>
        <text className="tick" x={PAD.l - 8} y={PAD.t + plotH} textAnchor="end">{fmtNum(eLo, 1)}</text>
        <text className="axis-label" x={PAD.l + plotW / 2} y={H - 5} textAnchor="middle">
          Total cost — cheaper to the left
        </text>
        <text className="axis-label" transform={`rotate(-90 14 ${PAD.t + plotH / 2})`}
              x={14} y={PAD.t + plotH / 2} textAnchor="middle">Portfolio ESG</text>
      </svg>
      <Tooltip tip={tip} />
    </>
  );
}

// ── efficient frontier ─────────────────────────────────────────────────────

/**
 * What raising the ESG floor costs.
 *
 * One measure (cost) against one control (the floor), so one hue: the mean is
 * the solid line, the P95 the same hue at low opacity above it — a band, not a
 * second series, and never a second y-axis. The marker shows where the run's
 * own floor sits on the curve.
 */
export function EfficientFrontier({ frontier, currentFloor, height = 270 }) {
  const { tip, show, hide } = useTooltip();
  const [hover, setHover] = useState(null);
  if (!frontier?.length || frontier.length < 2) {
    return <Empty label="Not enough ESG headroom in this supplier network to plot a frontier" />;
  }

  const W = 720, H = height, PAD = { t: 18, r: 20, b: 44, l: 68 };
  const plotW = W - PAD.l - PAD.r, plotH = H - PAD.t - PAD.b;

  const xLo = frontier[0].min_esg_score;
  const xHi = frontier[frontier.length - 1].min_esg_score;
  const xSpan = xHi - xLo || 1;
  const yMax = Math.max(...frontier.map((f) => f.cost_p95)) * 1.05;

  const xOf = (v) => PAD.l + ((v - xLo) / xSpan) * plotW;
  const yOf = (v) => PAD.t + plotH - (v / yMax) * plotH;

  const meanPath = frontier.map((f, i) => `${i ? "L" : "M"}${xOf(f.min_esg_score)},${yOf(f.cost_mean)}`).join(" ");
  const band = [
    ...frontier.map((f) => `${xOf(f.min_esg_score)},${yOf(f.cost_p95)}`),
    ...[...frontier].reverse().map((f) => `${xOf(f.min_esg_score)},${yOf(f.cost_mean)}`),
  ].join(" ");

  const ticks = niceTicks(yMax, 4);
  const nearest = (clientX, rect) => {
    const rel = ((clientX - rect.left) / rect.width) * W;
    let best = frontier[0], bestD = Infinity;
    for (const f of frontier) {
      const d = Math.abs(xOf(f.min_esg_score) - rel);
      if (d < bestD) { bestD = d; best = f; }
    }
    return best;
  };

  return (
    <>
      <svg className="chart" viewBox={`0 0 ${W} ${H}`} role="img"
           aria-label="Cost of raising the minimum ESG score"
           onMouseMove={(e) => {
             const f = nearest(e.clientX, e.currentTarget.getBoundingClientRect());
             setHover(f);
             show(e, (
               <TipBody title={`ESG floor ${fmtNum(f.min_esg_score, 1)}`} rows={[
                 ["Mean cost", fmtUSD(f.cost_mean)],
                 ["P95 cost", fmtUSD(f.cost_p95)],
                 ["Achieved ESG", fmtNum(f.achieved_esg, 2)],
                 ["Feasible iterations", fmtPct(f.feasible_pct)],
               ]} />
             ));
           }}
           onMouseLeave={() => { setHover(null); hide(); }}>
        {ticks.map((t) => (
          <g key={t}>
            <line className="grid-line" x1={PAD.l} x2={W - PAD.r} y1={yOf(t)} y2={yOf(t)} />
            <text className="tick" x={PAD.l - 8} y={yOf(t) + 3} textAnchor="end">{fmtCompactUSD(t)}</text>
          </g>
        ))}

        <polygon points={band} fill="var(--series-1)" opacity="0.15" />
        <path d={meanPath} fill="none" stroke="var(--series-1)" strokeWidth="2"
              strokeLinejoin="round" strokeLinecap="round" />

        {frontier.map((f) => (
          <circle key={f.min_esg_score} cx={xOf(f.min_esg_score)} cy={yOf(f.cost_mean)} r="4"
                  fill="var(--series-1)" stroke="var(--surface)" strokeWidth="2" />
        ))}

        {hover && (
          <line x1={xOf(hover.min_esg_score)} x2={xOf(hover.min_esg_score)} y1={PAD.t} y2={PAD.t + plotH}
                stroke="var(--text-muted)" strokeWidth="1" strokeDasharray="3 3" />
        )}

        {currentFloor > 0 && currentFloor >= xLo && currentFloor <= xHi && (
          <g>
            <line x1={xOf(currentFloor)} x2={xOf(currentFloor)} y1={PAD.t} y2={PAD.t + plotH}
                  stroke="var(--series-2)" strokeWidth="2" />
            <text className="mark-label" x={xOf(currentFloor)} y={PAD.t - 5} textAnchor="middle"
                  fill="var(--series-2)" fontWeight="600">your floor</text>
          </g>
        )}

        <line className="baseline" x1={PAD.l} x2={W - PAD.r} y1={PAD.t + plotH} y2={PAD.t + plotH} />
        <line className="baseline" x1={PAD.l} x2={PAD.l} y1={PAD.t} y2={PAD.t + plotH} />
        {frontier.filter((_, i) => i % 3 === 0).map((f) => (
          <text key={f.min_esg_score} className="tick" x={xOf(f.min_esg_score)} y={H - 26} textAnchor="middle">
            {f.min_esg_score.toFixed(0)}
          </text>
        ))}
        <text className="axis-label" x={PAD.l + plotW / 2} y={H - 8} textAnchor="middle">
          Minimum portfolio ESG score required
        </text>
        <text className="axis-label" transform={`rotate(-90 14 ${PAD.t + plotH / 2})`}
              x={14} y={PAD.t + plotH / 2} textAnchor="middle">Total landed cost</text>
      </svg>
      <div className="legend">
        <span className="item"><i className="swatch" style={{ background: "var(--series-1)" }} /> Mean cost</span>
        <span className="item"><i className="swatch" style={{ background: "var(--series-1)", opacity: 0.25 }} /> Up to P95</span>
        <span className="item"><i className="swatch" style={{ background: "var(--series-2)" }} /> Floor set for this run</span>
      </div>
      <Tooltip tip={tip} />
    </>
  );
}

// ── country risk ───────────────────────────────────────────────────────────

/** Country risk 0–1. Continuous magnitude, so a one-hue sequential ramp. */
export function CountryRisk({ risks }) {
  const { tip, show, hide } = useTooltip();
  const rows = Object.entries(risks || {})
    .map(([country, score]) => ({ country, score }))
    .sort((a, b) => b.score - a.score)
    .slice(0, 12);
  if (!rows.length) return <Empty label="No risk scores yet" />;

  const ROW = 26, W = 460, PAD = { t: 6, r: 52, b: 22, l: 44 };
  const H = PAD.t + rows.length * ROW + PAD.b;
  const plotW = W - PAD.l - PAD.r;

  return (
    <>
      <svg className="chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Country risk scores">
        {[0, 0.5, 1].map((t) => (
          <g key={t}>
            <line className="grid-line" x1={PAD.l + t * plotW} x2={PAD.l + t * plotW} y1={PAD.t} y2={PAD.t + rows.length * ROW} />
            <text className="tick" x={PAD.l + t * plotW} y={H - 8} textAnchor="middle">{t.toFixed(1)}</text>
          </g>
        ))}
        {rows.map((r, i) => {
          const y = PAD.t + i * ROW;
          return (
            <g key={r.country}
               onMouseMove={(e) => show(e, (
                 <TipBody title={r.country} rows={[["Risk score", fmtNum(r.score, 3)],
                   ["Above 0.30 threshold", r.score >= 0.3 ? "yes — supplier flagged" : "no"]]} />
               ))}
               onMouseLeave={hide}>
              <text className="axis-label" x={PAD.l - 8} y={y + ROW / 2 + 4} textAnchor="end">{r.country}</text>
              <rect x={PAD.l} y={y + ROW / 2 - 5} width={Math.max(2, r.score * plotW)} height={10}
                    rx="4" fill={seqStep(r.score)} />
              <text className="mark-label" x={W - PAD.r + 8} y={y + ROW / 2 + 4}>{r.score.toFixed(2)}</text>
            </g>
          );
        })}
        {/* the 0.30 exposure threshold the analyzer uses */}
        <line x1={PAD.l + 0.3 * plotW} x2={PAD.l + 0.3 * plotW} y1={PAD.t} y2={PAD.t + rows.length * ROW}
              stroke="var(--series-2)" strokeWidth="2" strokeDasharray="3 3" />
        <line className="baseline" x1={PAD.l} x2={PAD.l} y1={PAD.t} y2={PAD.t + rows.length * ROW} />
      </svg>
      <div className="legend">
        <span className="item"><i className="swatch" style={{ background: "var(--series-2)" }} /> 0.30 exposure threshold</span>
        <span className="item muted">Darker bar = higher risk</span>
      </div>
      <Tooltip tip={tip} />
    </>
  );
}

// ── ESG breakdown ──────────────────────────────────────────────────────────

/**
 * Environmental / social / governance contribution per supplier.
 *
 * The one categorical chart here: three validated slots, a 2px surface gap
 * between segments, a legend, direct labels on every segment wide enough to
 * hold one, and a table view — light-mode aqua sits below 3:1 on the surface,
 * so the relief rule requires visible labels.
 */
export function EsgBreakdown({ suppliers, limit = 12 }) {
  const { tip, show, hide } = useTooltip();
  const [showTable, setShowTable] = useState(false);
  const rows = (suppliers || []).slice(0, limit);
  if (!rows.length) return <Empty label="No supplier ESG data" />;

  const parts = [
    { key: "environmental", label: "Environmental", weight: 0.4, color: "var(--series-1)" },
    { key: "social", label: "Social", weight: 0.35, color: "var(--series-2)" },
    { key: "governance", label: "Governance", weight: 0.25, color: "var(--series-3)" },
  ];

  const ROW = 30, W = 720, PAD = { t: 6, r: 58, b: 24, l: 200 };
  const H = PAD.t + rows.length * ROW + PAD.b;
  const plotW = W - PAD.l - PAD.r;
  const scale = 100; // composite is on a 0–100 scale

  return (
    <>
      {!showTable ? (
        <svg className="chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Supplier ESG composition">
          {[0, 25, 50, 75, 100].map((t) => (
            <g key={t}>
              <line className="grid-line" x1={PAD.l + (t / scale) * plotW} x2={PAD.l + (t / scale) * plotW}
                    y1={PAD.t} y2={PAD.t + rows.length * ROW} />
              <text className="tick" x={PAD.l + (t / scale) * plotW} y={H - 8} textAnchor="middle">{t}</text>
            </g>
          ))}
          {rows.map((s, i) => {
            const y = PAD.t + i * ROW;
            let cursor = 0;
            return (
              <g key={s.supplier_id}>
                <text className="axis-label" x={PAD.l - 10} y={y + ROW / 2 + 4} textAnchor="end">
                  {(s.supplier_name || "").length > 24 ? `${s.supplier_name.slice(0, 23)}…` : s.supplier_name}
                </text>
                {parts.map((p) => {
                  const value = (s[p.key] || 0) * p.weight;
                  const w = (value / scale) * plotW;
                  const x = PAD.l + cursor;
                  cursor += w;
                  const isFirst = p.key === "environmental";
                  const isLast = p.key === "governance";
                  return (
                    <g key={p.key}>
                      {/* 2px surface gap between adjacent fills */}
                      <rect x={x + (isFirst ? 0 : 1)} y={y + ROW / 2 - 6}
                            width={Math.max(0, w - (isFirst || isLast ? 1 : 2))} height={12}
                            rx={isFirst || isLast ? 4 : 0} fill={p.color}
                            onMouseMove={(e) => show(e, (
                              <TipBody title={s.supplier_name} rows={[
                                [p.label, fmtNum(s[p.key], 1)],
                                [`Weight`, `${(p.weight * 100).toFixed(0)}%`],
                                ["Contribution", fmtNum(value, 1)],
                                ["Composite", fmtNum(s.composite_score, 1)],
                              ]} />
                            ))}
                            onMouseLeave={hide} />
                      {w > 34 && (
                        <text x={x + w / 2} y={y + ROW / 2 + 4} textAnchor="middle"
                              fontSize="10" fontWeight="600" fill="#fff" style={{ pointerEvents: "none" }}>
                          {value.toFixed(0)}
                        </text>
                      )}
                    </g>
                  );
                })}
                <text className="mark-label" x={W - PAD.r + 10} y={y + ROW / 2 + 4} fontWeight="600">
                  {fmtNum(s.composite_score, 1)}
                </text>
              </g>
            );
          })}
          <line className="baseline" x1={PAD.l} x2={PAD.l} y1={PAD.t} y2={PAD.t + rows.length * ROW} />
        </svg>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Supplier</th><th className="num">Environmental</th><th className="num">Social</th>
                <th className="num">Governance</th><th className="num">Composite</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((s) => (
                <tr key={s.supplier_id}>
                  <td>{s.supplier_name}</td>
                  <td className="num">{fmtNum(s.environmental, 1)}</td>
                  <td className="num">{fmtNum(s.social, 1)}</td>
                  <td className="num">{fmtNum(s.governance, 1)}</td>
                  <td className="num"><b>{fmtNum(s.composite_score, 1)}</b></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="legend">
        {parts.map((p) => (
          <span className="item" key={p.key}>
            <i className="swatch" style={{ background: p.color }} /> {p.label} ({p.weight * 100}%)
          </span>
        ))}
        <button className="toggle-link" onClick={() => setShowTable((v) => !v)}>
          {showTable ? "Show chart" : "Show table"}
        </button>
      </div>
      <Tooltip tip={tip} />
    </>
  );
}

// ── supplier mix ───────────────────────────────────────────────────────────

/** Share of volume the optimiser routes to each supplier. One measure, one hue. */
export function SupplierMix({ mix, limit = 10 }) {
  const { tip, show, hide } = useTooltip();
  const rows = (mix || []).slice(0, limit);
  if (!rows.length) return <Empty label="No allocation data" />;

  const max = Math.max(...rows.map((r) => r.share_pct)) || 1;
  const ROW = 30, W = 560, PAD = { t: 6, r: 56, b: 8, l: 210 };
  const H = PAD.t + rows.length * ROW + PAD.b;
  const plotW = W - PAD.l - PAD.r;

  return (
    <>
      <svg className="chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Supplier allocation share">
        {rows.map((r, i) => {
          const y = PAD.t + i * ROW;
          return (
            <g key={r.supplier_id}
               onMouseMove={(e) => show(e, (
                 <TipBody title={r.name} rows={[
                   ["Country", r.country_code],
                   ["Share of volume", fmtPct(r.share_pct)],
                   ["Mean units", fmtNum(r.mean_units)],
                   ["ESG score", fmtNum(r.esg_score, 1)],
                 ]} />
               ))}
               onMouseLeave={hide}>
              <text className="axis-label" x={PAD.l - 10} y={y + ROW / 2 + 4} textAnchor="end">
                {r.name.length > 26 ? `${r.name.slice(0, 25)}…` : r.name}
                <tspan className="tick" dx="6">{r.country_code}</tspan>
              </text>
              <rect x={PAD.l} y={y + ROW / 2 - 5} width={Math.max(2, (r.share_pct / max) * plotW)} height={10}
                    rx="4" fill="var(--series-1)" />
              <text className="mark-label" x={W - PAD.r + 8} y={y + ROW / 2 + 4}>{r.share_pct.toFixed(1)}%</text>
            </g>
          );
        })}
        <line className="baseline" x1={PAD.l} x2={PAD.l} y1={PAD.t} y2={PAD.t + rows.length * ROW} />
      </svg>
      <Tooltip tip={tip} />
    </>
  );
}

// ── capacity by country ────────────────────────────────────────────────────

/** Sourcing capacity concentration. Magnitude, so the sequential ramp again. */
export function CapacityByCountry({ rows, limit = 12 }) {
  const { tip, show, hide } = useTooltip();
  const data = (rows || []).slice(0, limit);
  if (!data.length) return <Empty label="No capacity data" />;

  const max = Math.max(...data.map((d) => d.capacity_share_pct)) || 1;
  const ROW = 26, W = 460, PAD = { t: 6, r: 54, b: 8, l: 46 };
  const H = PAD.t + data.length * ROW + PAD.b;
  const plotW = W - PAD.l - PAD.r;

  return (
    <>
      <svg className="chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Capacity share by country">
        {data.map((d, i) => {
          const y = PAD.t + i * ROW;
          return (
            <g key={d.country_code}
               onMouseMove={(e) => show(e, (
                 <TipBody title={d.country_code} rows={[
                   ["Suppliers", fmtNum(d.suppliers)],
                   ["Capacity", `${fmtNum(d.capacity_units)} units`],
                   ["Share", fmtPct(d.capacity_share_pct)],
                   ["Mean ESG", fmtNum(d.esg_score, 1)],
                 ]} />
               ))}
               onMouseLeave={hide}>
              <text className="axis-label" x={PAD.l - 8} y={y + ROW / 2 + 4} textAnchor="end">{d.country_code}</text>
              <rect x={PAD.l} y={y + ROW / 2 - 5} width={Math.max(2, (d.capacity_share_pct / max) * plotW)}
                    height={10} rx="4" fill={seqStep(d.capacity_share_pct / max)} />
              <text className="mark-label" x={W - PAD.r + 8} y={y + ROW / 2 + 4}>{d.capacity_share_pct.toFixed(1)}%</text>
            </g>
          );
        })}
        <line className="baseline" x1={PAD.l} x2={PAD.l} y1={PAD.t} y2={PAD.t + data.length * ROW} />
      </svg>
      <Tooltip tip={tip} />
    </>
  );
}
