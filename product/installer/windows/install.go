package main

import (
	"archive/tar"
	"archive/zip"
	"bytes"
	"compress/gzip"
	"context"
	"crypto/sha256"
	"crypto/tls"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"path"
	"path/filepath"
	"strings"
	"time"
)

const maxDownload = 128 << 20
const maxExpanded = 1 << 30

type runtimePin struct {
	URL    string `json:"url"`
	SHA256 string `json:"sha256"`
}

type installOptions struct {
	Root, Executable string
	Payload          []byte
	Progress         func(string)
	PrivateDirectory func(string) error
	Run              func(context.Context, string, []string, []string, io.Writer) error
	Download         func(context.Context, runtimePin, string) error
}

// Reject Windows path aliases as well as ordinary archive traversal.
func archivePath(root, name string) (string, error) {
	name = strings.TrimSuffix(name, "/")
	if name == "" || strings.ContainsAny(name, "\\:") || path.IsAbs(name) || path.Clean(name) != name {
		return "", errors.New("unsafe archive path")
	}
	for _, part := range strings.Split(name, "/") {
		if part == ".." || part == "." || strings.TrimRight(part, ". ") != part {
			return "", errors.New("unsafe archive component")
		}
		base := strings.ToUpper(strings.SplitN(part, ".", 2)[0])
		if base == "CON" || base == "PRN" || base == "AUX" || base == "NUL" || (len(base) == 4 && (strings.HasPrefix(base, "COM") || strings.HasPrefix(base, "LPT")) && base[3] >= '0' && base[3] <= '9') {
			return "", errors.New("reserved archive component")
		}
	}
	return filepath.Join(root, filepath.FromSlash(name)), nil
}

