// Small deterministic ZIP writer for the first-party extension; no build dependencies.
import { deflateRawSync } from "node:zlib";

export function crc32(data) {
  let value = 0xffffffff;
  for (const byte of data) {
    value ^= byte;
    for (let bit = 0; bit < 8; bit++) value = (value >>> 1) ^ ((value & 1) ? 0xedb88320 : 0);
  }
  return (value ^ 0xffffffff) >>> 0;
}

export function createZip(entries) {
  if (!entries.length || entries.length > 128) throw new Error("Invalid ZIP entry count");
  const local = [], central = [], seen = new Set();
  let offset = 0, total = 0;
  for (const { name, data } of entries) {
    if (typeof name !== "string" || !name || name.startsWith("/") || /[\\:\0]/.test(name) || name.split("/").some(part => !part || part === "." || part === ".." || /[. ]$/.test(part))) throw new Error("Unsafe ZIP path");
    const identity = name.toLowerCase();
    if (seen.has(identity)) throw new Error("Duplicate ZIP path");
    seen.add(identity);
    const filename = Buffer.from(name, "utf8"), bytes = Buffer.from(data);
    total += bytes.length;
    if (filename.length > 1024 || total > 32 * 1024 * 1024) throw new Error("ZIP exceeds limits");
    const compressed = deflateRawSync(bytes), checksum = crc32(bytes);
    const header = Buffer.alloc(30);
    header.writeUInt32LE(0x04034b50, 0);
    header.writeUInt16LE(20, 4);
    header.writeUInt16LE(0x0800, 6);
    header.writeUInt16LE(8, 8);
    header.writeUInt16LE(0x0021, 12); // 1980-01-01, fixed for reproducible builds.
    header.writeUInt32LE(checksum, 14);
    header.writeUInt32LE(compressed.length, 18);
    header.writeUInt32LE(bytes.length, 22);
    header.writeUInt16LE(filename.length, 26);
    local.push(header, filename, compressed);
    const directory = Buffer.alloc(46);
    directory.writeUInt32LE(0x02014b50, 0);
    directory.writeUInt16LE(0x0314, 4);
    directory.writeUInt16LE(20, 6);
    directory.writeUInt16LE(0x0800, 8);
    directory.writeUInt16LE(8, 10);
    directory.writeUInt16LE(0x0021, 14);
    directory.writeUInt32LE(checksum, 16);
    directory.writeUInt32LE(compressed.length, 20);
    directory.writeUInt32LE(bytes.length, 24);
    directory.writeUInt16LE(filename.length, 28);
    directory.writeUInt32LE((0o100644 << 16) >>> 0, 38);
    directory.writeUInt32LE(offset, 42);
    central.push(directory, filename);
    offset += header.length + filename.length + compressed.length;
  }
  const directory = Buffer.concat(central), end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50, 0);
  end.writeUInt16LE(entries.length, 8);
  end.writeUInt16LE(entries.length, 10);
  end.writeUInt32LE(directory.length, 12);
  end.writeUInt32LE(offset, 16);
  return Buffer.concat([...local, directory, end]);
}
