import { build } from "esbuild";
import { copyFile, mkdir } from "node:fs/promises";

await mkdir("dist", { recursive: true });
await build({
  entryPoints: { background: "src/background/index.js", content: "src/content/index.js", panel: "src/ui/panel.js" },
  bundle: true, outdir: "dist", format: "iife", target: "chrome116", sourcemap: false,
});
for (const [source, destination] of [["manifest.json", "manifest.json"], ["src/ui/panel.html", "panel.html"], ["src/ui/panel.css", "panel.css"]]) {
  await copyFile(source, `dist/${destination}`);
}
console.log("Built dist/. Load this directory as an unpacked Chrome extension.");
