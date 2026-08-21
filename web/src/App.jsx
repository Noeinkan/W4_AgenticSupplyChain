import { useCallback, useEffect, useRef, useState } from "react";
import { api, streamRun } from "./api";
import { Badge } from "./components/ui";
import { EsgView, GovernanceView, NetworkView, SimulateView } from "./views";

const TABS = [
  ["network", "Network"],
  ["simulate", "Simulate"],
  ["governance", "Governance"],
  ["esg", "ESG"],
];

/** Theme choice persists per browser; a failed storage read must not blank the app. */
function useTheme() {
  const [theme, setTheme] = useState(() => {
    try {
      return localStorage.getItem("theme") || "system";
    } catch {
      return "system";
    }
  });

  useEffect(() => {
    const root = document.documentElement;
    if (theme === "system") root.removeAttribute("data-theme");
    else root.setAttribute("data-theme", theme);
    try {
      localStorage.setItem("theme", theme);
    } catch {
      /* private mode or blocked site data — the theme just won't persist */
    }
  }, [theme]);

  return [theme, setTheme];
}

export default function App() {
  const [tab, setTab] = useState("network");
  const [theme, setTheme] = useTheme();

  const [health, setHealth] = useState(null);
  const [overview, setOverview] = useState(null);
  const [suppliers, setSuppliers] = useState([]);
  const [esg, setEsg] = useState([]);

  const [run, setRun] = useState(null);
  const [events, setEvents] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const unsubscribe = useRef(null);

  useEffect(() => {
    Promise.all([api.health(), api.overview(), api.suppliers(), api.esg()])
      .then(([h, o, s, e]) => { setHealth(h); setOverview(o); setSuppliers(s); setEsg(e); })
      .catch((e) => setError(`Cannot reach the API — is the backend running? (${e.message})`));
    return () => unsubscribe.current?.();
  }, []);

  const attach = useCallback((runId) => {
    unsubscribe.current?.();
    unsubscribe.current = streamRun(runId, {
      onEvent: (evt) => {
        setEvents((prev) => [...prev, evt]);
        // Pull the full run whenever a node finishes, so charts fill in live.
        if (["done", "awaiting_approval", "failed"].includes(evt.status)) {
          api.getRun(runId).then(setRun).catch(() => {});
        }
      },
      onEnd: () => {
        api.getRun(runId).then(setRun).catch(() => {});
        setBusy(false);
      },
      onError: () => setBusy(false),
    });
  }, []);

  const startRun = useCallback(async (profile) => {
    setBusy(true);
    setError(null);
    setEvents([]);
    setRun(null);
    try {
      const { run_id } = await api.startRun(profile);
      const detail = await api.getRun(run_id);
      setRun(detail);
      attach(run_id);
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  }, [attach]);

  const openRun = useCallback(async (runId) => {
    setTab("simulate");
    setError(null);
    try {
      const detail = await api.getRun(runId);
      setRun(detail);
      setEvents(detail.events || []);
      if (detail.status === "awaiting_approval") {
        setBusy(true);
        attach(runId);
      }
    } catch (e) {
      setError(e.message);
    }
  }, [attach]);

  const decide = useCallback(async (decision, notes) => {
    if (!run) return;
    try {
      await api.decide(run.run_id, decision, "dashboard_user", notes || null);
      setBusy(true);
    } catch (e) {
      setError(e.message);
    }
  }, [run]);

  const llm = health?.llm;

  return (
    <div className="app">
      <header className="topbar">
        <div>
          <h1>Supply-Chain Resilience Orchestrator</h1>
          <div className="sub">
            Monitor → analyse → simulate → recommend → govern → execute
          </div>
        </div>
        <span className="spacer" />

        {health && (
          <div className="row" style={{ gap: 8 }}>
            <Badge tone={health.data_backend === "db" ? "good" : "neutral"}>
              data: {health.data_backend}
            </Badge>
            <Badge tone={llm?.available ? "good" : "warning"}>
              llm: {llm?.provider}{llm?.provider !== "none" ? ` · ${llm?.model}` : ""}
            </Badge>
          </div>
        )}

        <select className="chip" value={theme} onChange={(e) => setTheme(e.target.value)}
                aria-label="Colour theme" style={{ padding: "5px 8px" }}>
          <option value="system">System theme</option>
          <option value="light">Light</option>
          <option value="dark">Dark</option>
        </select>
        <a className="chip" href="/docs" target="_blank" rel="noreferrer"
           style={{ textDecoration: "none" }}>API docs</a>
      </header>

      <nav className="tabs" role="tablist">
        {TABS.map(([key, label]) => (
          <button key={key} className="tab" role="tab" aria-selected={tab === key}
                  onClick={() => setTab(key)}>{label}</button>
        ))}
      </nav>

      <main className="main">
        {error && tab !== "simulate" && <div className="error-banner">{error}</div>}

        {tab === "network" && <NetworkView overview={overview} suppliers={suppliers} />}
        {tab === "simulate" && (
          <SimulateView run={run} events={events} busy={busy} error={error}
                        onStart={startRun} onDecide={decide} />
        )}
        {tab === "governance" && <GovernanceView onOpenRun={openRun} />}
        {tab === "esg" && <EsgView esg={esg} />}
      </main>
    </div>
  );
}
