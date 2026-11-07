import test from "node:test";
import assert from "node:assert/strict";
import { copyFile, mkdir, mkdtemp, readFile, readdir, rm, symlink, writeFile } from "node:fs/promises";
import { spawnSync } from "node:child_process";
import path from "node:path";

test("installer build rejects unexpected payloads and symlinks without deleting them", async () => {
  const fixture = await mkdtemp(path.resolve("product/installer-build-test-"));
  try {
    await mkdir(path.join(fixture, "extension"));
    await mkdir(path.join(fixture, "installer"));
    for (const name of ["build.mjs", "build-installer.mjs"]) await copyFile(path.resolve("product", name), path.join(fixture, name));
    for (const name of await readdir("product/extension")) await copyFile(path.resolve("product/extension", name), path.join(fixture, "extension", name));
    await copyFile(path.resolve("product/installer/runtime-pins.json"), path.join(fixture, "installer/runtime-pins.json"));
    const app = path.join(fixture, "dist/installer/macos/Verity Installer.app");
    const resources = path.join(app, "Contents/Resources");
    await mkdir(resources, { recursive: true });
    const marker = path.join(resources, "private-user-file.txt");
    await writeFile(marker, "preserve this file");
    const build = () => spawnSync(process.execPath, [path.join(fixture, "build-installer.mjs")], { cwd: fixture, encoding: "utf8" });
    let result = build();
    assert.notEqual(result.status, 0);
    assert.match(result.stderr, /Unexpected installer file/);
    assert.equal(await readFile(marker, "utf8"), "preserve this file");
    await rm(marker);

    const target = path.join(fixture, "outside.txt");
    await writeFile(target, "do not overwrite");
    await symlink(target, path.join(resources, "install-macos.sh"));
    result = build();
    assert.notEqual(result.status, 0);
    assert.match(result.stderr, /Unexpected installer file/);
    assert.equal(await readFile(target, "utf8"), "do not overwrite");

    await rm(app, { recursive: true });
    await symlink(path.dirname(target), app, "dir");
    result = build();
    assert.notEqual(result.status, 0);
    assert.match(result.stderr, /Unexpected installer symlink/);
    assert.equal(await readFile(target, "utf8"), "do not overwrite");
  } finally {
    await rm(fixture, { recursive: true, force: true });
  }
});

test("Windows build guards refuse unrelated files and symlinked outputs", async () => {
  const fixture = await mkdtemp(path.resolve("product/windows-build-test-"));
  try {
    await mkdir(path.join(fixture, "extension"));
    for (const name of ["build.mjs", "build-installer-windows.mjs"]) await copyFile(path.resolve("product", name), path.join(fixture, name));
    for (const name of await readdir("product/extension")) await copyFile(path.resolve("product/extension", name), path.join(fixture, "extension", name));
    const output = path.join(fixture, "dist/installer/windows");
    await mkdir(output, { recursive: true });
    const marker = path.join(output, "user-work.txt");
    await writeFile(marker, "preserve me");
    const build = () => spawnSync(process.execPath, [path.join(fixture, "build-installer-windows.mjs")], { cwd: fixture, encoding: "utf8" });
    let result = build();
    assert.notEqual(result.status, 0);
    assert.match(result.stderr, /Unexpected Windows installer file/);
    assert.equal(await readFile(marker, "utf8"), "preserve me");
    await rm(marker);
    const target = path.join(fixture, "outside.exe");
    await writeFile(target, "do not overwrite");
    await symlink(target, path.join(output, "VeritySetup.exe"));
    result = build();
    assert.notEqual(result.status, 0);
    assert.match(result.stderr, /Unexpected Windows installer file/);
    assert.equal(await readFile(target, "utf8"), "do not overwrite");
  } finally {
    await rm(fixture, { recursive: true, force: true });
  }
});
