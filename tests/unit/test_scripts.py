import sys

import pytest

from backend.app.schemas.document import Document
from backend.scripts import init_local, make_document


def test_make_document_preserves_utf8_and_newlines_without_overwrite(tmp_path, monkeypatch, capsys):
    original = "Private Unicode 😀\r\nSecond line."
    source, output = tmp_path / "source.txt", tmp_path / "document.json"
    source.write_bytes(b"\xef\xbb\xbf" + original.encode("utf-8"))
    monkeypatch.setattr(sys, "argv", ["make_document", str(source), "--output", str(output)])
    make_document.main()
    document = Document.model_validate_json(output.read_text(encoding="utf-8"))
    assert document.extracted_text == original
    assert original not in capsys.readouterr().out
    with pytest.raises(FileExistsError):
        make_document.main()


def test_init_cli_never_displays_or_overwrites_secrets(tmp_path, monkeypatch, capsys):
    path = tmp_path / ".env"
    monkeypatch.setattr(sys, "argv", ["init_local", "--output", str(path)])
    init_local.main()
    captured = capsys.readouterr().out
    for line in path.read_text(encoding="utf-8").splitlines()[:2]:
        assert line.split("=", 1)[1] not in captured
    with pytest.raises(SystemExit, match="already exists"):
        init_local.main()
