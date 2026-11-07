// npm demo uses the separately provisioned local runtime.
import { spawnSync } from "node:child_process";
const python = process.platform === "win32" ? "product/.runtime/Scripts/python.exe" : "product/.runtime/bin/python";
const output = spawnSync(python, ["-m", "internal.demo.browser_run"], { stdio: "inherit" });
process.exit(output.status ?? 1);
