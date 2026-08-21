// Thin fetch wrapper. All calls go through the Vite dev proxy, so the browser
// only ever makes same-origin requests and there is no CORS story in dev.

async function request(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body?.detail) detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* response had no JSON body; keep the status line */
    }
    throw new Error(detail);
  }
  return res.status === 204 ? null : res.json();
}

export const api = {
  health: () => request("/health/"),
  overview: () => request("/api/v1/catalog/overview"),
  suppliers: () => request("/api/v1/catalog/suppliers"),
  routes: () => request("/api/v1/catalog/routes"),
  events: () => request("/api/v1/catalog/events"),
  scenarios: () => request("/api/v1/catalog/scenarios"),
  esg: () => request("/api/v1/catalog/esg"),

  listRuns: (limit = 25) => request(`/api/v1/pipeline/runs?limit=${limit}`),
  getRun: (id) => request(`/api/v1/pipeline/runs/${id}`),
  startRun: (profile) =>
    request("/api/v1/pipeline/runs", {
      method: "POST",
      body: JSON.stringify({ manufacturer_profile: profile }),
    }),
  decide: (id, decision, approver, notes) =>
    request(`/api/v1/pipeline/runs/${id}/decision`, {
      method: "POST",
      body: JSON.stringify({ decision, approver, notes }),
    }),
  pending: () => request("/api/v1/pipeline/pending"),
  audit: () => request("/api/v1/pipeline/audit"),
};

/**
 * Subscribe to a run's server-sent event stream.
 *
 * The backend replays the run's whole event history on connect, so a browser
 * that opens the stream late still renders every node, not just the tail.
 * Returns an unsubscribe function.
 */
export function streamRun(runId, { onEvent, onEnd, onError }) {
  const source = new EventSource(`/api/v1/pipeline/runs/${runId}/stream`);

  source.onmessage = (msg) => {
    try {
      onEvent?.(JSON.parse(msg.data));
    } catch {
      /* keepalive comments and malformed frames are not fatal */
    }
  };
  source.addEventListener("end", (msg) => {
    try {
      onEnd?.(JSON.parse(msg.data));
    } catch {
      onEnd?.(null);
    }
    source.close();
  });
  source.onerror = () => {
    // EventSource retries on its own; only surface a hard close.
    if (source.readyState === EventSource.CLOSED) onError?.(new Error("Stream closed"));
  };

  return () => source.close();
}

// ── formatting ─────────────────────────────────────────────────────────────

export const fmtUSD = (n, digits = 0) =>
  n == null || !Number.isFinite(n)
    ? "—"
    : new Intl.NumberFormat("en-US", {
        style: "currency", currency: "USD",
        minimumFractionDigits: digits, maximumFractionDigits: digits,
      }).format(n);

export const fmtCompactUSD = (n) => {
  if (n == null || !Number.isFinite(n)) return "—";
  const abs = Math.abs(n);
  const sign = n < 0 ? "-" : "";
  if (abs >= 1e9) return `${sign}$${(abs / 1e9).toFixed(1)}B`;
  if (abs >= 1e6) return `${sign}$${(abs / 1e6).toFixed(2)}M`;
  if (abs >= 1e3) return `${sign}$${(abs / 1e3).toFixed(0)}k`;
  return `${sign}$${abs.toFixed(0)}`;
};

export const fmtNum = (n, digits = 0) =>
  n == null || !Number.isFinite(n)
    ? "—"
    : new Intl.NumberFormat("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(n);

export const fmtPct = (n, digits = 1) =>
  n == null || !Number.isFinite(n) ? "—" : `${n.toFixed(digits)}%`;

export const fmtTime = (iso) => {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
};

export const fmtRelative = (iso) => {
  if (!iso) return "—";
  const secs = (Date.now() - new Date(iso).getTime()) / 1000;
  if (secs < 60) return "just now";
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
  if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`;
  return `${Math.floor(secs / 86400)}d ago`;
};

/** Severity 1–5 and risk 0–1 both map onto the reserved status vocabulary. */
export const severityStatus = (sev) =>
  sev >= 5 ? "critical" : sev >= 4 ? "serious" : sev >= 3 ? "warning" : "neutral";

export const riskStatus = (risk) =>
  risk >= 0.66 ? "critical" : risk >= 0.4 ? "serious" : risk >= 0.2 ? "warning" : "good";
