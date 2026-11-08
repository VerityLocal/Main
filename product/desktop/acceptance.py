"""Explicit developer GUI acceptance of the actual app/runtime and genuine models.

Uses first-party functional inputs, never synthetic weights or accuracy claims.
No real document, private path, configuration, or raw inference feature is reported.
"""
import json
import platform
import sys
import time
from pathlib import Path

from .controller import save_export
from .fixtures import SOURCE_TEXT, ORIGINAL_TEXT, pdf


class Acceptance:
    def __init__(self, app, output):
        self.app, self.output = app, Path(output)
        self.output.mkdir(parents=True, exist_ok=False)
        self.report = {"frozen": bool(getattr(sys, "frozen", False)), "os": platform.system(), "architecture": platform.machine(), "checks": {}, "accuracy_claim": False}
        self.phase = "verify"
        self.started = time.monotonic()
        self.beats = 0
        self.errors = []
        # Avoid blocking the harness on expected unavailable-input dialogs.
        from .app import messagebox
        messagebox.showerror = lambda *args, **kwargs: self.errors.append(args)
        app.on_event = self.event
        app.after(100, self.heartbeat)
        app.after(300_000, lambda: self.finish(False, "acceptance_timeout"))
        app.after(100, self.begin)

    def check(self, name, value):
        self.report["checks"][name] = bool(value)
        if not value:
            raise AssertionError(name)

    def heartbeat(self):
        self.beats += 1
        self.app.after(100, self.heartbeat)

    def begin(self):
        try:
            self.check("four_native_tabs", [self.app.tabs.tab(tab, "text") for tab in self.app.tabs.tabs()] == ["Review", "Results", "Models", "Settings"])
            self.check("offline_default_no_consent", not self.app.allow_web.get() and not self.app.consent.get())
            self.check("no_result_before_scan", self.app.result is None and str(self.app.export_json["state"]) == "disabled")
            self.app.start("verify")
        except Exception as error:
            self.finish(False, type(error).__name__)

    def event(self, message):
        if message["type"] == "diagnostic":
            with (self.output / "private-diagnostics.txt").open("a") as stream:
                stream.write(message["message"])
            return
        if message["type"] == "progress":
            return
        try:
            if message["type"] == "error":
                raise AssertionError("unexpected_worker_error")
            result = message["result"]
            if self.phase == "verify":
                self.check("complete_model_hash_verification", result == {"text": "integrity_verified", "semantic": "integrity_verified"})
                self.phase = "pdf"
                self.pdf_path = self.output / "functional-fixture.pdf"
                self.pdf_bytes = pdf("Offline desktop fixture", [SOURCE_TEXT, ORIGINAL_TEXT])
                self.pdf_path.write_bytes(self.pdf_bytes)
                self.app.start("pdf", path=str(self.pdf_path), network_guard=True)
            elif self.phase == "pdf":
                self.check("packaged_pdf_parser", SOURCE_TEXT in result["text"] and ORIGINAL_TEXT in result["text"])
                self.check("original_pdf_unchanged", self.pdf_path.read_bytes() == self.pdf_bytes)
                self.check("editable_extracted_text", self.app.editor.get("1.0", "end-1c") == result["text"])
                self.phase = "scan"
                self.app.invalidate()
                self.app.start("scan", text=result["text"], consent=False, network_guard=True, diagnostics=True)
            elif self.phase == "scan":
                self.check("genuine_desklib_inference", result["model_states"]["text"] == "feature_computed" and any(row["ai"]["status"] == "calibration_required" for row in result["segments"]))
                self.check("no_uncalibrated_ai_percentage", result["overall"]["ai"]["percent"] is None and all(row["ai"]["score"] is None for row in result["segments"]))
                self.check("no_consent_no_web_search", result["overall"]["plagiarism"]["status"] == "not_checked" and all(row["plagiarism"]["status"] == "not_checked" for row in result["segments"]))
                self.check("rendered_text_matches_document", self.app.result_text.get("1.0", "end-1c") == result["text"])
                self.app.rows.selection_set(result["segments"][-1]["id"])
                self.app.select_segment()
                self.check("segment_selection_highlight", bool(self.app.result_text.tag_ranges("selected_segment")))
                save_export(self.output / "functional-export.json", result, "json")
                save_export(self.output / "functional-export.txt", result, "txt")
                exported = json.loads((self.output / "functional-export.json").read_text())
                self.check("json_text_export", exported["document_digest"] == result["document_digest"] and "calibration_required" in (self.output / "functional-export.txt").read_text())
                self.check("no_configuration_in_export", not any(key in exported for key in ("token", "signals", "config", "path", "asset_manifest", "features")))
                self.phase = "semantic"
                self.app.start("semantic_test", left=SOURCE_TEXT, right=SOURCE_TEXT, network_guard=True)
            elif self.phase == "semantic":
                self.check("genuine_bge_inference", result["computed"] and result["bounded"])
                self.phase = "browser"
                self.app.start("browser_test")
            elif self.phase == "browser":
                self.check("bundled_retrieval_browser", result["rendered"])
                self.app.editor.insert("end", "\n\nEdited document.")
                self.app.edited()
                self.check("edit_invalidates_results", self.app.result is None and str(self.app.export_json["state"]) == "disabled")
                self.app.start("scan", text=(SOURCE_TEXT + "\n\n") * 100, consent=False, network_guard=True)
                self.app.after(150, self.cancel_test)
        except Exception as error:
            self.finish(False, str(error) if isinstance(error, AssertionError) else type(error).__name__)

    def cancel_test(self):
        try:
            process = self.app.controller.process
            before = time.monotonic()
            self.app.cancel()
            self.check("responsive_hard_cancel", time.monotonic() - before < 0.8 and not process.is_alive() and not self.app.controller.busy and self.app.result is None)
            self.app.allow_web.set(True)
            self.app.web_setting_changed()
            self.app.consent.set(True)
            self.app.allow_web.set(False)
            self.app.web_setting_changed()
            self.check("web_disable_revokes_consent", not self.app.consent.get() and str(self.app.web_check["state"]) == "disabled")
            self.app.clear()
            self.check("clear_releases_document_and_worker", not self.app.editor.get("1.0", "end-1c") and self.app.result is None and self.app.controller.process is None)
            self.check("gui_event_loop_responsive", self.beats > 10)
            self.check("no_unexpected_dialogs", not self.errors)
            self.finish(True)
        except Exception as error:
            self.finish(False, str(error))

    def finish(self, passed, error=None):
        self.report.update(passed=passed, elapsed_seconds=round(time.monotonic() - self.started, 2))
        if error:
            self.report["failure"] = error
        (self.output / "acceptance.json").write_text(json.dumps(self.report, indent=2) + "\n")
        self.app.close()
