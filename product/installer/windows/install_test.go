package main

import (
	"archive/tar"
	"archive/zip"
	"bytes"
	"compress/gzip"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func fixtureZIP(t *testing.T, files map[string][]byte, manifest map[string]string) []byte {
	t.Helper()
	var output bytes.Buffer
	writer := zip.NewWriter(&output)
	if manifest != nil {
		stream, _ := writer.Create("payload-manifest.json")
		json.NewEncoder(stream).Encode(manifest)
	}
	for name, data := range files { stream, err := writer.Create(name); if err != nil { t.Fatal(err) }; stream.Write(data) }
	if err := writer.Close(); err != nil { t.Fatal(err) }
	return output.Bytes()
}

func TestPayloadIntegrityAndAllowlist(t *testing.T) {
	data := []byte("first-party fixture")
	hash := sha256.Sum256(data)
	manifest := map[string]string{"engine/fixture.py": hex.EncodeToString(hash[:])}
	if err := extractPayload(fixtureZIP(t, map[string][]byte{"engine/fixture.py": data}, manifest), t.TempDir()); err != nil { t.Fatal(err) }
	for label, files := range map[string]map[string][]byte{
		"modified": {"engine/fixture.py": []byte("changed")},
		"missing": {},
		"unlisted": {"engine/fixture.py": data, "private-user-file.txt": data},
	} {
		t.Run(label, func(t *testing.T) { if err := extractPayload(fixtureZIP(t, files, manifest), t.TempDir()); err == nil { t.Fatal("unsafe payload accepted") } })
	}
	if err := extractPayload(fixtureZIP(t, map[string][]byte{"engine/fixture.py": data}, nil), t.TempDir()); err == nil { t.Fatal("missing manifest accepted") }
}

func TestWindowsArchiveAliasesAreRejected(t *testing.T) {
	for _, name := range []string{"../outside", "/absolute", "C:/file", `python\file`, "python/../outside", "python/NUL.txt", "python/com1", "python/file.", "python/file ", "python/file:stream", "./python/file", "python//file"} {
		t.Run(name, func(t *testing.T) { if _, err := archivePath(t.TempDir(), name); err == nil { t.Fatal("unsafe path accepted") } })
	}
	if _, err := archivePath(t.TempDir(), "python/Lib/fixture.py"); err != nil { t.Fatal(err) }
}

func TestRuntimeRejectsTraversalLinksAndUnexpectedRoots(t *testing.T) {
	for _, header := range []*tar.Header{
		{Name: "python/../outside", Typeflag: tar.TypeReg},
		{Name: "python/link", Typeflag: tar.TypeSymlink, Linkname: "../outside"},
		{Name: "python/link", Typeflag: tar.TypeLink, Linkname: "python/file"},
		{Name: "unrelated/file", Typeflag: tar.TypeReg},
	} {
		t.Run(header.Name+string(header.Typeflag), func(t *testing.T) {
			var output bytes.Buffer
			compressed := gzip.NewWriter(&output)
			writer := tar.NewWriter(compressed)
			if err := writer.WriteHeader(header); err != nil { t.Fatal(err) }
			writer.Close(); compressed.Close()
			root := t.TempDir()
			filename := filepath.Join(root, "runtime.tar.gz")
			os.WriteFile(filename, output.Bytes(), 0600)
			if err := extractRuntime(filename, root); err == nil { t.Fatal("unsafe runtime accepted") }
		})
	}
}

func TestRuntimePinValidationAndCancellation(t *testing.T) {
	for _, pin := range []runtimePin{
		{URL: "http://github.com/astral-sh/python-build-standalone/releases/download/fixture", SHA256: "invalid"},
		{URL: "https://evil.invalid/python.tar.gz", SHA256: "invalid"},
		{URL: "https://github.com/astral-sh/python-build-standalone/releases/download/fixture", SHA256: "invalid"},
	} {
		if err := downloadRuntime(context.Background(), pin, filepath.Join(t.TempDir(), "runtime")); err == nil { t.Fatal("unsafe pin accepted") }
	}
	ctx, cancel := context.WithCancel(context.Background()); cancel()
	pin := runtimePin{URL: "https://github.com/astral-sh/python-build-standalone/releases/download/fixture", SHA256: "75cb501dc11c7b55c6b447c58e4910bce5b1f609f1017328b4f3a858dfaf5428"}
	if err := downloadRuntime(ctx, pin, filepath.Join(t.TempDir(), "runtime")); err == nil { t.Fatal("cancelled download accepted") }
}

func TestPinnedWindowsArchiveExtraction(t *testing.T) {
	archive := os.Getenv("VERITY_WINDOWS_RUNTIME_ARCHIVE")
	if archive == "" { t.Skip("real pinned runtime archive not supplied") }
	data, err := os.ReadFile(archive)
	if err != nil { t.Fatal(err) }
	hash := sha256.Sum256(data)
	if hex.EncodeToString(hash[:]) != "75cb501dc11c7b55c6b447c58e4910bce5b1f609f1017328b4f3a858dfaf5428" { t.Fatal("pinned runtime digest mismatch") }
	root := t.TempDir()
	if err := extractRuntime(archive, root); err != nil { t.Fatal(err) }
	if _, err := os.Stat(filepath.Join(root, "python", "python.exe")); err != nil { t.Fatal(err) }
}

func stagedInstallFixture(t *testing.T) installOptions {
	t.Helper()
	base := t.TempDir()
	executable := filepath.Join(base, "setup.exe")
	os.WriteFile(executable, []byte("fixture executable, never run"), 0600)
	files := map[string][]byte{"runtime-pins.json": []byte(`{"windows":{"x86_64":{"url":"https://github.com/astral-sh/python-build-standalone/releases/download/fixture","sha256":"fixture"}}}`)}
	manifest := map[string]string{}
	for name, data := range files { hash := sha256.Sum256(data); manifest[name] = hex.EncodeToString(hash[:]) }
	return installOptions{
		Root: filepath.Join(base, "Verity"), Executable: executable, Payload: fixtureZIP(t, files, manifest),
		Progress: func(string) {}, PrivateDirectory: func(string) error { return nil },
		Download: func(ctx context.Context, pin runtimePin, destination string) error {
			var output bytes.Buffer
			compressed := gzip.NewWriter(&output)
			writer := tar.NewWriter(compressed)
			data := []byte("fixture Python, never run")
			writer.WriteHeader(&tar.Header{Name: "python/python.exe", Typeflag: tar.TypeReg, Size: int64(len(data))})
			writer.Write(data); writer.Close(); compressed.Close()
			return os.WriteFile(destination, output.Bytes(), 0600)
		},
	}
}

func TestInstallPromotesRuntimeAndUsesOnlyFixedProvisioningCommands(t *testing.T) {
	options := stagedInstallFixture(t)
	var commands [][]string
	options.Run = func(ctx context.Context, python string, args, env []string, output io.Writer) error {
		if !strings.HasSuffix(python, filepath.Join("python", "python.exe")) { t.Fatal("unexpected executable") }
		if args[0] != "-I" { t.Fatal("runtime is not isolated") }
		commands = append(commands, args)
		return nil
	}
	folder, err := install(context.Background(), options)
	if err != nil { t.Fatal(err) }
	if len(commands) != 6 { t.Fatalf("unexpected command count: %d", len(commands)) }
	if strings.Join(commands[0][:6], " ") != "-I -m pip --isolated install --only-binary=:all:" { t.Fatal("unexpected dependency installation") }
	if strings.Join(commands[1], " ") != "-I -m playwright install chromium --only-shell" { t.Fatal("unexpected browser installation") }
	if !strings.HasSuffix(commands[3][len(commands[3])-1], "model-requirements.txt") { t.Fatal("missing model dependencies") }
	if !strings.HasSuffix(commands[4][1], "model_entry.py") || commands[4][2] != "--root" || commands[4][3] != options.Root || commands[4][4] != "--pins" { t.Fatal("unexpected model setup command") }
	if !strings.HasSuffix(commands[5][1], "provision_windows_entry.py") || commands[5][4] != "--install-root" { t.Fatal("unexpected provisioning command") }
	root := filepath.Dir(folder)
	if filepath.Dir(root) != filepath.Join(options.Root, "versions") { t.Fatal("runtime was not promoted") }
	if _, err := os.Stat(filepath.Join(root, "native-host.exe")); err != nil { t.Fatal(err) }
}

func TestFailedInstallKeepsUserSettingsAndOnlyCleansItsStage(t *testing.T) {
	for _, failCommand := range []int{1, 4, 5, 6} {
		t.Run(string(rune('0'+failCommand)), func(t *testing.T) {
			options := stagedInstallFixture(t)
			os.MkdirAll(options.Root, 0700)
			settings := filepath.Join(options.Root, "helper.json")
			os.WriteFile(settings, []byte("preserved private fixture"), 0600)
			calls := 0
			options.Run = func(context.Context, string, []string, []string, io.Writer) error {
				calls++
				if calls == failCommand { return errors.New("controlled failure") }
				return nil
			}
			if _, err := install(context.Background(), options); err == nil { t.Fatal("failure was hidden") }
			data, _ := os.ReadFile(settings)
			if string(data) != "preserved private fixture" { t.Fatal("settings changed") }
			entries, _ := os.ReadDir(options.Root)
			for _, entry := range entries { if strings.HasPrefix(entry.Name(), ".install-") { t.Fatal("staging directory leaked") } }
			versions, _ := os.ReadDir(filepath.Join(options.Root, "versions"))
			if failCommand == 6 && len(versions) != 1 { t.Fatal("promoted release was improperly discarded") }
			if failCommand < 6 && len(versions) != 0 { t.Fatal("failed stage was promoted") }
		})
	}
}
