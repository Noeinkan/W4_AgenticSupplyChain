#!/usr/bin/env node
/** `npm run api` - backend only, with PYTHONPATH already set. */
import { spawn } from "node:child_process";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = dirname(dirname(fileURLToPath(import.meta.url)));
const bin = process.env.PYTHON || "python";

spawn(bin, ["-m", "uvicorn", "orchestrator.main:app", "--reload", "--port", "8000"], {
  cwd: ROOT,
  stdio: "inherit",
  env: { ...process.env, PYTHONPATH: join(ROOT, "src") },
}).on("exit", (code) => process.exit(code ?? 0));