func extractPayload(data []byte, root string) error {
	reader, err := zip.NewReader(bytes.NewReader(data), int64(len(data)))
	if err != nil { return err }
	var manifest map[string]string
	for _, file := range reader.File {
		if file.Name != "payload-manifest.json" { continue }
		if manifest != nil || file.UncompressedSize64 > 65536 { return errors.New("invalid payload manifest") }
		stream, err := file.Open()
		if err != nil { return err }
		err = json.NewDecoder(io.LimitReader(stream, 65537)).Decode(&manifest)
		stream.Close()
		if err != nil { return err }
	}
	if len(manifest) == 0 || len(manifest) > 128 { return errors.New("missing payload manifest") }
	seen := map[string]bool{}
	var total uint64
	for _, file := range reader.File {
		if file.Name == "payload-manifest.json" { continue }
		destination, err := archivePath(root, file.Name)
		if err != nil { return err }
		want, approved := manifest[file.Name]
		if !approved || seen[file.Name] || !file.Mode().IsRegular() || len(want) != 64 { return errors.New("unapproved payload file") }
		total += file.UncompressedSize64
		if total > 32<<20 { return errors.New("payload exceeds limit") }
		if err := os.MkdirAll(filepath.Dir(destination), 0700); err != nil { return err }
		input, err := file.Open()
		if err != nil { return err }
		output, err := os.OpenFile(destination, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
		if err != nil { input.Close(); return err }
		hash := sha256.New()
		_, err = io.Copy(io.MultiWriter(output, hash), io.LimitReader(input, 32<<20+1))
		closeErr := output.Close()
		input.Close()
		if err != nil { return err }
		if closeErr != nil { return closeErr }
		if hex.EncodeToString(hash.Sum(nil)) != want { return errors.New("payload integrity mismatch") }
		seen[file.Name] = true
	}
	if len(seen) != len(manifest) { return errors.New("incomplete payload") }
	return nil
}

func downloadRuntime(ctx context.Context, pin runtimePin, destination string) error {
	parsed, err := url.Parse(pin.URL)
	if err != nil || parsed.Scheme != "https" || parsed.Host != "github.com" || !strings.HasPrefix(parsed.Path, "/astral-sh/python-build-standalone/releases/download/") || strings.ContainsAny(pin.URL, "\r\n") {
		return errors.New("unapproved runtime URL")
	}
	if digest, err := hex.DecodeString(pin.SHA256); err != nil || len(digest) != sha256.Size { return errors.New("invalid runtime digest") }
	client := &http.Client{Timeout: 5*time.Minute, Transport: &http.Transport{TLSClientConfig: &tls.Config{MinVersion: tls.VersionTLS12}}, CheckRedirect: func(request *http.Request, via []*http.Request) error {
		if request.URL.Scheme != "https" || len(via) >= 8 { return errors.New("unsafe download redirect") }
		return nil
	}}
	defer client.CloseIdleConnections()
	request, err := http.NewRequestWithContext(ctx, "GET", pin.URL, nil)
	if err != nil { return err }
	response, err := client.Do(request)
	if err != nil { return err }
	defer response.Body.Close()
	if response.StatusCode != 200 || response.ContentLength > maxDownload { return errors.New("runtime download failed") }
	file, err := os.OpenFile(destination, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
	if err != nil { return err }
	defer file.Close()
	hash := sha256.New()
	size, err := io.Copy(io.MultiWriter(file, hash), io.LimitReader(response.Body, maxDownload+1))
	if err != nil { return err }
	if size > maxDownload || hex.EncodeToString(hash.Sum(nil)) != pin.SHA256 { return errors.New("runtime integrity mismatch") }
	return nil
}

func extractRuntime(filename, root string) error {
	file, err := os.Open(filename)
	if err != nil { return err }
	defer file.Close()
	compressed, err := gzip.NewReader(file)
	if err != nil { return err }
	defer compressed.Close()
	reader := tar.NewReader(compressed)
	var total int64
	count := 0
	for {
		header, err := reader.Next()
		if err == io.EOF { break }
		if err != nil { return err }
		count++
		if count > 40000 || header.Size < 0 { return errors.New("runtime archive exceeds limits") }
		destination, err := archivePath(root, header.Name)
		if err != nil { return err }
		if header.Name != "python" && header.Name != "python/" && !strings.HasPrefix(header.Name, "python/") { return errors.New("unexpected runtime root") }
		switch header.Typeflag {
		case tar.TypeDir:
			if err := os.MkdirAll(destination, 0700); err != nil { return err }
		case tar.TypeReg, tar.TypeRegA:
			total += header.Size
			if total > maxExpanded { return errors.New("expanded runtime exceeds limit") }
			if err := os.MkdirAll(filepath.Dir(destination), 0700); err != nil { return err }
			output, err := os.OpenFile(destination, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
			if err != nil { return err }
			_, err = io.Copy(output, reader)
			closeErr := output.Close()
			if err != nil { return err }
			if closeErr != nil { return closeErr }
		default:
			return errors.New("runtime archive contains links or special files")
		}
	}
	// Finish the gzip stream so its checksum is verified too.
	if _, err := io.Copy(io.Discard, compressed); err != nil { return err }
	return nil
}

func copyFile(source, destination string) error {
	input, err := os.Open(source)
	if err != nil { return err }
	defer input.Close()
	output, err := os.OpenFile(destination, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
	if err != nil { return err }
	_, copyErr := io.Copy(output, input)
	closeErr := output.Close()
	if copyErr != nil { return copyErr }
	return closeErr
}

func install(ctx context.Context, options installOptions) (folder string, installErr error) {
	if !filepath.IsAbs(options.Root) { return "", errors.New("installation root must be absolute") }
	if err := os.MkdirAll(options.Root, 0700); err != nil { return "", err }
	if err := options.PrivateDirectory(options.Root); err != nil { return "", err }
	versions := filepath.Join(options.Root, "versions")
	if err := os.MkdirAll(versions, 0700); err != nil { return "", err }
	if err := options.PrivateDirectory(versions); err != nil { return "", err }
	logPath := filepath.Join(options.Root, "installer.log")
	if info, err := os.Lstat(logPath); err == nil {
		if !info.Mode().IsRegular() { return "", errors.New("invalid log path") }
		if err := options.PrivateDirectory(logPath); err != nil { return "", err }
	} else if !os.IsNotExist(err) { return "", err }
	log, err := os.OpenFile(logPath, os.O_WRONLY|os.O_CREATE|os.O_APPEND, 0600)
	if err != nil { return "", err }
	defer func() {
		if installErr != nil { fmt.Fprintln(log, "Installation failed:", installErr) }
		log.Close()
	}()
	progress := options.Progress
	options.Progress = func(value string) { fmt.Fprintln(log, value); progress(value) }
	cache := filepath.Join(options.Root, "download-cache")
	if err := os.MkdirAll(cache, 0700); err != nil { return "", err }
	if err := options.PrivateDirectory(cache); err != nil { return "", err }
	stage, err := os.MkdirTemp(options.Root, ".install-")
	if err != nil { return "", err }
	defer func() { if stage != "" { os.RemoveAll(stage) } }()
	if err := options.PrivateDirectory(stage); err != nil { return "", err }
	options.Progress("Verifying installer components…")
	if err := extractPayload(options.Payload, stage); err != nil { return "", err }
	pinsData, err := os.ReadFile(filepath.Join(stage, "runtime-pins.json"))
	if err != nil { return "", err }
	var pins struct { Windows map[string]runtimePin `json:"windows"` }
	if err := json.Unmarshal(pinsData, &pins); err != nil { return "", err }
	options.Progress("Downloading the local runtime. This may take a few minutes…")
	archive := filepath.Join(stage, "python.tar.gz")
	download := options.Download
	if download == nil { download = downloadRuntime }
	if err := download(ctx, pins.Windows["x86_64"], archive); err != nil { return "", err }
	if err := extractRuntime(archive, stage); err != nil { return "", err }
	if err := os.Remove(archive); err != nil { return "", err }
	if err := copyFile(options.Executable, filepath.Join(stage, "native-host.exe")); err != nil { return "", err }
	python := filepath.Join(stage, "python", "python.exe")
	env := append(os.Environ(), "PLAYWRIGHT_BROWSERS_PATH="+filepath.Join(stage, "browsers"))
	run := func(args ...string) error {
		commandCtx, cancel := context.WithTimeout(ctx, 15*time.Minute)
		defer cancel()
		return options.Run(commandCtx, python, args, env, log)
	}
	options.Progress("Installing local components. No AI weights are downloaded…")
	if err := run("-I", "-m", "pip", "--isolated", "install", "--only-binary=:all:", "--disable-pip-version-check", "--index-url", "https://pypi.org/simple", "--cache-dir", cache, "-r", filepath.Join(stage, "runtime-requirements.txt")); err != nil { return "", err }
	if err := run("-I", "-m", "playwright", "install", "chromium", "--only-shell"); err != nil { return "", err }
	if err := run("-I", "-c", "from docling_parse.pdf_parser import DoclingPdfParser; from playwright.async_api import async_playwright; print('Local components verified.')"); err != nil { return "", err }
	if err := ctx.Err(); err != nil { return "", err }
	root := filepath.Join(versions, time.Now().UTC().Format("20060102150405")+"-"+filepath.Base(stage))
	if err := os.Rename(stage, root); err != nil { return "", err }
	stage = "" // Promoted releases and existing user settings are never deleted on failure.
	options.Progress("Connecting Chrome, Edge, Chromium and Firefox…")
	python = filepath.Join(root, "python", "python.exe")
	env = append(os.Environ(), "PLAYWRIGHT_BROWSERS_PATH="+filepath.Join(root, "browsers"))
	if err := run("-I", filepath.Join(root, "provision_windows_entry.py"), "--root", root, "--install-root", options.Root); err != nil { return "", fmt.Errorf("browser registration failed: %w", err) }
	return filepath.Join(root, "chrome-extension"), nil
}
