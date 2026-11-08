"""Persistent native Review, Results, Models and Settings window."""
import tkinter as tk
from bisect import bisect_left
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from urllib.parse import urlsplit
import webbrowser

from product.engine.text import Utf16Index
from . import VERSION
from .controller import Controller, save_export


class DesktopApp(tk.Tk):
    def __init__(self, root):
        super().__init__()
        self.bundle = Path(root)
        self.controller = Controller(root)
        self.result = None
        self.operation = None
        self.on_event = None
        self.suppress_edit = False
        self.title(f"Verity · Standard · {VERSION}")
        self.geometry("1100x780")
        self.minsize(780, 580)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.status = tk.StringVar(value="Ready · local analysis stays on this device")
        self.allow_web = tk.BooleanVar(value=False)
        self.consent = tk.BooleanVar(value=False)
        self.font_size = tk.IntVar(value=13)
        ttk.Label(self, text="VERITY", font=("TkDefaultFont", 23, "bold")).pack(anchor="w", padx=22, pady=(18, 2))
        ttk.Label(self, text="Local document review · Standard models included · No authorship verdicts").pack(anchor="w", padx=22, pady=(0, 14))
        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill="both", expand=True, padx=18, pady=(0, 10))
        self.review, self.results, self.models, self.settings = [ttk.Frame(self.tabs, padding=14) for _ in range(4)]
        for frame, label in zip((self.review, self.results, self.models, self.settings), ("Review", "Results", "Models", "Settings")):
            self.tabs.add(frame, text=label)
        self.build_review()
        self.build_results()
        self.build_models()
        self.build_settings()
        ttk.Label(self, textvariable=self.status, wraplength=1040).pack(anchor="w", padx=22, pady=(0, 14))
        self.after(75, self.poll)

    def text_widget(self, parent, height=12):
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True, pady=8)
        widget = tk.Text(frame, wrap="word", height=height, undo=True, font=("TkDefaultFont", self.font_size.get()), padx=10, pady=10)
        scroll = ttk.Scrollbar(frame, command=widget.yview)
        widget.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        widget.pack(side="left", fill="both", expand=True)
        return widget

    def build_review(self):
        bar = ttk.Frame(self.review)
        bar.pack(fill="x")
        self.open_button = ttk.Button(bar, text="Open PDF…", command=self.open_pdf)
        self.open_button.pack(side="left")
        self.scan_button = ttk.Button(bar, text="Analyze locally", command=self.scan)
        self.scan_button.pack(side="left", padx=8)
        self.cancel_button = ttk.Button(bar, text="Cancel & revoke consent", command=self.cancel, state="disabled")
        self.cancel_button.pack(side="left")
        ttk.Button(bar, text="Clear document", command=self.clear).pack(side="right")
        ttk.Label(self.review, text="Paste text/code or open a text-layer PDF. Review and correct extraction before analyzing.", wraplength=980).pack(anchor="w", pady=(12, 0))
        self.editor = self.text_widget(self.review, 20)
        self.editor.bind("<<Modified>>", self.edited)
        self.web_check = ttk.Checkbutton(self.review, text="For this scan, send short passages to public web search and retrieve comparison pages", variable=self.consent, command=self.consent_changed, state="disabled")
        self.web_check.pack(anchor="w", pady=6)
        ttk.Label(self.review, text="Web comparison is optional and disabled by default. Enable it in Settings first. No full-document upload; selected passages leave your device.", wraplength=970).pack(anchor="w")
        self.progress = ttk.Progressbar(self.review, mode="determinate")
        self.progress.pack(fill="x", pady=(12, 0))

    def build_results(self):
        bar = ttk.Frame(self.results)
        bar.pack(fill="x")
        self.export_json = ttk.Button(bar, text="Export JSON…", command=lambda: self.export("json"), state="disabled")
        self.export_json.pack(side="left")
        self.export_text = ttk.Button(bar, text="Export text…", command=lambda: self.export("txt"), state="disabled")
        self.export_text.pack(side="left", padx=8)
        self.summary = tk.StringVar(value="No completed analysis. Unchecked text is not counted as original.")
        ttk.Label(self.results, textvariable=self.summary, wraplength=980).pack(anchor="w", pady=10)
        self.rows = ttk.Treeview(self.results, columns=("kind", "words", "ai", "web"), show="headings", height=6, selectmode="browse")
        for name, label, width in (("kind", "Type", 65), ("words", "Words", 65), ("ai", "Local AI status (not a probability)", 270), ("web", "Web evidence status", 240)):
            self.rows.heading(name, text=label)
            self.rows.column(name, width=width, minwidth=45)
        self.rows.pack(fill="x")
        self.rows.bind("<<TreeviewSelect>>", self.select_segment)
        self.result_text = self.text_widget(self.results, 10)
        self.result_text.configure(state="disabled", undo=False)
        self.result_text.tag_configure("evidence", background="#fff0b3", foreground="#181818")
        self.result_text.tag_configure("unscored", background="#edf0f2", foreground="#181818")
        self.result_text.tag_configure("selected_segment", background="#c9e5ff", foreground="#181818")
        self.evidence = tk.StringVar(value="Select a segment to inspect its status and source evidence. Yellow = source match; grey = unscored. Neither is an authorship verdict.")
        ttk.Label(self.results, textvariable=self.evidence, wraplength=980).pack(anchor="w", pady=6)
        self.source_button = ttk.Button(self.results, text="Open selected source…", command=self.open_source, state="disabled")
        self.source_button.pack(anchor="w")

    def build_models(self):
        ttk.Label(self.models, text="Standard bundle", font=("TkDefaultFont", 18, "bold")).pack(anchor="w")
        ttk.Label(self.models, text="Desklib: English prose signal · BGE-small: English semantic comparison. Weights and tokenizers are included; no model downloads occur.", wraplength=940).pack(anchor="w", pady=10)
        self.model_status = tk.StringVar(value="Bundled assets have not yet been hash-verified in this session. Verification does not establish inference readiness.")
        ttk.Label(self.models, textvariable=self.model_status, wraplength=940).pack(anchor="w", pady=10)
        self.verify_button = ttk.Button(self.models, text="Verify all bundled model files", command=lambda: self.start("verify"))
        self.verify_button.pack(anchor="w", pady=8)
        ttk.Label(self.models, text="Memory gates: Desklib needs 8 GiB physical / 3 GiB available RAM before cold loading; BGE needs 4 GiB physical / 0.5 GiB available. Inference is CPU-only. Low memory or incompatible assets yield unavailable results, never guessed scores.", wraplength=940).pack(anchor="w", pady=12)
        ttk.Label(self.models, text="AI percentages are unavailable: independent calibration is not supplied. GPTSniffer, a production code corpus and Falcon/Binoculars are excluded. Code can be reviewed and source-compared, but the Standard bundle has no code authorship detector.", wraplength=940).pack(anchor="w", pady=12)
        ttk.Button(self.models, text="View bundled license notices", command=self.notices).pack(anchor="w", pady=8)

    def build_settings(self):
        ttk.Label(self.settings, text="Privacy & display", font=("TkDefaultFont", 18, "bold")).pack(anchor="w", pady=(0, 12))
        ttk.Checkbutton(self.settings, text="Allow optional public web-source comparison", variable=self.allow_web, command=self.web_setting_changed).pack(anchor="w")
        ttk.Label(self.settings, text="Enabling this does not grant scan consent. Review requires a separate checkbox for every scan. Disabling it cancels any active operation and revokes consent. Public search may be blocked or incomplete; limited coverage is reported honestly.", wraplength=940).pack(anchor="w", pady=10)
        ttk.Label(self.settings, text="Text size").pack(anchor="w", pady=(14, 2))
        ttk.Spinbox(self.settings, from_=10, to=22, textvariable=self.font_size, width=6, command=self.change_font).pack(anchor="w")
        ttk.Button(self.settings, text="Apply text size", command=self.change_font).pack(anchor="w", pady=6)
        ttk.Button(self.settings, text="Clear document, results and loaded models", command=self.clear).pack(anchor="w", pady=20)
        ttk.Label(self.settings, text="Documents, results and preferences stay in memory and are cleared on exit. Only explicit exports are saved. Original PDFs are never modified. No extension, pairing, listener port, telemetry or background startup service is installed.", wraplength=940).pack(anchor="w", pady=10)
        ttk.Label(self.settings, text="Development build: unsigned and not independently calibrated. Do not use as proof of authorship or misconduct.", wraplength=940).pack(anchor="w", pady=10)

    def busy_state(self, busy):
        for button in (self.open_button, self.scan_button, self.verify_button):
            button.configure(state="disabled" if busy else "normal")
        self.cancel_button.configure(state="normal" if busy else "disabled")
        self.editor.configure(state="disabled" if busy else "normal")

    def start(self, operation, **payload):
        try:
            self.controller.submit(operation, **payload)
        except (ValueError, OSError) as error:
            messagebox.showerror("Cannot start", str(error), parent=self)
            return False
        self.operation = operation
        self.busy_state(True)
        self.progress.configure(value=0)
        self.status.set({"scan": "Loading local models / analyzing… Cancel is available.", "pdf": "Extracting PDF locally…", "verify": "Verifying bundled hashes…"}.get(operation, "Working locally…"))
        return True

    def open_pdf(self):
        path = filedialog.askopenfilename(parent=self, title="Open PDF for local extraction", filetypes=[("PDF documents", "*.pdf")])
        if path:
            self.invalidate()
            self.consent.set(False)
            self.start("pdf", path=path)

    def scan(self):
        text = self.editor.get("1.0", "end-1c")
        if not text.strip() or len(text) > 200_000:
            messagebox.showerror("Input limit", "Provide readable text, up to 200,000 characters.", parent=self)
            return
        consent = self.allow_web.get() and self.consent.get()
        self.invalidate()
        self.consent.set(False)  # Consent is a per-job snapshot, never remembered.
        self.start("scan", text=text, consent=consent)

    def consent_changed(self):
        if self.controller.busy:
            self.cancel()
            self.consent.set(False)

    def web_setting_changed(self):
        if self.controller.busy:
            self.cancel()
        self.consent.set(False)
        self.web_check.configure(state="normal" if self.allow_web.get() else "disabled")

    def cancel(self):
        self.controller.cancel()
        self.operation = None
        self.consent.set(False)
        self.busy_state(False)
        self.progress.configure(value=0)
        self.status.set("Cancelled · no partial analysis was accepted · web consent revoked")

    def clear(self):
        self.cancel()
        self.suppress_edit = True
        self.editor.delete("1.0", "end")
        self.editor.edit_reset()
        self.editor.edit_modified(False)
        self.suppress_edit = False
        self.invalidate()
        self.status.set("Cleared · original files and explicit exports are unchanged")

    def edited(self, _event=None):
        if self.editor.edit_modified():
            if not self.suppress_edit:
                self.invalidate()
                self.consent.set(False)
            self.editor.edit_modified(False)

    def invalidate(self):
        self.result = None
        self.rows.delete(*self.rows.get_children())
        self.result_text.configure(state="normal")
        self.result_text.delete("1.0", "end")
        self.result_text.configure(state="disabled")
        for button in (self.export_json, self.export_text, self.source_button):
            button.configure(state="disabled")
        self.summary.set("No current completed analysis. Edits invalidate previous results.")
        self.evidence.set("Select a segment after analysis to inspect its status and evidence.")

    def poll(self):
        for message in self.controller.poll():
            if message["type"] == "progress":
                value = message["value"]
                stage = value["stage"]
                if "total" in value:
                    self.progress.configure(value=100 * value["done"] / max(1, value["total"]))
                    self.status.set(f"{'Local analysis' if stage == 'local' else 'Consented source comparison'}: {value['done']} / {value['total']}")
                else:
                    self.status.set(f"Hash-verifying {value.get('model', 'models')}…")
            elif message["type"] == "error":
                self.operation = None
                self.busy_state(False)
                self.status.set(message["message"])
                messagebox.showerror("Operation unavailable", message["message"], parent=self)
            elif message["type"] == "completed":
                self.busy_state(False)
                operation, result = message["operation"], message["result"]
                self.operation = None
                if operation == "pdf":
                    self.suppress_edit = True
                    self.editor.delete("1.0", "end")
                    self.editor.insert("1.0", result["text"])
                    self.editor.edit_reset()
                    self.editor.edit_modified(False)
                    self.suppress_edit = False
                    self.status.set(result["note"] + (f" {len(result['empty_pages'])} page(s) had no extracted text." if result["empty_pages"] else ""))
                    self.tabs.select(self.review)
                elif operation == "verify":
                    self.model_status.set(" · ".join(f"{name}: {state}" for name, state in result.items()) + ". Integrity is not inference readiness.")
                    self.status.set("Model verification complete. See Models for status.")
                elif operation == "scan":
                    self.show_result(result)
                    self.status.set("Review complete · AI percentage unavailable until independently calibrated")
            if self.on_event:
                self.on_event(message)
        self.after(75, self.poll)

    def show_result(self, result):
        self.result = result
        ai, web = result["overall"]["ai"], result["overall"]["plagiarism"]
        self.summary.set(f"AI-written: unavailable (independent calibration required). Scored AI coverage: {ai['coverage']:.1%}. Completed web-search coverage: {web['search_coverage']:.1%}. Source evidence coverage: {web['coverage']:.1%}. Unchecked text is never original by default.")
        self.model_status.set(" · ".join(f"{name}: {state}" for name, state in result.get("model_states", {}).items()) + ". A computed feature is not a calibrated result.")
        self.rows.delete(*self.rows.get_children())
        widget = self.result_text
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        index, previous = Utf16Index(result["text"]), 0
        for row in result["segments"]:
            self.rows.insert("", "end", iid=row["id"], values=(row["kind"], row["words"], row["ai"]["status"], row["plagiarism"]["status"]))
            first, last = bisect_left(index.boundaries, row["start"]), bisect_left(index.boundaries, row["end"])
            widget.insert("end", result["text"][previous:first])
            widget.mark_set(row["id"] + "_start", "end-1c")
            widget.mark_gravity(row["id"] + "_start", "left")
            tag = "evidence" if row["plagiarism"].get("match") else "unscored"
            widget.insert("end", row["text"], tag)
            widget.mark_set(row["id"] + "_end", "end-1c")
            widget.mark_gravity(row["id"] + "_end", "left")
            previous = last
        widget.insert("end", result["text"][previous:])
        widget.configure(state="disabled")
        self.export_json.configure(state="normal")
        self.export_text.configure(state="normal")
        self.tabs.select(self.results)

    def selected_row(self):
        selection = self.rows.selection()
        return next((row for row in self.result["segments"] if row["id"] == selection[0]), None) if self.result and selection else None

    def select_segment(self, _event=None):
        row = self.selected_row()
        if not row:
            return
        widget = self.result_text
        widget.tag_remove("selected_segment", "1.0", "end")
        widget.tag_add("selected_segment", row["id"] + "_start", row["id"] + "_end")
        widget.see(row["id"] + "_start")
        match = row["plagiarism"].get("match")
        detail = f"Local AI: {row['ai']['status']}; sources: {row['plagiarism']['status']}."
        if match:
            detail += f"\n{match['title']} · similarity {match['similarity']:.1%}\n{match['url']}\nEvidence: {match['excerpt']}"
        self.evidence.set(detail)
        self.source_button.configure(state="normal" if match else "disabled")

    def open_source(self):
        row = self.selected_row()
        match = row["plagiarism"].get("match") if row else None
        if not match:
            return
        url = match["url"]
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            return
        if messagebox.askyesno("Open external source", f"Open this address in your browser?\n\n{url}", parent=self):
            webbrowser.open(url)

    def export(self, kind):
        if not self.result:
            return
        path = filedialog.asksaveasfilename(parent=self, title="Export completed review", defaultextension="." + kind, filetypes=[(kind.upper(), "*." + kind)])
        if path:
            try:
                save_export(path, self.result, kind)
                self.status.set("Export saved only to the destination you selected")
            except (OSError, ValueError):
                messagebox.showerror("Export failed", "Choose a writable regular destination file.", parent=self)

    def change_font(self):
        try:
            size = max(10, min(22, self.font_size.get()))
        except (ValueError, tk.TclError):
            return
        self.font_size.set(size)
        for widget in (self.editor, self.result_text):
            widget.configure(font=("TkDefaultFont", size))

    def notices(self):
        window = tk.Toplevel(self)
        window.title("Verity · Third-party notices")
        window.geometry("850x600")
        widget = self.text_widget(window, 25)
        try:
            widget.insert("1.0", (self.bundle / "THIRD-PARTY-NOTICES.txt").read_text())
        except OSError:
            widget.insert("1.0", "Notices are unavailable: this bundle is incomplete.")
        widget.configure(state="disabled")

    def close(self):
        self.controller.cancel()
        self.destroy()
