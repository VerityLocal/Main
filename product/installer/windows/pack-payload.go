//go:build ignore

// Maintainer-only deterministic ZIP writer; not compiled into the installer.
package main

import (
	"archive/zip"
	"flag"
	"io"
	"os"
	"path/filepath"
	"time"
)

func main() {
	source := flag.String("source", "", "source directory")
	output := flag.String("output", "", "output archive")
	flag.Parse()
	file, err := os.Create(*output)
	if err != nil { panic(err) }
	writer := zip.NewWriter(file)
	err = filepath.WalkDir(*source, func(name string, info os.DirEntry, err error) error {
		if err != nil { return err }
		if info.IsDir() { return nil }
		if info.Type() != 0 { return os.ErrInvalid }
		relative, err := filepath.Rel(*source, name)
		if err != nil { return err }
		header := &zip.FileHeader{Name: filepath.ToSlash(relative), Method: zip.Deflate}
		header.SetModTime(time.Date(1980, 1, 1, 0, 0, 0, 0, time.UTC))
		header.SetMode(0600)
		target, err := writer.CreateHeader(header)
		if err != nil { return err }
		input, err := os.Open(name)
		if err != nil { return err }
		_, err = io.Copy(target, input)
		input.Close()
		return err
	})
	if err != nil { panic(err) }
	if err := writer.Close(); err != nil { panic(err) }
	if err := file.Close(); err != nil { panic(err) }
}
