// Screenshot config for the resilience dashboard.
//
// Notes for the next run:
//  * `npm start` boots BOTH the FastAPI backend (:8000) and Vite (:5173); the
//    readyPath must be the Vite port, not the API's.
//  * The dashboard renders from an in-memory catalog, so no DB seeding step is
//    needed and no real supplier data is ever in frame.
//  * A pipeline run finishes in a few hundred ms, but the SSE stream and the
//    follow-up detail fetch need ~2s to settle before the charts are populated.
//  * The fashion preset (ESG floor 60) escalates to the c-suite tier, which is
//    what puts the approval panel on screen for shot 03.

export default {
  server: {
    command: "npm start",
    readyPath: "http://localhost:5173/",
    readyTimeoutMs: 90_000,
  },
  baseUrl: "http://localhost:5173",
  viewport: { width: 1440, height: 900 },
  colorScheme: "dark",

  shots: [
    {
      name: "01-network-overview",
      shows: "Supplier network: capacity concentration by country and the live disruption feed",
      path: "/",
      waitFor: ".tile",
      settleMs: 800,
    },
    {
      name: "02-simulation-results",
      shows: "Monte Carlo results: scenario comparison, cost distribution and the ESG cost curve",
      path: "/",
      waitFor: ".tile",
      async prepare(page) {
        await page.getByRole("tab", { name: "Simulate" }).click();
        await page.getByRole("button", { name: "Run pipeline" }).click();
        // Wait for the scenario comparison chart, then let the SSE stream settle.
        await page.waitForSelector('svg[aria-label="Cost by scenario"]', { timeout: 30_000 });
        await page.waitForTimeout(2500);
        // Scroll the charts into the upper two-thirds of the frame.
        await page.evaluate(() => document.querySelector(".main")?.scrollIntoView());
        await page.mouse.wheel(0, 420);
        await page.waitForTimeout(400);
      },
      settleMs: 600,
    },
    {
      name: "03-hitl-approval",
      shows: "Pipeline suspended at the human-in-the-loop gate, awaiting a c-suite approval decision",
      path: "/",
      waitFor: ".tile",
      async prepare(page) {
        await page.getByRole("tab", { name: "Simulate" }).click();
        await page.getByRole("button", { name: "Run pipeline" }).click();
        await page.waitForSelector("text=Approval required", { timeout: 30_000 });
        await page.waitForTimeout(1500);
      },
      settleMs: 600,
    },
    {
      name: "04-recommendations",
      shows: "Ranked mitigations with cost, risk and ESG deltas, plus the optimal supplier mix",
      path: "/",
      waitFor: ".tile",
      async prepare(page) {
        await page.getByRole("tab", { name: "Simulate" }).click();
        await page.getByRole("button", { name: "Run pipeline" }).click();
        await page.waitForSelector("text=Approval required", { timeout: 30_000 });
        await page.getByRole("button", { name: /Approve/ }).click();
        await page.waitForSelector('svg[aria-label="Supplier allocation share"]', { timeout: 20_000 });
        await page.waitForTimeout(2000);
        await page.mouse.wheel(0, 1900);
        await page.waitForTimeout(400);
      },
      settleMs: 600,
    },
    {
      name: "05-governance-audit",
      shows: "Governance: approval queue, audit trail of every decision, and the escalation policy",
      path: "/",
      waitFor: ".tile",
      async prepare(page) {
        // Produce one decided run so the audit trail is not empty.
        await page.getByRole("tab", { name: "Simulate" }).click();
        await page.getByRole("button", { name: "Run pipeline" }).click();
        await page.waitForSelector("text=Approval required", { timeout: 30_000 });
        await page.getByRole("button", { name: /Approve/ }).click();
        await page.waitForTimeout(1500);
        await page.getByRole("tab", { name: "Governance" }).click();
        await page.waitForTimeout(1200);
      },
      settleMs: 600,
    },
    {
      name: "06-esg-scoring",
      shows: "ESG: stacked environmental/social/governance composition and the supplier leaderboard",
      path: "/",
      waitFor: ".tile",
      async prepare(page) {
        await page.getByRole("tab", { name: "ESG" }).click();
        await page.waitForSelector('svg[aria-label="Supplier ESG composition"]', { timeout: 20_000 });
        await page.waitForTimeout(800);
      },
      settleMs: 600,
    },
    {
      name: "07-network-light",
      shows: "The same network view in light theme, showing the dual-mode design system",
      path: "/",
      waitFor: ".tile",
      colorScheme: "light",
      async prepare(page) {
        await page.selectOption('select[aria-label="Colour theme"]', "light");
        await page.waitForTimeout(500);
      },
      settleMs: 600,
    },
  ],
};
