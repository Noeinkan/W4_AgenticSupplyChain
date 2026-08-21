/* The four dashboard views: Network, Simulate, Governance, ESG. */

import { useEffect, useMemo, useState } from "react";
import {
  api, fmtCompactUSD, fmtNum, fmtPct, fmtRelative, fmtUSD, riskStatus, severityStatus,
} from "./api";
import {
  CapacityByCountry, CostDistribution, CountryRisk, EfficientFrontier, EsgBreakdown,
  ParetoFront, ScenarioCompare, SupplierMix,
} from "./components/charts";
import { Badge, Card, PipelineTimeline, ProgressBar, StatTile, StatusBadge } from "./components/ui";

// ── Network ────────────────────────────────────────────────────────────────

export function NetworkView({ overview, suppliers }) {
  const [sort, setSort] = useState("capacity_units");

  const sorted = useMemo(() => {
    const rows = [...(suppliers || [])];
    rows.sort((a, b) =>
      typeof a[sort] === "string" ? String(a[sort]).localeCompare(String(b[sort])) : (b[sort] || 0) - (a[sort] || 0)
    );
    return rows;
  }, [suppliers, sort]);

  if (!overview) return <p className="empty">Loading network…</p>;

  return (
    <div className="stack">
      <div className="grid tiles">
        <StatTile label="Suppliers" value={fmtNum(overview.supplier_count)}
                  hint={`across ${overview.country_count} countries`} />
        <StatTile label="Shipping lanes" value={fmtNum(overview.route_count)}
                  hint="sea, air and rail" />
        <StatTile label="Monthly capacity" value={fmtNum(overview.total_capacity_units / 12)} unit=" units"
                  hint={`${fmtNum(overview.total_capacity_units)} annual`} />
        <StatTile label="Mean ESG score" value={fmtNum(overview.mean_esg_score, 1)} unit="/100"
                  hint="capacity-unweighted" />
        <StatTile label="Active disruptions" value={fmtNum(overview.active_events)}
                  delta={`peak severity ${overview.max_event_severity}/5`}
                  deltaTone={overview.max_event_severity >= 4 ? "bad" : ""} />
      </div>

      <div className="grid cols-2">
        <Card title="Capacity concentration"
              caption="Share of total sourcing capacity by country. A tall bar is a single point of failure.">
          <CapacityByCountry rows={overview.by_country} />
        </Card>

        <Card title="Live disruption feed"
              caption="Events the monitor agent scores into country risk on every run.">
          <div className="stack" style={{ gap: 12 }}>
            {overview.events.map((e) => (
              <div key={e.id} style={{ borderLeft: "2px solid var(--grid)", paddingLeft: 12 }}>
                <div className="row" style={{ gap: 8, marginBottom: 2 }}>
                  <Badge tone={severityStatus(e.severity)}>sev {e.severity}/5</Badge>
                  <span className="muted" style={{ fontSize: 12 }}>{e.event_type}</span>
                  <span className="muted" style={{ fontSize: 12 }}>· {fmtRelative(e.valid_from)}</span>
                </div>
                <div style={{ fontWeight: 600, fontSize: 13 }}>{e.title}</div>
                <div className="muted" style={{ fontSize: 12 }}>{e.description}</div>
                <div className="chips" style={{ marginTop: 6 }}>
                  {e.affected_countries.map((c) => <span className="chip" key={c}>{c}</span>)}
                </div>
              </div>
            ))}
          </div>
        </Card>
      </div>

      <Card title="Supplier master"
            caption="Click a column heading to re-sort."
            actions={<span className="muted" style={{ fontSize: 12 }}>{sorted.length} suppliers</span>}>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                {[["name", "Supplier"], ["country_code", "Country"], ["tier", "Tier"],
                  ["capacity_units", "Capacity"], ["unit_cost_usd", "Unit cost"],
                  ["esg_score", "ESG"], ["lead_time_days", "Lead time"], ["route_count", "Lanes"]]
                  .map(([key, label]) => (
                    <th key={key} className={key === "name" || key === "country_code" ? "" : "num"}
                        style={{ cursor: "pointer", color: sort === key ? "var(--text-primary)" : undefined }}
                        onClick={() => setSort(key)}>
                      {label}{sort === key ? " ↓" : ""}
                    </th>
                  ))}
              </tr>
            </thead>
            <tbody>
              {sorted.map((s) => (
                <tr key={s.id}>
                  <td>{s.name}</td>
                  <td>{s.country_code} <span className="muted">{s.region}</span></td>
                  <td className="num">{s.tier}</td>
                  <td className="num">{fmtNum(s.capacity_units)}</td>
                  <td className="num">{fmtUSD(s.unit_cost_usd, 2)}</td>
                  <td className="num">{fmtNum(s.esg_score, 1)}</td>
                  <td className="num">{s.lead_time_days}d</td>
                  <td className="num">{s.route_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}

// ── Simulate ───────────────────────────────────────────────────────────────

const PRESETS = {
  fashion: {
    name: "Northwind Apparel", industry: "fashion",
    hs_codes: ["6104", "6201"], supplier_countries: ["BD", "VN", "IN", "KH"],
    annual_volume_units: 1_200_000, min_esg_score: 60, n_iterations: 2000, max_iterations: 3,
  },
  electronics: {
    name: "Helio Devices", industry: "electronics",
    hs_codes: ["8542", "8471"], supplier_countries: ["TW", "KR", "MY", "TH", "JP"],
    annual_volume_units: 300_000, min_esg_score: 70, n_iterations: 2000, max_iterations: 3,
  },
};

export function SimulateView({ run, events, busy, onStart, onDecide, error }) {
  const [profile, setProfile] = useState(PRESETS.fashion);
  const [selectedScenario, setSelectedScenario] = useState(null);
  const [notes, setNotes] = useState("");

  const results = run?.scenario_results || [];
  const selected = useMemo(
    () => results.find((r) => r.scenario_id === selectedScenario) || results[0],
    [results, selectedScenario]
  );

  const set = (key) => (e) => {
    const raw = e.target.value;
    setProfile((p) => ({
      ...p,
      [key]: ["annual_volume_units", "n_iterations"].includes(key)
        ? Math.max(1, parseInt(raw, 10) || 0)
        : key === "min_esg_score" ? Math.max(0, Math.min(100, parseFloat(raw) || 0))
        : ["hs_codes", "supplier_countries"].includes(key)
          ? raw.split(",").map((v) => v.trim()).filter(Boolean)
          : raw,
    }));
  };

  const worst = results.length
    ? results.reduce((a, b) => (a.risk_score > b.risk_score ? a : b))
    : null;
  const exposure = worst ? worst.cost_p95 - (worst.baseline_cost_mean || worst.cost_mean) : null;

  return (
    <div className="grid split">
      <div className="stack">
        <Card title="Manufacturer profile"
              caption="What the agents monitor and simulate against.">
          <div className="chips" style={{ marginBottom: 14 }}>
            {Object.entries(PRESETS).map(([key, p]) => (
              <button className="chip" key={key} aria-pressed={profile.name === p.name}
                      onClick={() => setProfile(p)}>{p.name}</button>
            ))}
          </div>

          <label className="field"><span>Company</span>
            <input value={profile.name} onChange={set("name")} /></label>

          <label className="field"><span>Industry</span>
            <select value={profile.industry} onChange={set("industry")}>
              {["fashion", "electronics", "automotive", "pharma", "other"].map((i) =>
                <option key={i} value={i}>{i}</option>)}
            </select></label>

          <label className="field"><span>Supplier countries</span>
            <input value={profile.supplier_countries.join(", ")} onChange={set("supplier_countries")} />
            <span className="hint">ISO-2 codes, comma separated. Blank sources from the whole network.</span></label>

          <label className="field"><span>HS codes</span>
            <input value={profile.hs_codes.join(", ")} onChange={set("hs_codes")} /></label>

          <label className="field"><span>Annual volume (units)</span>
            <input type="number" min="1" value={profile.annual_volume_units} onChange={set("annual_volume_units")} />
            <span className="hint">Simulated demand is one twelfth of this.</span></label>

          <label className="field"><span>Minimum portfolio ESG: {profile.min_esg_score}</span>
            <input type="range" min="0" max="100" step="1" value={profile.min_esg_score} onChange={set("min_esg_score")} />
            <span className="hint">Above 0 the optimiser must hit this weighted average exactly at demand.</span></label>

          <label className="field"><span>Monte Carlo iterations</span>
            <input type="number" min="100" max="50000" step="100" value={profile.n_iterations} onChange={set("n_iterations")} />
            <span className="hint">50,000 still returns in well under a second.</span></label>

          <button className="btn primary" style={{ width: "100%" }} disabled={busy}
                  onClick={() => onStart(profile)}>
            {busy ? "Running…" : "Run pipeline"}
          </button>
        </Card>

        <Card title="Pipeline" caption={run ? `Run ${run.run_id.slice(0, 8)} · ${run.status.replace(/_/g, " ")}` : "Not started"}>
          {run && (
            <div style={{ marginBottom: 14 }}>
              <ProgressBar pct={run.progress_pct} />
              <div className="row muted" style={{ fontSize: 11, marginTop: 6, justifyContent: "space-between" }}>
                <span>{Math.round(run.progress_pct)}%</span>
                <span>{run.duration_ms ? `${fmtNum(run.duration_ms)} ms` : ""}</span>
              </div>
            </div>
          )}
          <PipelineTimeline events={events} />
        </Card>
      </div>

      <div className="stack">
        {error && <div className="error-banner">{error}</div>}

        {run?.status === "awaiting_approval" && run.selected_recommendation && (
          <ApprovalPanel run={run} notes={notes} setNotes={setNotes} onDecide={onDecide} />
        )}

        {!run && <p className="empty">Configure a profile on the left and run the pipeline to see results.</p>}

        {run && results.length > 0 && (
          <>
            <div className="grid tiles">
              <StatTile label="Worst-case P95 cost" value={fmtCompactUSD(worst.cost_p95)}
                        delta={exposure > 0 ? `↑ ${fmtCompactUSD(exposure)} over baseline` : "at baseline"}
                        deltaTone={exposure > 0 ? "bad" : "good"} />
              <StatTile label="Service level" value={fmtPct(worst.service_level_pct)}
                        hint={`${fmtPct(worst.infeasible_pct)} of iterations short`} />
              <StatTile label="Portfolio ESG" value={fmtNum(worst.esg_score_mean, 1)} unit="/100"
                        hint={profile.min_esg_score > 0 ? `floor ${profile.min_esg_score} enforced` : "no floor set"} />
              <StatTile label="Mean delay" value={fmtNum(worst.delay_mean, 1)} unit=" d"
                        hint={`P95 ${fmtNum(worst.delay_p95, 1)} d`} />
              <StatTile label="Iterations simulated" value={fmtNum(results.reduce((n, r) => n + r.iterations, 0))}
                        hint={`${results.length} scenarios in ${fmtNum(run.compute_ms)} ms of compute`} />
            </div>

            <Card title="Scenario comparison"
                  caption="Mean landed cost with its P5–P95 band, ordered by risk. Click a row to inspect it below.">
              <ScenarioCompare results={results} selectedId={selected?.scenario_id} onSelect={setSelectedScenario} />
            </Card>

            {selected && (
              <div className="grid cols-2">
                <Card title={`Cost distribution — ${selected.scenario_name}`}
                      caption={`${fmtNum(selected.iterations)} iterations. The P95 line is the tail the governance tier keys off.`}>
                  <CostDistribution result={selected} />
                </Card>
                <Card title="The cost of ESG"
                      caption="Re-solved at each floor level: what tightening the ESG requirement does to landed cost.">
                  {selected.efficient_frontier?.length > 1
                    ? <EfficientFrontier frontier={selected.efficient_frontier} currentFloor={profile.min_esg_score} />
                    : <ParetoFront result={selected} />}
                </Card>
              </div>
            )}

            <div className="grid cols-2">
              <Card title="Country risk"
                    caption="Scored by the monitor agent from event severity, type and recency.">
                <CountryRisk risks={run.risk_scores} />
              </Card>
              {selected && (
                <Card title="Optimal supplier mix"
                      caption={`Where the optimiser routes volume under ${selected.scenario_name}.`}>
                  <SupplierMix mix={selected.supplier_mix} />
                </Card>
              )}
            </div>

            <Card title="Recommendations"
                  caption={run.narrative || "Ranked by risk reduction, then cost."}>
              <div className="stack" style={{ gap: 12 }}>
                {run.recommendations.map((r, i) => (
                  <RecommendationRow key={r.id} rec={r} top={i === 0} />
                ))}
              </div>
            </Card>

            {run.execution_log?.length > 0 && (
              <Card title="Execution log" caption={`Status: ${run.execution_status}`}>
                <div className="log">{run.execution_log.join("\n")}</div>
              </Card>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function RecommendationRow({ rec, top }) {
  const saves = (rec.cost_delta_usd || 0) < 0;
  return (
    <div style={{
      border: `1px solid ${top ? "var(--series-1)" : "var(--border)"}`,
      borderRadius: "var(--radius-sm)", padding: 12,
    }}>
      <div className="row" style={{ gap: 8, marginBottom: 6 }}>
        <Badge tone={top ? "good" : "neutral"}>{rec.rec_type.replace(/_/g, " ")}</Badge>
        {top && <span className="muted" style={{ fontSize: 11 }}>selected</span>}
        <span style={{ flex: 1 }} />
        <span className="muted" style={{ fontSize: 11 }}>
          {rec.authored_by === "llm" ? "LLM-authored" : "rule-based"} · {fmtPct(rec.confidence_pct, 0)} confidence
        </span>
      </div>
      <div style={{ fontSize: 13, fontWeight: 500, marginBottom: 4 }}>{rec.description}</div>
      <div className="muted" style={{ fontSize: 12, marginBottom: 8 }}>{rec.rationale}</div>
      <div className="row" style={{ gap: 18, fontSize: 12 }}>
        <span>
          Cost{" "}
          <b style={{ color: saves ? "var(--success-text)" : "var(--critical)" }}>
            {saves ? "↓ " : "↑ "}{fmtUSD(Math.abs(rec.cost_delta_usd))}
          </b>
        </span>
        <span>
          Risk <b style={{ color: "var(--success-text)" }}>↓ {Math.abs(rec.risk_delta).toFixed(2)}</b>
        </span>
        {/* An ESG drop is a real cost of the action - show it as one, not neutrally. */}
        <span>
          ESG{" "}
          <b style={{ color: rec.esg_delta > 0 ? "var(--success-text)"
                           : rec.esg_delta < 0 ? "var(--critical)" : "var(--text-primary)" }}>
            {rec.esg_delta > 0 ? "↑ " : rec.esg_delta < 0 ? "↓ " : "− "}
            {Math.abs(rec.esg_delta).toFixed(1)}
          </b>
        </span>
      </div>
    </div>
  );
}

function ApprovalPanel({ run, notes, setNotes, onDecide }) {
  const rec = run.selected_recommendation;
  const tier = (run.hitl_tier || "").replace(/_/g, "-");
  return (
    <Card title="Approval required"
          caption={`This decision exceeds the auto-approve threshold and is escalated to the ${tier} tier.`}
          style={{ borderColor: "var(--warning)", borderWidth: 2 }}>
      <div className="row" style={{ gap: 8, marginBottom: 10 }}>
        <Badge tone="serious">{tier} tier</Badge>
        <Badge tone="neutral">{rec.rec_type.replace(/_/g, " ")}</Badge>
        <span className="muted" style={{ fontSize: 12 }}>
          {fmtUSD(Math.abs(rec.cost_delta_usd))} cost impact
        </span>
      </div>
      <p style={{ fontSize: 13, marginTop: 0 }}>{rec.description}</p>
      <p className="muted" style={{ fontSize: 12 }}>{rec.rationale}</p>
      <label className="field"><span>Approver notes</span>
        <textarea rows="2" value={notes} onChange={(e) => setNotes(e.target.value)}
                  placeholder="Optional — recorded in the audit trail" /></label>
      <div className="btn-row">
        <button className="btn approve" onClick={() => onDecide("approve", notes)}>Approve &amp; execute</button>
        <button className="btn reject" onClick={() => onDecide("reject", notes)}>Reject &amp; re-analyse</button>
      </div>
    </Card>
  );
}

// ── Governance ─────────────────────────────────────────────────────────────

export function GovernanceView({ onOpenRun }) {
  const [runs, setRuns] = useState([]);
  const [audit, setAudit] = useState([]);
  const [err, setErr] = useState(null);

  useEffect(() => {
    const load = () =>
      Promise.all([api.listRuns(50), api.audit()])
        .then(([r, a]) => { setRuns(r); setAudit(a); setErr(null); })
        .catch((e) => setErr(e.message));
    load();
    const id = setInterval(load, 4000);
    return () => clearInterval(id);
  }, []);

  const pending = runs.filter((r) => r.status === "awaiting_approval");

  return (
    <div className="stack">
      {err && <div className="error-banner">{err}</div>}

      <div className="grid tiles">
        <StatTile label="Awaiting approval" value={fmtNum(pending.length)}
                  delta={pending.length ? "action required" : "clear"}
                  deltaTone={pending.length ? "bad" : "good"} />
        <StatTile label="Total runs" value={fmtNum(runs.length)} />
        <StatTile label="Decisions logged" value={fmtNum(audit.length)} />
        <StatTile label="Auto-approved"
                  value={fmtNum(audit.filter((a) => a.tier === "auto").length)}
                  hint="under the $10k threshold" />
      </div>

      <Card title="Approval queue"
            caption="Runs paused at the HITL gate. The pipeline is suspended until a decision is recorded.">
        {pending.length === 0 ? (
          <p className="empty">Nothing awaiting approval.</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead><tr>
                <th>Run</th><th>Manufacturer</th><th>Tier</th><th>Recommendation</th>
                <th className="num">Cost impact</th><th>Started</th><th></th>
              </tr></thead>
              <tbody>
                {pending.map((r) => (
                  <tr key={r.run_id}>
                    <td className="num">{r.run_id.slice(0, 8)}</td>
                    <td>{r.manufacturer}</td>
                    <td><Badge tone="serious">{(r.hitl_tier || "").replace(/_/g, "-")}</Badge></td>
                    <td style={{ whiteSpace: "normal", maxWidth: 380 }}>{r.top_recommendation}</td>
                    <td className="num">{fmtUSD(Math.abs(r.cost_delta_usd || 0))}</td>
                    <td>{fmtRelative(r.created_at)}</td>
                    <td><button className="btn ghost" onClick={() => onOpenRun(r.run_id)}>Review</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card title="Audit trail"
            caption="Every governance decision, newest first — who decided, on what, and what happened next.">
        {audit.length === 0 ? (
          <p className="empty">No decisions recorded yet.</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead><tr>
                <th>Decided</th><th>Manufacturer</th><th>Action</th><th>Tier</th>
                <th>Decision</th><th>Approver</th><th className="num">Cost impact</th><th>Outcome</th>
              </tr></thead>
              <tbody>
                {audit.map((a, i) => (
                  <tr key={`${a.run_id}-${i}`}>
                    <td>{fmtRelative(a.decided_at)}</td>
                    <td>{a.manufacturer}</td>
                    <td>{(a.rec_type || "—").replace(/_/g, " ")}</td>
                    <td>{(a.tier || "—").replace(/_/g, "-")}</td>
                    <td>
                      <Badge tone={a.decision === "approve" ? "good" : a.decision === "reject" ? "critical" : "neutral"}>
                        {a.decision}
                      </Badge>
                    </td>
                    <td>{a.approver || "—"}</td>
                    <td className="num">{fmtUSD(Math.abs(a.cost_delta_usd || 0))}</td>
                    <td>{a.execution_status || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card title="Escalation policy" caption="Applied automatically to every recommendation.">
        <div className="table-wrap">
          <table>
            <thead><tr><th>Cost impact</th><th>Tier</th><th>Approval window</th><th>Behaviour</th></tr></thead>
            <tbody>
              <tr><td>Under $10,000</td><td><Badge tone="good">auto</Badge></td><td>—</td>
                  <td>Executed without pausing</td></tr>
              <tr><td>$10,000 – $100,000</td><td><Badge tone="warning">manager</Badge></td><td>24 hours</td>
                  <td>Pipeline suspends at the gate</td></tr>
              <tr><td>Over $100,000, or any supplier switch</td><td><Badge tone="critical">c-suite</Badge></td><td>48 hours</td>
                  <td>Pipeline suspends at the gate</td></tr>
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}

// ── ESG ────────────────────────────────────────────────────────────────────

export function EsgView({ esg }) {
  const [standard, setStandard] = useState("GRI");
  const [report, setReport] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    setReport(null);
    fetch("/api/v1/esg/report", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ standard }),
    })
      .then((r) => r.json())
      .then(setReport)
      .catch((e) => setErr(e.message));
  }, [standard]);

  if (!esg?.length) return <p className="empty">Loading ESG data…</p>;

  const top = esg[0], bottom = esg[esg.length - 1];
  const mean = esg.reduce((s, e) => s + e.composite_score, 0) / esg.length;
  const certified = esg.filter((e) => e.breakdown?.certifications?.ISO14001).length;

  return (
    <div className="stack">
      {err && <div className="error-banner">{err}</div>}

      <div className="grid tiles">
        <StatTile label="Mean composite ESG" value={fmtNum(mean, 1)} unit="/100"
                  hint={`${esg.length} suppliers scored`} />
        <StatTile label="Best performer" value={fmtNum(top.composite_score, 1)} hint={top.supplier_name} />
        <StatTile label="Weakest link" value={fmtNum(bottom.composite_score, 1)}
                  delta={`${fmtNum(top.composite_score - bottom.composite_score, 1)} point spread`}
                  deltaTone="bad" hint={bottom.supplier_name} />
        <StatTile label="ISO 14001 certified" value={fmtPct((100 * certified) / esg.length, 0)}
                  hint={`${certified} of ${esg.length} suppliers`} />
      </div>

      <Card title="ESG composition by supplier"
            caption="Stacked contribution to the composite score: environmental 40%, social 35%, governance 25%.">
        <EsgBreakdown suppliers={esg} limit={12} />
      </Card>

      <Card title="Disclosure report"
            caption="Portfolio figures mapped onto a reporting standard, capacity-weighted."
            actions={
              <div className="chips">
                {["GRI", "SASB", "raw"].map((s) => (
                  <button className="chip" key={s} aria-pressed={standard === s} onClick={() => setStandard(s)}>{s}</button>
                ))}
              </div>
            }>
        {!report ? <p className="empty">Generating…</p> : (
          <div className="log" style={{ maxHeight: 340 }}>{JSON.stringify(report, null, 2)}</div>
        )}
      </Card>

      <Card title="Full leaderboard" caption="Ranked by composite score.">
        <div className="table-wrap">
          <table>
            <thead><tr>
              <th className="num">#</th><th>Supplier</th><th>Country</th>
              <th className="num">Environmental</th><th className="num">Social</th><th className="num">Governance</th>
              <th className="num">Composite</th><th className="num">CO₂/unit</th>
            </tr></thead>
            <tbody>
              {esg.map((s) => (
                <tr key={s.supplier_id}>
                  <td className="num">{s.rank}</td>
                  <td>{s.supplier_name}</td>
                  <td>{s.country_code}</td>
                  <td className="num">{fmtNum(s.environmental, 1)}</td>
                  <td className="num">{fmtNum(s.social, 1)}</td>
                  <td className="num">{fmtNum(s.governance, 1)}</td>
                  <td className="num"><b>{fmtNum(s.composite_score, 1)}</b></td>
                  <td className="num">{fmtNum(s.breakdown?.avg_co2_kg_per_unit, 2)} kg</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}

export { StatusBadge, riskStatus };
