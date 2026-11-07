"""Copy local extension setup to the clipboard without printing credentials."""

import argparse
import json
import os
import subprocess

import httpx

from backend.app.core.config import PROJECT_ROOT, Settings

DEMO_TEXT = "Alice visited Paris during the summer of 2024 and toured the city museum."
API = "http://127.0.0.1:8787/api/v1"


def setup_script(auth, csrf, extension_ids):
    configuration = json.dumps(
        {"auth": auth, "csrf": csrf, "extensionIds": extension_ids, "text": DEMO_TEXT}
    )
    return (
        "(async () => {\nconst setup = "
        + configuration
        + ";\n"
        + r"""
  if (location.protocol !== "chrome-extension:" || location.pathname !== "/panel.html" ||
      typeof chrome === "undefined" || !setup.extensionIds.includes(chrome.runtime?.id)) {
    throw new Error("Open the Console inside your paired Verity Local extension panel.");
  }
  const $ = id => document.getElementById(id);
  if (!$('save-settings') || !$('analyze')) throw new Error("Open the Verity Local panel first.");
  if ($('analyze').disabled) throw new Error("Wait for the current analysis to finish first.");

  const response = await fetch("http://127.0.0.1:8787/api/v1/sources", {
    method: "POST", credentials: "omit", cache: "no-store", signal: AbortSignal.timeout(12000),
    headers: { "X-Local-Token": setup.auth, "X-CSRF-Token": setup.csrf,
      "Content-Type": "application/json" },
    body: JSON.stringify({ source_id: "setup_" + crypto.randomUUID(),
      title: "Verity setup example", text: setup.text, reliability: "unrated" })
  });
  if (!response.ok) throw new Error("Reference setup failed (HTTP " + response.status + ").");

  const stored = await chrome.storage.local.get("preferences");
  $('auth-token').value = setup.auth;
  $('csrf-token').value = setup.csrf;
  $('excluded-domains').value = (stored.preferences?.excluded || []).join(", ");

  // The existing Save handler owns credential storage and the connection check.
  // Observe its completion so a late connection message cannot overwrite results.
  await new Promise((resolve, reject) => {
    $('status').textContent = "Connecting for setup...";
    const observer = new MutationObserver(() => {
      const message = $('status').textContent;
      if (message === "Connecting for setup...") return;
      observer.disconnect(); clearTimeout(timeout);
      if (message.startsWith("Local analysis ready.")) resolve();
      else reject(new Error(message));
    });
    const timeout = setTimeout(() => {
      observer.disconnect(); reject(new Error("Connection timed out. Check the backend window."));
    }, 40000);
    observer.observe($('status'), { childList: true, subtree: true, characterData: true });
    $('save-settings').click();
  });

  $('manual-mode').click();
  $('document-text').value = setup.text;
  $('document-text').dispatchEvent(new Event("input", { bubbles: true }));
  $('engine-ai').checked = true;
  $('engine-copy').checked = true;
  $('engine-claims').checked = false;
  $('external-consent').checked = false;
  $('analyze').click();
  console.info("Verity is connected. The sample analysis is running in the panel.");
})();
"""
    )


def main():
    parser = argparse.ArgumentParser(
        description="Copy a command that connects the extension and runs a local overlap example"
    )
    parser.parse_args()
    if os.name != "nt":
        raise SystemExit("This clipboard helper requires Windows PowerShell.")
    try:
        settings = Settings(_env_file=PROJECT_ROOT / ".env")
    except (ValueError, OSError):
        raise SystemExit("Could not read valid local settings from the project .env.") from None
    if settings.port != 8787:
        raise SystemExit("The extension needs the backend on port 8787.")
    extension_ids = [
        origin.removeprefix("chrome-extension://")
        for origin in settings.allowed_origins
        if origin.startswith("chrome-extension://")
    ]
    if not extension_ids:
        raise SystemExit(
            "Pair your extension first: python -m backend.scripts.pair_extension YOUR_EXTENSION_ID"
        )
    auth, csrf = settings.auth_token.get_secret_value(), settings.csrf_token.get_secret_value()
    try:
        response = httpx.get(
            API + "/health", headers={"X-Local-Token": auth}, timeout=5, trust_env=False
        )
    except httpx.HTTPError:
        raise SystemExit("Start the backend first: python -m backend.app.main") from None
    if response.status_code != 200:
        raise SystemExit(
            f"Backend returned HTTP {response.status_code}. Restart it with the current .env."
        )
    try:
        copied = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "$ErrorActionPreference='Stop'; Set-Clipboard -Value ([Console]::In.ReadToEnd())",
            ],
            input=setup_script(auth, csrf, extension_ids),
            text=True,
            capture_output=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise SystemExit(
            "Could not access the clipboard. Run this in Windows PowerShell."
        ) from None
    if copied.returncode:
        raise SystemExit("Could not copy setup. Run the command again in Windows PowerShell.")
    print("Setup copied to your clipboard.")
    print("1. Open the Verity Local extension panel.")
    print("2. Right-click inside the panel, choose Inspect, then select Console.")
    print("3. Paste (Ctrl+V) and press Enter there.")
    print("It saves the connection, adds one example source, and starts an overlap analysis.")


if __name__ == "__main__":
    main()
