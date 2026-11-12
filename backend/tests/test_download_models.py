"""Release installation must not install incomplete or tampered model archives."""

import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from zipfile import ZipFile

from backend.detectors.artifacts import ModelLoadError
from backend.scripts.download_models import install_archive


class ModelInstallTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.archive = self.root / "model.zip"
        self.destination = self.root / "models" / "text_detector"
        self.contents = {"weights.bin": b"inspected weights", "tokenizer.json": b'{"test":true}'}
        self.expected = {name: hashlib.sha256(data).hexdigest() for name, data in self.contents.items()}

    def bundle(self, contents):
        with ZipFile(self.archive, "w") as bundle:
            for name, data in contents.items():
                bundle.writestr("models/text_detector/" + name, data)

    def test_complete_verified_model_is_installed(self):
        self.bundle(self.contents)
        install_archive(self.archive, "text", self.destination, self.expected)
        for name, data in self.contents.items():
            self.assertEqual((self.destination / name).read_bytes(), data)

    def test_tampered_file_does_not_replace_existing_artifacts(self):
        self.destination.mkdir(parents=True)
        for name in self.contents:
            (self.destination / name).write_bytes(b"existing version")
        self.bundle({**self.contents, "tokenizer.json": b"tampered"})
        with self.assertRaises(ModelLoadError):
            install_archive(self.archive, "text", self.destination, self.expected)
        for name in self.contents:
            self.assertEqual((self.destination / name).read_bytes(), b"existing version")

    def test_incomplete_archive_is_rejected(self):
        self.bundle({"weights.bin": self.contents["weights.bin"]})
        with self.assertRaisesRegex(ValueError, "incomplete"):
            install_archive(self.archive, "text", self.destination, self.expected)
        self.assertFalse((self.destination / "weights.bin").exists())

    def test_unexpected_paths_cannot_escape_staging(self):
        self.bundle({**self.contents, "../../../escaped.txt": b"unexpected"})
        with self.assertRaisesRegex(ValueError, "unexpected"):
            install_archive(self.archive, "text", self.destination, self.expected)
        self.assertFalse((self.root / "escaped.txt").exists())

    def test_distributed_notices_are_allowed_outside_inference_files(self):
        self.bundle(self.contents)
        with ZipFile(self.archive, "a") as bundle:
            bundle.writestr("THIRD_PARTY_NOTICES.md", "Upstream attribution")
        install_archive(self.archive, "text", self.destination, self.expected)
        self.assertEqual({item.name for item in self.destination.iterdir()}, set(self.contents))
