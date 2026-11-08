"""UI-independent single-operation worker ownership and credential-free exports."""
import json
import multiprocessing
import os
import signal
import tempfile
from pathlib import Path

from . import VERSION
from .worker import serve


class Controller:
    def __init__(self, root):
        self.root, self.process, self.connection = str(root), None, None
        self.job = None
        self.busy = False

    def submit(self, operation, **payload):
        if self.busy:
            raise ValueError("Wait for the current operation or cancel it")
        if self.process is None or not self.process.is_alive():
            self.cancel()
            parent, child = multiprocessing.get_context("spawn").Pipe()
            self.process = multiprocessing.get_context("spawn").Process(target=serve, args=(self.root, child), daemon=True)
            self.connection = parent
            try:
                if os.name == "nt":
                    from .windows_job import WindowsJob
                    self.job = WindowsJob()
                self.process.start()
                if self.job:
                    # Assign before the first request can spawn retrieval descendants.
                    self.job.assign(self.process.sentinel)
            except Exception:
                self.cancel()
                raise
            finally:
                child.close()
        self.connection.send({"operation": operation, **payload})
        self.busy = True

    def poll(self):
        messages = []
        try:
            while self.connection and self.connection.poll():
                message = self.connection.recv()
                messages.append(message)
                if message["type"] in {"completed", "error"}:
                    self.busy = False
        except (EOFError, OSError):
            pass
        if self.busy and not self.process.is_alive():
            messages.append({"type": "error", "message": "The worker stopped unexpectedly. No result was accepted. Retry or check available memory."})
            self.busy = False
        return messages

    def cancel(self):
        process = self.process
        job_terminated = bool(self.job and self.job.assigned)
        if self.job:
            self.job.close()
            self.job = None
        if process and process.is_alive():
            if os.name == "posix":
                try:
                    # A group only exists after serve() has established ownership.
                    if os.getpgid(process.pid) == process.pid:
                        os.killpg(process.pid, signal.SIGKILL)
                    else:
                        process.kill()
                except ProcessLookupError:
                    pass
            elif not job_terminated:
                process.kill()  # Also covers a failed job assignment before dispatch.
            process.join(timeout=0.1)
        if self.connection:
            self.connection.close()
        self.process = self.connection = None
        self.busy = False


def export_data(result):
    """No environment, paths, helper settings, raw model features or credentials."""
    document_keys = ("schema_version", "document_digest", "text", "segments", "overall", "notes", "model_states")
    # The engine result is authoritative. No settings/config objects are exported.
    return {"application": "Verity", "version": VERSION, **{key: result[key] for key in document_keys if key in result}}


def text_report(result):
    overall = result["overall"]
    lines = [f"Verity {VERSION}", "AI-written percentage: unavailable until independently calibrated.",
             f"AI scored coverage: {overall['ai']['coverage']:.1%}",
             f"Completed web-search coverage: {overall['plagiarism']['search_coverage']:.1%}",
             "Source similarity is evidence, not proof of copying or misconduct.", ""]
    for row in result["segments"]:
        lines.extend([f"[{row['id']}] {row['kind']} | AI: {row['ai']['status']} | Sources: {row['plagiarism']['status']}", row["text"]])
        match = row["plagiarism"].get("match")
        if match:
            lines.extend([f"Source: {match['title']}", match["url"], f"Similarity: {match['similarity']:.1%}", f"Evidence: {match['excerpt']}"])
        lines.append("")
    return "\n".join(lines)


def save_export(path, result, kind):
    path = Path(path)
    if path.is_symlink():
        raise ValueError("Choose a regular destination file, not a symlink")
    contents = json.dumps(export_data(result), ensure_ascii=False, indent=2, allow_nan=False) if kind == "json" else text_report(result)
    descriptor, name = tempfile.mkstemp(prefix=".verity-export-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(contents + "\n")
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)
