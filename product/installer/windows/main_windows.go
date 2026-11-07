package main

import (
	"context"
	_ "embed"
	"encoding/binary"
	"errors"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"syscall"
	"time"
	"unsafe"
)

//go:embed payload.zip
var payload []byte

func message(text string, flags uintptr) uintptr {
	answer, _, _ := user32.NewProc("MessageBoxW").Call(0, uintptr(unsafe.Pointer(utf16(text))), uintptr(unsafe.Pointer(utf16("Verity Installer"))), flags)
	return answer
}

type countingWriter struct { Writer io.Writer; Written int }
func (writer *countingWriter) Write(data []byte) (int, error) {
	count, err := writer.Writer.Write(data)
	writer.Written += count
	return count, err
}

func nativeHost(executable string) {
	root := filepath.Dir(executable)
	command := exec.Command(filepath.Join(root, "python", "python.exe"), "-I", filepath.Join(root, "native_entry.py"), "native", "--release", filepath.Join(root, "release.json"), "--config", filepath.Join(filepath.Dir(filepath.Dir(root)), "helper.json"), "--entrypoint", filepath.Join(root, "native_entry.py"))
	// Caller arguments are forwarded only to the Python validator, never to a shell.
	command.Args = append(command.Args, os.Args[1:]...)
	output := &countingWriter{Writer: os.Stdout}
	command.Stdin, command.Stdout, command.Stderr = os.Stdin, output, io.Discard
	command.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: 0x08000000}
	if err := command.Run(); err != nil && output.Written == 0 {
		body := []byte(`{"protocol":1,"ready":false,"code":"start_failed"}`)
		binary.Write(os.Stdout, binary.LittleEndian, uint32(len(body)))
		os.Stdout.Write(body)
	}
}

type windowClass struct {
	Size, Style uint32
	Procedure uintptr
	ClassExtra, WindowExtra int32
	Instance, Icon, Cursor, Background, MenuName, ClassName, SmallIcon uintptr
}

type winMessage struct {
	Window uintptr
	Message uint32
	WParam, LParam uintptr
	Time uint32
	X, Y int32
	Private uint32
}

var cancelInstall context.CancelFunc
var statusLabel uintptr

func setStatus(value string) {
	if statusLabel != 0 { user32.NewProc("SetWindowTextW").Call(statusLabel, uintptr(unsafe.Pointer(utf16(value)))) }
}

func windowProcedure(window uintptr, event uint32, wparam, lparam uintptr) uintptr {
	switch event {
	case 0x0010: // WM_CLOSE: cancel work, then wait for its owned subprocesses to exit.
		if cancelInstall != nil { cancelInstall(); setStatus("Cancelling installation…"); return 0 }
	case 0x8001: // Installation finished.
		user32.NewProc("DestroyWindow").Call(window)
		return 0
	case 0x0002:
		user32.NewProc("PostQuitMessage").Call(0)
		return 0
	}
	result, _, _ := user32.NewProc("DefWindowProcW").Call(window, uintptr(event), wparam, lparam)
	return result
}

