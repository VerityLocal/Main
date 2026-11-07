import test from "node:test";
import assert from "node:assert/strict";
import { inflateRawSync } from "node:zlib";
import { crc32, createZip } from "../zip.mjs";

test("extension ZIP has deterministic checked data and a central directory", () => {
  const data = Buffer.from("Verity fixture 🦊");
  assert.equal(crc32(Buffer.from("123456789")), 0xcbf43926);
  const entries = [{ name: "Verity Extension/fixture.txt", data }];
  const archive = createZip(entries);
  assert.deepEqual(archive, createZip(entries));
  assert.equal(archive.readUInt32LE(0), 0x04034b50);
  const length = archive.readUInt16LE(26), size = archive.readUInt32LE(18);
  assert.equal(archive.subarray(30, 30 + length).toString(), entries[0].name);
  assert.deepEqual(inflateRawSync(archive.subarray(30 + length, 30 + length + size)), data);
  assert.equal(archive.readUInt32LE(14), crc32(data));
  const end = archive.length - 22, directory = archive.readUInt32LE(end + 16);
  assert.equal(archive.readUInt32LE(end), 0x06054b50);
  assert.equal(archive.readUInt32LE(directory), 0x02014b50);
  assert.equal(archive.readUInt16LE(end + 10), 1);
});

test("extension ZIP refuses traversal, aliases, duplicate paths and oversize inputs", () => {
  for (const name of ["../secret", "/absolute", "C:/file", "a\\file", "a/../file", "a//file", "a/file.", "a/file ", "a/file:stream"]) {
    assert.throws(() => createZip([{ name, data: Buffer.from("x") }]), /Unsafe ZIP path/);
  }
  assert.throws(() => createZip([{ name: "file", data: [] }, { name: "FILE", data: [] }]), /Duplicate/);
  assert.throws(() => createZip([{ name: "file", data: Buffer.alloc(32 * 1024 * 1024 + 1) }]), /exceeds/);
  assert.throws(() => createZip([]), /entry count/);
});
