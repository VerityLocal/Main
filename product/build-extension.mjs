// One Chrome/Edge package for macOS and Windows; analysis still needs the companion.
import { extensionFiles } from "./build.mjs";
import { createZip } from "./zip.mjs";
import { lstat, mkdir, readFile, readdir, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";

const root = path.dirname(fileURLToPath(import.meta.url));
const output = path.join(root, "dist/downloads");
const archive = path.join(output, "Verity-Extension.zip");
try {
  if ((await lstat(output)).isSymbolicLink()) throw new Error("The extension download output cannot be a symlink");
  for (const entry of await readdir(output, { withFileTypes: true })) {
    if (!entry.isFile() || entry.name !== "Verity-Extension.zip") throw new Error(`Unexpected extension download file: ${entry.name}. Nothing was deleted.`);
  }
} catch (error) { if (error.code !== "ENOENT") throw error; }
const entries = [];
for (const name of [...extensionFiles].sort()) {
  const source = path.join(root, "dist/chrome", name);
  if (!(await lstat(source)).isFile()) throw new Error("Extension inputs must be regular files");
  entries.push({ name: "Verity Extension/" + name, data: await readFile(source) });
}
entries.push({ name: "INSTALL.txt", data: Buffer.from("Verity browser extension — development build\n\nThis same Chrome/Edge extension works on macOS and Windows. PDF extraction and analysis require the matching Verity desktop companion; this ZIP does not replace it. Companion installers already include the extension.\n\nInstall the matching companion first. Extract this ZIP, open chrome://extensions or edge://extensions, enable Developer mode, choose Load unpacked, and select the Verity Extension folder. Pairing and helper startup are automatic. No approved AI checkpoints/calibration are included; AI estimates remain unavailable.\n\nDownloads, setup and unsigned-build warnings: https://veritylocal.github.io/\n") });
await mkdir(output, { recursive: true });
await writeFile(archive, createZip(entries));
console.log(`Shared Chrome/Edge extension: ${archive}`);
