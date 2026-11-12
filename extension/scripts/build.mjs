import { mkdir, cp } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
const root = fileURLToPath(new URL('../', import.meta.url));
await mkdir(`${root}vendor`, { recursive: true });
for (const name of ['pdf.mjs', 'pdf.worker.mjs']) {
  await cp(`${root}node_modules/pdfjs-dist/build/${name}`, `${root}vendor/${name}`);
}
for (const name of ['cmaps', 'standard_fonts', 'wasm']) {
  await cp(`${root}node_modules/pdfjs-dist/${name}`, `${root}vendor/${name}`, { recursive: true });
}
await cp(`${root}node_modules/pdfjs-dist/LICENSE`, `${root}vendor/PDFJS-LICENSE`);
console.log('Bundled PDF.js and local fonts/CMaps/WASM. No CDN required.');
