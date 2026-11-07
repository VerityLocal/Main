"""Static Windows artifact validation on any OS; never claims Windows execution."""
import base64
import hashlib
import io
import json
import struct
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).parents[2]
OUTPUT = ROOT / "product/dist/installer/windows"


def check_manifest(data):
    assert data[:2] == b"MZ"
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    assert data[pe:pe + 4] == b"PE\0\0"
    machine, sections = struct.unpack_from("<HH", data, pe + 4)
    assert machine == 0x8664, "Installer is not AMD64"
    optional = pe + 24
    assert struct.unpack_from("<H", data, optional)[0] == 0x20B
    assert struct.unpack_from("<H", data, optional + 68)[0] == 2, "Console subsystem instead of GUI"
    optional_size = struct.unpack_from("<H", data, pe + 20)[0]
    section_table = optional + optional_size

    def offset(rva):
        for index in range(sections):
            size, start, raw_size, raw = struct.unpack_from("<IIII", data, section_table + 40 * index + 8)
            if start <= rva < start + max(size, raw_size):
                return raw + rva - start
        raise AssertionError("Resource RVA is outside PE sections")

    resource_rva, resource_size = struct.unpack_from("<II", data, optional + 128)
    assert resource_rva and resource_size, "Missing application manifest resource"
    resource = offset(resource_rva)

    def entry(directory, identity=None):
        names, ids = struct.unpack_from("<HH", data, directory + 12)
        assert 0 < names + ids < 128
        for index in range(names + ids):
            name, pointer = struct.unpack_from("<II", data, directory + 16 + 8 * index)
            if identity is None or name == identity:
                return pointer
        raise AssertionError("Manifest resource entry is missing")

    pointer = entry(resource, 24)  # RT_MANIFEST
    assert pointer & 0x80000000
    pointer = entry(resource + (pointer & 0x7FFFFFFF), 1)
    assert pointer & 0x80000000
    pointer = entry(resource + (pointer & 0x7FFFFFFF))
    assert not pointer & 0x80000000
    manifest_rva, length = struct.unpack_from("<II", data, resource + pointer)
    assert 0 < length < 65536
    start = offset(manifest_rva)
    xml = ElementTree.fromstring(data[start:start + length])
    level = xml.find(".//{urn:schemas-microsoft-com:asm.v3}requestedExecutionLevel")
    assert level is not None and level.attrib == {"level": "asInvoker", "uiAccess": "false"}
    _, certificate_size = struct.unpack_from("<II", data, optional + 144)
    return certificate_size > 0


def embedded_payload(data):
    # //go:embed retains the complete ZIP as a contiguous read-only byte slice.
    position = 0
    while True:
        position = data.find(b"PK\x05\x06", position)
        if position < 0:
            raise AssertionError("Embedded installer payload was not found")
        try:
            disk, directory_disk, disk_count, count, size, directory_offset, comment = struct.unpack_from("<HHHHIIH", data, position + 4)
            start = position - size - directory_offset
            if disk == directory_disk == 0 and disk_count == count and 0 < count < 128 and start >= 0:
                archive = zipfile.ZipFile(io.BytesIO(data[start:position + 22 + comment]))
                if "payload-manifest.json" in archive.namelist():
                    return archive
        except (struct.error, zipfile.BadZipFile):
            pass
        position += 4


def main():
    executable = (OUTPUT / "VeritySetup.exe").read_bytes()
    assert len(executable) < 128 * 1024 * 1024
    signed = check_manifest(executable)
    digest = hashlib.sha256(executable).hexdigest()
    assert (OUTPUT / "VeritySetup.exe.sha256").read_text().split()[0] == digest
    with zipfile.ZipFile(OUTPUT / "Verity-Windows.zip") as bundle:
        assert set(bundle.namelist()) == {"VeritySetup.exe", "VeritySetup.exe.sha256", "DOWNLOAD-INFO.txt", "THIRD-PARTY-NOTICES.txt"}
        for name in bundle.namelist():
            assert bundle.read(name) == (OUTPUT / name).read_bytes()
    with embedded_payload(executable) as payload:
        manifest = json.loads(payload.read("payload-manifest.json"))
        assert len(payload.namelist()) == len(set(payload.namelist())) == len(manifest) + 1
        assert set(payload.namelist()) == set(manifest) | {"payload-manifest.json"}
        for name, expected in manifest.items():
            content = payload.read(name)
            assert hashlib.sha256(content).hexdigest() == expected
            if name.startswith("product/engine/") or name == "product/extension/calibration.json":
                source = ROOT / name
            elif name.startswith(("chrome-extension/", "firefox-extension/")):
                browser, file = name.split("/", 1)
                source = ROOT / "product/dist" / browser.removesuffix("-extension") / file
            elif name == "runtime-requirements.txt":
                source = ROOT / "internal/runtime-requirements.txt"
            elif name in {"native_entry.py", "provision_windows.py", "provision_windows_entry.py", "runtime-pins.json"}:
                source = ROOT / "product/installer" / name
            elif name == "licenses/go-LICENSE.txt":
                assert content.decode() in (OUTPUT / "THIRD-PARTY-NOTICES.txt").read_text()
                continue
            elif name == "release.json":
                release = json.loads(content)
                extension = json.loads((ROOT / "product/extension/manifest.json").read_text())
                identity = hashlib.sha256(base64.b64decode(extension["key"])).digest()[:16]
                identity = "".join(chr(97 + nibble) for byte in identity for nibble in [byte >> 4, byte & 15])
                assert release == {"engine_version": extension["version"], "chrome_origin": "chrome-extension://" + identity, "firefox_id": "verity@local.invalid"}
                continue
            else:
                raise AssertionError("Unexpected embedded file: " + name)
            assert content == source.read_bytes(), "Stale packaged file: " + name
    result = {"artifact": "product/dist/installer/windows/VeritySetup.exe", "architecture": "AMD64 PE32+", "subsystem": "Windows GUI", "requested_privilege": "asInvoker; no administrator request", "payload": "passed; exact first-party source hashes and retained compiler license", "download_archive": "passed; exact executable, checksum, instructions and notices", "sha256": digest, "authenticode_certificate_present": signed, "validation_host": sys.platform, "windows_installation_execution": "not tested; Windows acceptance machine required", "windows_native_browser_integration": "not tested; registry unit tests use an explicit fake", "ai": "unavailable; no models or approved calibration added"}
    (ROOT / "internal/demo/screenshots/windows-package-validation.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