func installWindow(options installOptions) (string, error) {
	runtime.LockOSThread()
	defer runtime.UnlockOSThread()
	instance, _, _ := kernel.NewProc("GetModuleHandleW").Call(0)
	cursor, _, _ := user32.NewProc("LoadCursorW").Call(0, 32512)
	className := utf16("VerityInstaller")
	defer runtime.KeepAlive(className)
	class := windowClass{Procedure: syscall.NewCallback(windowProcedure), Instance: instance, Cursor: cursor, Background: 6, ClassName: uintptr(unsafe.Pointer(className))}
	class.Size = uint32(unsafe.Sizeof(class))
	registered, _, err := user32.NewProc("RegisterClassExW").Call(uintptr(unsafe.Pointer(&class)))
	if registered == 0 { return "", err }
	window, _, err := user32.NewProc("CreateWindowExW").Call(0, class.ClassName, uintptr(unsafe.Pointer(utf16("Verity Installer"))), 0x10CA0000, 0x80000000, 0x80000000, 550, 190, 0, 0, instance, 0)
	if window == 0 { return "", err }
	statusLabel, _, _ = user32.NewProc("CreateWindowExW").Call(0, uintptr(unsafe.Pointer(utf16("STATIC"))), uintptr(unsafe.Pointer(utf16("Preparing your local desktop companion…"))), 0x50000000, 20, 25, 495, 95, window, 0, instance, 0)
	font, _, _ := syscall.NewLazyDLL("gdi32.dll").NewProc("GetStockObject").Call(17)
	user32.NewProc("SendMessageW").Call(statusLabel, 0x0030, font, 1)
	ctx, cancel := context.WithTimeout(context.Background(), 120*time.Minute)
	defer cancel()
	cancelInstall = cancel
	options.Progress = setStatus
	type outcome struct { Folder string; Error error }
	finished := make(chan outcome, 1)
	go func() {
		folder, err := install(ctx, options)
		finished <- outcome{folder, err}
		user32.NewProc("PostMessageW").Call(window, 0x8001, 0, 0)
	}()
	var msg winMessage
	for {
		result, _, _ := user32.NewProc("GetMessageW").Call(uintptr(unsafe.Pointer(&msg)), 0, 0, 0)
		if int32(result) <= 0 { break }
		user32.NewProc("TranslateMessage").Call(uintptr(unsafe.Pointer(&msg)))
		user32.NewProc("DispatchMessageW").Call(uintptr(unsafe.Pointer(&msg)))
	}
	result := <-finished
	cancelInstall = nil
	statusLabel = 0
	return result.Folder, result.Error
}

func main() {
	executable, err := os.Executable()
	if err != nil { return }
	if strings.EqualFold(filepath.Base(executable), "native-host.exe") { nativeHost(executable); return }
	headless := len(os.Args) == 2 && os.Args[1] == "--headless"
	fail := func(text string) { if headless { os.Stderr.WriteString(text+"\n") } else { message(text, 0x10) } }
	if err := supportedWindows(); err != nil { fail(err.Error()); os.Exit(1) }
	cache, err := os.UserCacheDir()
	if err != nil { fail("The per-user installation folder is unavailable."); os.Exit(1) }
	root := filepath.Join(cache, "Verity")
	if headless && os.Getenv("VERITY_INSTALL_ROOT") != "" { root = os.Getenv("VERITY_INSTALL_ROOT") }
	closeMutex, err := installerMutex(root)
	if err != nil { fail(err.Error()); os.Exit(1) }
	defer closeMutex()
	if !headless && message("Install Verity's local companion? Setup downloads its runtime, browser and about 1.9 GB of reviewed prose/semantic models. Binoculars adds about 29 GB only on machines with at least 64 GB RAM. Code models require a permitted checkpoint/reference corpus. Authorship stays local; AI percentages require independent calibration. No administrator password is needed.", 0x24) != 6 { return }
	options := installOptions{Root: root, Executable: executable, Payload: payload, PrivateDirectory: privateDirectory, Run: runHidden}
	var folder string
	if headless {
		options.Progress = func(value string) { os.Stdout.WriteString(value+"\n") }
		ctx, cancel := context.WithTimeout(context.Background(), 120*time.Minute)
		defer cancel()
		folder, err = install(ctx, options)
	} else { folder, err = installWindow(options) }
	if err != nil {
		if errors.Is(err, context.Canceled) { if !headless { message("Installation cancelled. Existing settings were preserved.", 0x40) }; return }
		fail("Installation could not finish. Existing settings were preserved. Check your internet connection and run the installer again. Diagnostic log: "+filepath.Join(root, "installer.log"))
		os.Exit(1)
	}
	if headless { os.Stdout.WriteString("Desktop companion installed. Extension folder: "+folder+"\n"); return }
	openFolder(folder)
	message("Verity is installed. Load the chrome-extension folder shown in Explorer into Chrome or Edge. Pairing and companion startup are automatic. Reviewed models were provisioned where hardware permits; code assets may still be missing. AI percentages remain unavailable until independently calibrated.", 0x40)
}
