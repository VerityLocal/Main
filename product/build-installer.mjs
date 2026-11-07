// Build a first-party bootstrap app; runtimes are downloaded and verified on install.
import "./build.mjs";
import { createHash } from "node:crypto";
import { copyFile, mkdir, readFile, readdir, writeFile, chmod, lstat } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";
import path from "node:path";

const root = path.dirname(fileURLToPath(import.meta.url));
const source = path.join(root, "installer");
const output = path.join(root, "dist/installer/macos");
const app = path.join(output, "Verity Installer.app");
const contents = path.join(app, "Contents");
const resources = path.join(contents, "Resources");
const payload = path.join(resources, "payload");
const manifest = JSON.parse(await readFile(path.join(root, "extension/manifest.json"), "utf8"));
const pins = JSON.parse(await readFile(path.join(source, "runtime-pins.json"), "utf8"));
const hash = createHash("sha256").update(Buffer.from(manifest.key, "base64")).digest().subarray(0, 16);
const id = [...hash].map(b => String.fromCharCode(97 + (b >> 4), 97 + (b & 15))).join("");
const engineFiles = ["__init__.py", "ai.py", "assets.py", "calibration.py", "detection.py", "local_os.py", "native_host.py", "pdf.py", "server.py", "similarity.py", "text.py", "web.py"];
const extensionFiles = ["background.js", "calibration.json", "capture.js", "connection.js", "content.js", "icon.svg", "manifest.json", "panel.css", "panel.html", "panel.js", "reader.js"];
const allowed = new Set(["Contents/Info.plist", "Contents/MacOS/Verity Installer", "Contents/Resources/install-macos.sh", "Contents/Resources/runtime-pins.sh", ...["native_entry.py", "provision.py", "provision_entry.py", "release.json", "runtime-requirements.txt", "product/extension/calibration.json"].map(x => "Contents/Resources/payload/" + x), ...engineFiles.map(x => "Contents/Resources/payload/product/engine/" + x), ...["chrome", "firefox"].flatMap(browser => extensionFiles.map(x => "Contents/Resources/payload/" + browser + "-extension/" + x))]);
async function checkExisting(directory, relative = "") {
  let entries;
  try {
    if ((await lstat(directory)).isSymbolicLink()) throw new Error(`Unexpected installer symlink: ${directory}. Nothing was changed.`);
    entries = await readdir(directory, { withFileTypes: true });
  }
  catch (error) { if (error.code === "ENOENT") return; throw error; }
  for (const entry of entries) {
    const name = relative ? relative + "/" + entry.name : entry.name;
    if (entry.isSymbolicLink() || (!entry.isDirectory() && !allowed.has(name)) || (entry.isDirectory() && ![...allowed].some(file => file.startsWith(name + "/")))) throw new Error(`Unexpected installer file: ${name}. Review and move it before building; nothing was deleted.`);
    if (entry.isDirectory()) await checkExisting(path.join(directory, entry.name), name);
  }
}
await checkExisting(app);
for (const directory of [path.join(contents, "MacOS"), path.join(payload, "product/engine"), path.join(payload, "product/extension"), path.join(payload, "chrome-extension"), path.join(payload, "firefox-extension")]) await mkdir(directory, { recursive: true });
for (const name of engineFiles) {
  await copyFile(path.join(root, "engine", name), path.join(payload, "product/engine", name));
}
for (const browser of ["chrome", "firefox"]) {
  for (const name of extensionFiles) await copyFile(path.join(root, "dist", browser, name), path.join(payload, browser + "-extension", name));
}
await copyFile(path.join(root, "extension/calibration.json"), path.join(payload, "product/extension/calibration.json"));
for (const name of ["native_entry.py", "provision.py", "provision_entry.py"]) await copyFile(path.join(source, name), path.join(payload, name));
await copyFile(path.join(root, "runtime-requirements.txt"), path.join(payload, "runtime-requirements.txt"));
await writeFile(path.join(payload, "release.json"), JSON.stringify({ engine_version: manifest.version, chrome_origin: "chrome-extension://" + id, firefox_id: "verity@local.invalid" }, null, 2) + "\n");
const lines = [];
for (const [arch, entry] of Object.entries(pins.macos)) {
  if (!/^https:\/\/github\.com\/astral-sh\/python-build-standalone\/releases\/download\//.test(entry.url) || !/^[a-f0-9]{64}$/.test(entry.sha256)) throw new Error("Invalid runtime pin");
  lines.push(`${arch.toUpperCase()}_URL='${entry.url}'`, `${arch.toUpperCase()}_SHA256='${entry.sha256}'`);
}
await writeFile(path.join(resources, "runtime-pins.sh"), lines.join("\n") + "\n");
await copyFile(path.join(source, "install-macos.sh"), path.join(resources, "install-macos.sh"));
await chmod(path.join(resources, "install-macos.sh"), 0o755);
const launcher = path.join(contents, "MacOS/Verity Installer");
await writeFile(launcher, '#!/bin/zsh\nexec "${0:A:h:h}/Resources/install-macos.sh"\n');
await chmod(launcher, 0o755);
await writeFile(path.join(contents, "Info.plist"), `<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n<plist version="1.0"><dict><key>CFBundleExecutable</key><string>Verity Installer</string><key>CFBundleIdentifier</key><string>local.verity.installer</string><key>CFBundleName</key><string>Verity Installer</string><key>CFBundlePackageType</key><string>APPL</string><key>CFBundleShortVersionString</key><string>${manifest.version}</string><key>LSMinimumSystemVersion</key><string>14.0</string><key>NSHighResolutionCapable</key><true/></dict></plist>\n`);
await writeFile(path.join(output, "DOWNLOAD-INFO.txt"), "Double-click Verity Installer.app, approve Install, then load the extension folder shown in Finder. Runtime installation, pairing and startup are automatic. First installation requires internet. This is an unsigned development build: public downloads require developer signing and notarization. Do not disable macOS security. No production AI weights are included.\n");
if (process.platform === "darwin") {
  const archive = path.join(output, "Verity-macOS.zip");
  const packed = spawnSync("/usr/bin/ditto", ["-c", "-k", "--sequesterRsrc", "--keepParent", app, archive], { stdio: "inherit" });
  if (packed.status !== 0) throw new Error("Installer packaging failed");
  console.log(`macOS installer: ${archive}`);
} else console.log(`macOS app generated: ${app} (archive/sign on macOS)`);
