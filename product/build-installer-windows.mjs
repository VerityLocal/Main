// Cross-build a GUI bootstrap/native host; end users need neither Go nor Python.
import "./build.mjs";
import { createHash } from "node:crypto";
import { copyFile, lstat, mkdir, mkdtemp, readFile, readdir, rm, writeFile } from "node:fs/promises";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";

const root = path.dirname(fileURLToPath(import.meta.url));
const source = path.join(root, "installer");
const output = path.join(root, "dist/installer/windows");
const outputs = ["VeritySetup.exe", "VeritySetup.exe.sha256", "Verity-Windows.zip", "DOWNLOAD-INFO.txt", "THIRD-PARTY-NOTICES.txt"];
try {
  if ((await lstat(output)).isSymbolicLink()) throw new Error("The Windows installer output cannot be a symlink");
  for (const entry of await readdir(output, { withFileTypes: true })) {
    if (!entry.isFile() || !outputs.includes(entry.name)) throw new Error(`Unexpected Windows installer file: ${entry.name}. Review and move it before building; nothing was deleted.`);
  }
} catch (error) { if (error.code !== "ENOENT") throw error; }

const go = process.env.VERITY_GO || "go";
const nativeEnv = { ...process.env, CGO_ENABLED: "0", GOTOOLCHAIN: "local", GOOS: process.platform === "win32" ? "windows" : process.platform, GOARCH: process.arch === "x64" ? "amd64" : process.arch };
function run(args, directory, env = nativeEnv) {
  const result = spawnSync(go, args, { cwd: directory, env, encoding: "utf8" });
  if (result.error?.code === "ENOENT") throw new Error("Windows installer builds require Go 1.22+ on the maintainer machine. Set VERITY_GO to its executable. End users do not need it.");
  if (result.status !== 0) throw new Error(result.stderr || result.error?.message || "Windows installer compilation failed");
  return result.stdout.trim();
}
const goRoot = run(["env", "GOROOT"], root);
const manifest = JSON.parse(await readFile(path.join(root, "extension/manifest.json"), "utf8"));
const hash = createHash("sha256").update(Buffer.from(manifest.key, "base64")).digest().subarray(0, 16);
const id = [...hash].map(b => String.fromCharCode(97 + (b >> 4), 97 + (b & 15))).join("");
const pins = JSON.parse(await readFile(path.join(source, "runtime-pins.json"), "utf8"));
const pin = pins.windows?.x86_64;
if (!/^https:\/\/github\.com\/astral-sh\/python-build-standalone\/releases\/download\/[0-9]+\/cpython-[0-9.]+(?:%2B|\+)[0-9]+-x86_64-pc-windows-msvc-install_only\.tar\.gz$/.test(pin?.url || "") || !/^[a-f0-9]{64}$/.test(pin?.sha256 || "")) throw new Error("Invalid Windows runtime pin");
const engineFiles = ["__init__.py", "ai.py", "assets.py", "calibration.py", "detection.py", "local_os.py", "model_setup.py", "native_host.py", "pdf.py", "resources.py", "server.py", "similarity.py", "text.py", "web.py"];
const extensionFiles = ["background.js", "calibration.json", "capture.js", "connection.js", "content.js", "icon.svg", "manifest.json", "panel.css", "panel.html", "panel.js", "reader.js"];
// One RT_MANIFEST resource in an AMD64 COFF object. This avoids a Windows SDK
// build dependency and prevents legacy "Setup.exe" administrator-elevation heuristics.
function manifestObject(xml) {
  const size = (88 + xml.length + 3) & ~3;
  const object = Buffer.alloc(60 + size + 10 + 18 + 4);
  object.writeUInt16LE(0x8664, 0);
  object.writeUInt16LE(1, 2);
  object.writeUInt32LE(60 + size + 10, 8);
  object.writeUInt32LE(1, 12);
  object.write(".rsrc", 20);
  object.writeUInt32LE(size, 36);
  object.writeUInt32LE(60, 40);
  object.writeUInt32LE(60 + size, 44);
  object.writeUInt16LE(1, 52);
  object.writeUInt32LE(0x40000040, 56);
  const resource = object.subarray(60, 60 + size);
  for (const offset of [0, 24, 48]) resource.writeUInt16LE(1, offset + 14);
  resource.writeUInt32LE(24, 16); // RT_MANIFEST
  resource.writeUInt32LE(0x80000018, 20);
  resource.writeUInt32LE(1, 40);
  resource.writeUInt32LE(0x80000030, 44);
  resource.writeUInt32LE(0x0409, 64);
  resource.writeUInt32LE(72, 68);
  resource.writeUInt32LE(88, 72); // Section-relative until the linker applies the relocation.
  resource.writeUInt32LE(xml.length, 76);
  resource.writeUInt32LE(65001, 80);
  xml.copy(resource, 88);
  object.writeUInt32LE(72, 60 + size);
  object.writeUInt16LE(3, 60 + size + 8); // IMAGE_REL_AMD64_ADDR32NB
  object.write(".rsrc", 60 + size + 10);
  object.writeInt16LE(1, 60 + size + 10 + 12);
  object.writeUInt8(3, 60 + size + 10 + 16); // Static section symbol.
  object.writeUInt32LE(4, object.length - 4);
  return object;
}
const stage = await mkdtemp(path.join(root, ".windows-build-"));
try {
  const payload = path.join(stage, "payload");
  const records = {};
  async function add(name, sourcePath, content) {
    const data = sourcePath ? await readFile(sourcePath) : Buffer.from(content);
    const target = path.join(payload, name);
    await mkdir(path.dirname(target), { recursive: true });
    await writeFile(target, data);
    records[name] = createHash("sha256").update(data).digest("hex");
  }
  for (const name of engineFiles) await add("product/engine/" + name, path.join(root, "engine", name));
  for (const browser of ["chrome", "firefox"]) for (const name of extensionFiles) await add(browser + "-extension/" + name, path.join(root, "dist", browser, name));
  await add("product/extension/calibration.json", path.join(root, "extension/calibration.json"));
  for (const name of ["native_entry.py", "model_entry.py", "provision_windows.py", "provision_windows_entry.py", "runtime-pins.json"]) await add(name, path.join(source, name));
  for (const name of ["model-pins.json", "model-requirements.txt", "THIRD-PARTY-NOTICES.txt"]) await add(name, path.join(root, name));
  await add("runtime-requirements.txt", path.join(root, "runtime-requirements.txt"));
  await add("release.json", null, JSON.stringify({ engine_version: manifest.version, chrome_origin: "chrome-extension://" + id, firefox_id: "verity@local.invalid" }, null, 2) + "\n");
  const license = await readFile(path.join(goRoot, "LICENSE"), "utf8");
  await add("licenses/go-LICENSE.txt", null, license);
  await writeFile(path.join(payload, "payload-manifest.json"), JSON.stringify(records, null, 2) + "\n");
  const pack = path.join(source, "windows/pack-payload.go");
  run(["run", pack, "--source", payload, "--output", path.join(stage, "payload.zip")], stage);
  for (const name of ["go.mod", "install.go", "main_windows.go", "platform_windows.go"]) await copyFile(path.join(source, "windows", name), path.join(stage, name));
  await writeFile(path.join(stage, "manifest.syso"), manifestObject(await readFile(path.join(source, "windows/app.manifest"))));
  const executable = path.join(stage, "VeritySetup.exe");
  run(["build", "-trimpath", "-ldflags=-H=windowsgui -s -w -buildid=", "-o", executable, "."], stage, { ...nativeEnv, GOOS: "windows", GOARCH: "amd64" });
  const info = "Open VeritySetup.exe if permitted by Windows, approve Install, then load the chrome-extension folder shown in Explorer. Windows 10/11 x64 is required. Setup downloads the runtime, browser and about 1.9 GB of reviewed models; Binoculars adds about 29 GB only on 64 GB+ machines. AI percentages require independent calibration; code assets need a permitted checkpoint/corpus. Pairing and startup are automatic. This is an unsigned development build; Windows execution/browser acceptance and signing are outstanding. Do not disable Windows security.\n";
  const notices = await readFile(path.join(root, "THIRD-PARTY-NOTICES.txt"), "utf8") + "\nThe installer/native launcher includes the Go standard library under the following license.\n\n" + license;
  await mkdir(output, { recursive: true });
  await copyFile(executable, path.join(output, "VeritySetup.exe"));
  await writeFile(path.join(output, "VeritySetup.exe.sha256"), createHash("sha256").update(await readFile(executable)).digest("hex") + "  VeritySetup.exe\n");
  await writeFile(path.join(output, "DOWNLOAD-INFO.txt"), info);
  await writeFile(path.join(output, "THIRD-PARTY-NOTICES.txt"), notices);
  const bundle = path.join(stage, "bundle");
  await mkdir(bundle);
  for (const name of outputs.filter(name => !name.endsWith(".zip"))) await copyFile(path.join(output, name), path.join(bundle, name));
  run(["run", pack, "--source", bundle, "--output", path.join(output, "Verity-Windows.zip")], stage);
  console.log(`Windows x64 installer: ${path.join(output, "VeritySetup.exe")}`);
  console.log(`Windows download archive: ${path.join(output, "Verity-Windows.zip")}`);
} finally {
  // This unique build-only staging directory was created by this invocation.
  await rm(stage, { recursive: true, force: true });
}
