package main

import (
	"context"
	"crypto/sha256"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"os/user"
	"path/filepath"
	"strconv"
	"syscall"
	"time"
	"unsafe"
)

var kernel = syscall.NewLazyDLL("kernel32.dll")
var user32 = syscall.NewLazyDLL("user32.dll")
var advapi = syscall.NewLazyDLL("advapi32.dll")

func utf16(value string) *uint16 {
	result, err := syscall.UTF16PtrFromString(value)
	if err != nil { panic(err) }
	return result
}

func supportedWindows() error {
	var info [48]byte
	kernel.NewProc("GetNativeSystemInfo").Call(uintptr(unsafe.Pointer(&info[0])))
	if *(*uint16)(unsafe.Pointer(&info[0])) != 9 { return errors.New("Windows x64 is required; ARM and 32-bit builds are not supported") }
	var version struct { Size, Major, Minor, Build, Platform uint32; Description [128]uint16 }
	version.Size = uint32(unsafe.Sizeof(version))
	status, _, _ := syscall.NewLazyDLL("ntdll.dll").NewProc("RtlGetVersion").Call(uintptr(unsafe.Pointer(&version)))
	if status != 0 || version.Major < 10 { return errors.New("Windows 10 or 11 x64 is required") }
	return nil
}

func privateDirectory(path string) error {
	attributes, err := syscall.GetFileAttributes(utf16(path))
	if err != nil { return err }
	if attributes & 0x400 != 0 { return errors.New("installation paths cannot be links or reparse points") }
	current, err := user.Current()
	if err != nil { return err }
	// Protected DACL: current user and SYSTEM only, inherited by installed children.
	sddl := "D:P(A;OICI;FA;;;"+current.Uid+")(A;OICI;FA;;;SY)"
	var descriptor uintptr
	result, _, callErr := advapi.NewProc("ConvertStringSecurityDescriptorToSecurityDescriptorW").Call(uintptr(unsafe.Pointer(utf16(sddl))), 1, uintptr(unsafe.Pointer(&descriptor)), 0)
	if result == 0 { return callErr }
	defer kernel.NewProc("LocalFree").Call(descriptor)
	result, _, callErr = advapi.NewProc("SetFileSecurityW").Call(uintptr(unsafe.Pointer(utf16(path))), 0x80000004, descriptor)
	if result == 0 { return callErr }
	return nil
}

func installerMutex(root string) (func(), error) {
	current, err := user.Current()
	if err != nil { return nil, err }
	hash := sha256.Sum256([]byte(current.Uid+root))
	name := fmt.Sprintf("Local\\VerityInstaller-%x", hash[:16])
	handle, _, callErr := kernel.NewProc("CreateMutexW").Call(0, 0, uintptr(unsafe.Pointer(utf16(name))))
	if handle == 0 { return nil, callErr }
	close := func() { kernel.NewProc("CloseHandle").Call(handle) }
	if callErr == syscall.Errno(183) { close(); return nil, errors.New("another Verity installation is already running") }
	return close, nil
}

func runHidden(ctx context.Context, executable string, args, env []string, output io.Writer) error {
	command := exec.CommandContext(ctx, executable, args...)
	command.Env = env
	command.Stdout, command.Stderr = output, output
	command.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: 0x08000000}
	command.WaitDelay = 10*time.Second
	command.Cancel = func() error {
		// Cancel only the child tree launched by this installer, not other helpers.
		killCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		killer := exec.CommandContext(killCtx, filepath.Join(os.Getenv("SystemRoot"), "System32", "taskkill.exe"), "/PID", strconv.Itoa(command.Process.Pid), "/T", "/F")
		killer.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: 0x08000000}
		if err := killer.Run(); err != nil { return command.Process.Kill() }
		return nil
	}
	err := command.Run()
	if ctx.Err() != nil { return ctx.Err() }
	return err
}

func openFolder(path string) {
	syscall.NewLazyDLL("shell32.dll").NewProc("ShellExecuteW").Call(0, uintptr(unsafe.Pointer(utf16("open"))), uintptr(unsafe.Pointer(utf16(path))), 0, 0, 1)
}
