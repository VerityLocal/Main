// Explicit first-party allowlist. Never copy the repository or legacy release.
import { readFile, writeFile, mkdir, copyFile, readdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";
const root = path.dirname(fileURLToPath(import.meta.url));
const files = ["panel.html", "panel.css", "panel.js", "background.js", "content.js", "capture.js", "reader.js", "connection.js", "icon.svg", "calibration.json"];
export const extensionFiles = [...files, "manifest.json"];
const manifest = JSON.parse(await readFile(path.join(root, "extension/manifest.json"), "utf8"));
for (const target of ["chrome", "firefox"]) {
  const out = path.join(root, "dist", target);
  await mkdir(out, { recursive: true });
  const unexpected = (await readdir(out)).filter(file => ![...files, "manifest.json"].includes(file));
  if (unexpected.length) throw new Error(`Unexpected files in ${out}: ${unexpected.join(", ")}. Review and move them before building; nothing was deleted.`);
  for (const file of files) await copyFile(path.join(root, "extension", file), path.join(out, file));
  const value = structuredClone(manifest);
  if (target === "firefox") {
    delete value.key;
    delete value.minimum_chrome_version;
    delete value.side_panel;
    value.permissions = value.permissions.filter(x => x !== "sidePanel");
    value.background = { scripts: ["background.js"], type: "module" };
    value.action.default_popup = "panel.html";
    value.browser_specific_settings = { gecko: { id: "verity@local.invalid", strict_min_version: "128.0", data_collection_permissions: { required: ["none"], optional: ["websiteContent"] } } };
  }
  await writeFile(path.join(out, "manifest.json"), JSON.stringify(value, null, 2) + "\n");
}
console.log("Extension built: product/dist/chrome and product/dist/firefox");
