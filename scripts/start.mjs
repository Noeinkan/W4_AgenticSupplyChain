#!/usr/bin/env node
/**
 * `npm start` - boots the API and the dashboard together.
 *
 * Deliberately dependency-free: it runs before `npm install` has put anything in
 * the root node_modules, so it cannot rely on concurrently, cross-env or chalk.
 * It handles the three things that otherwise break a fresh clone on Windows:
 *
 *   1. PYTHONPATH=src, which every command in this repo needs
 *   2. finding a Python that actually has the dependencies installed
 *   3. installing web/node_modules on first run, before starting Vite
 *
 * Ctrl+C stops both processes.
 */

import { spawn, spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = dirname(dirname(fileURLToPath(import.meta.url)));
const WEB = join(ROOT, "web");
const IS_WIN = process.platform === "win32";
const NPM = IS_WIN ? "npm.cmd" : "npm";

const C = {
  reset: "\x1b[0m", dim: "\x1b[2m", bold: "\x1b[1m",
  blue: "\x1b[34m", magenta: "\x1b[35m", red: "\x1b[31m", green: "\x1b[32m", yellow: "\x1b[33m",
};

const REQUIRED = ["fastapi", "uvicorn", "numpy", "pydantic_settings", "httpx"];

function findPython() {
  const candidates = process.env.PYTHON ? [process.env.PYTHON] : ["python", "python3", "py"];
  const probe = `import importlib.util as u,sys; sys.exit(0 if all(u.find_spec(m) for m in ${JSON.stringify(REQUIRED)}) else 1)`;

  let found = null;
  for (const bin of candidates) {
    const version = spawnSync(bin, ["--version"], { encoding: "utf8" });
    if (version.status !== 0) continue;
    found = bin;
    if (spawnSync(bin, ["-c", probe], { encoding: "utf8" }).status === 0) return { bin, ready: true };
  }
  return found ? { bin: found, ready: false } : null;
}

function fail(message, hint) {
  console.error(`\n${C.red}${C.bold}✗ ${message}${C.reset}`);
  if (hint) console.error(`${C.dim}  ${hint}${C.reset}\n`);
  process.exit(1);
}

// ── preflight ───────────────────────────────────────────────────────────────

const python = findPython();
if (!python) {
  fail("No Python interpreter found.", "Install Python 3.11+ and make sure `python` is on PATH.");
}
if (!python.ready) {
  fail(
    "Python is installed but the backend dependencies are missing.",
    `Run:  ${python.bin} -m pip install -r requirements.txt`
  );
}

if (!existsSync(join(WEB, "node_modules"))) {
  console.log(`${C.dim}Installing dashboard dependencies (first run only)…${C.reset}`);
  const install = spawnSync(NPM, ["install"], { cwd: WEB, stdio: "inherit", shell: IS_WIN });
  if (install.status !== 0) fail("npm install failed in web/.");
}

// ── launch ──────────────────────────────────────────────────────────────────

const children = [];

function launch(name, color, command, args, options) {
  const child = spawn(command, args, {
    ...options,
    stdio: ["ignore", "pipe", "pipe"],
    shell: IS_WIN && command.endsWith(".cmd"),
  });
  const tag = `${color}${name.padEnd(3)}${C.reset} ${C.dim}|${C.reset} `;

  const relay = (stream, out) => {
    let buffer = "";
    stream.on("data", (chunk) => {
      buffer += chunk.toString();
      const lines = buffer.split("\n");
      buffer = lines.pop();
      for (const line of lines) out.write(`${tag}${line}\n`);
    });
  };
  relay(child.stdout, process.stdout);
  relay(child.stderr, process.stdout);

  child.on("exit", (code) => {
    if (!shuttingDown) {
      console.log(`\n${tag}exited with code ${code}`);
      shutdown(code ?? 1);
    }
  });

  children.push(child);
  return child;
}

let shuttingDown = false;
function shutdown(code = 0) {
  if (shuttingDown) return;
  shuttingDown = true;
  for (const child of children) {
    try {
      if (IS_WIN) spawnSync("taskkill", ["/pid", String(child.pid), "/T", "/F"], { stdio: "ignore" });
      else child.kill("SIGTERM");
    } catch {
      /* already gone */
    }
  }
  setTimeout(() => process.exit(code), 150);
}

process.on("SIGINT", () => shutdown(0));
process.on("SIGTERM", () => shutdown(0));

console.log(`
${C.bold}Agentic Supply-Chain Resilience Orchestrator${C.reset}
${C.dim}  python   ${python.bin}
  api      http://localhost:8000    (docs at /docs)
  dashboard http://localhost:5173   ${C.reset}
`);

launch("api", C.blue, python.bin, ["-m", "uvicorn", "orchestrator.main:app", "--host", "127.0.0.1", "--port", "8000"], {
  cwd: ROOT,
  env: { ...process.env, PYTHONPATH: join(ROOT, "src"), PYTHONUNBUFFERED: "1" },
});

launch("web", C.magenta, NPM, ["run", "dev"], { cwd: WEB, env: process.env });
