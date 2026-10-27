"""Runtime helpers for .env loading and small, read-only host checks.

The production MADX app deliberately does not use browser-session adapters. This module
keeps a small legacy browser-discovery utility for local diagnostics only; it is not
invoked by the production startup path.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Optional

from http_client import redact

_CANDIDATE_NAMES = ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable", "chrome", "chrome.exe")
_CANDIDATE_PATHS = (
    "/usr/local/bin/chromium-safe",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/snap/bin/chromium",
    "/data/data/com.termux/files/usr/bin/chromium",
    "/data/data/com.termux/files/usr/bin/chromium-browser",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
)

_lock = threading.Lock()
_probe_cache: dict[str, Any] = {"at": 0.0, "result": None}
PROBE_TTL = 300.0



def load_dotenv(path: Path | str) -> list[str]:
    """Load KEY=VALUE lines from a .env file without overriding real environment variables.

    The README tells users to copy .env.example to .env, but nothing loaded it, so keys
    placed there were silently ignored. Empty values are skipped so a blank template line
    never masks a real setting. Returns the names that were set (never the values).
    """
    loaded: list[str] = []
    try:
        file = Path(path)
        if not file.is_file():
            return loaded
        for raw in file.read_text(encoding="utf-8-sig").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.lower().startswith("export "):
                line = line[7:].lstrip()
            name, _, value = line.partition("=")
            name, value = name.strip(), value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            elif " #" in value:
                value = value.split(" #", 1)[0].rstrip()
            if not name.replace("_", "").isalnum() or not value or name in os.environ:
                continue
            os.environ[name] = value
            loaded.append(name)
    except Exception:
        return loaded
    return loaded

def _is_executable(path: Optional[str]) -> bool:
    return bool(path) and os.path.isfile(path) and os.access(path, os.X_OK)


def find_chrome() -> Optional[str]:
    """Return a real, executable Chrome/Chromium path or None."""
    # Ignore stale paths instead of allowing a bad override to mask a working
    # executable supplied by the container or host PATH.
    for env_name in ("CHROME_BIN", "CHROMIUM_PATH", "GOOGLE_CHROME_BIN"):
        value = os.getenv(env_name, "").strip()
        if _is_executable(value):
            return value
        if value:
            os.environ.pop(env_name, None)
    for path in _CANDIDATE_PATHS[:1]:  # our wrapper wins when present
        if _is_executable(path):
            return path
    for name in _CANDIDATE_NAMES:
        found = shutil.which(name)
        if found:
            return found
    for path in _CANDIDATE_PATHS[1:]:
        if _is_executable(path):
            return path
    return None


def running_as_root() -> bool:
    geteuid = getattr(os, "geteuid", None)
    return bool(geteuid and geteuid() == 0)


def browser_flags() -> list[str]:
    """Flags that make Chromium start reliably in containers / low-memory hosts."""
    flags = [
        "--headless=new",
        "--disable-gpu",
        "--disable-dev-shm-usage",      # /dev/shm is 64MB in Docker/Render
        "--disable-extensions",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-networking",
        "--mute-audio",
        "--renderer-process-limit=1",
    ]
    no_sandbox = os.getenv("BROWSER_NO_SANDBOX", "auto").strip().lower()
    if no_sandbox in {"1", "true", "yes"} or (no_sandbox == "auto" and (running_as_root() or Path("/.dockerenv").exists())):
        flags.append("--no-sandbox")
    return flags


def configure_runtime() -> dict[str, Any]:
    """Export a valid Chromium path (only if found). Safe to call repeatedly."""
    chrome = find_chrome()
    if chrome:
        os.environ["CHROME_BIN"] = chrome
        os.environ["CHROMIUM_PATH"] = chrome
        os.environ.setdefault("GOOGLE_CHROME_BIN", chrome)
    else:
        # Remove stale values pointing at a missing file so libraries auto-detect/fail clearly.
        for name in ("CHROME_BIN", "CHROMIUM_PATH", "GOOGLE_CHROME_BIN"):
            value = os.getenv(name, "")
            if value and not _is_executable(value):
                os.environ.pop(name, None)
    return {"chrome": chrome, "flags": browser_flags(), "root": running_as_root()}


def probe_browser(force: bool = False) -> dict[str, Any]:
    """Launch the browser once (cached 5 min) and report real success/failure."""
    with _lock:
        now = time.monotonic()
        cached = _probe_cache["result"]
        if cached is not None and not force and now - float(_probe_cache["at"]) < PROBE_TTL:
            return dict(cached)
        chrome = find_chrome()
        result: dict[str, Any] = {"found": bool(chrome), "path": chrome, "version": None,
                                  "launch_ok": False, "flags": browser_flags(), "error": None, "hint": None}
        if not chrome:
            result["error"] = "no Chrome/Chromium executable found"
            result["hint"] = ("Docker image installs chromium automatically. Elsewhere: apt install chromium, "
                              "or Termux `pkg install chromium`, or set CHROME_BIN to the binary.")
        else:
            try:
                version = subprocess.run([chrome, "--version"], capture_output=True, text=True, timeout=10)
                result["version"] = (version.stdout or version.stderr).strip()[:120] or None
            except Exception as exc:
                result["error"] = redact(f"{type(exc).__name__}: {exc}", 300)
            if result["error"] is None:
                profile = tempfile.mkdtemp(prefix="madex-probe-")
                try:
                    cmd = [chrome, *browser_flags(), f"--user-data-dir={profile}", "--dump-dom", "about:blank"]
                    run = subprocess.run(cmd, capture_output=True, text=True, timeout=25)
                    if run.returncode == 0 and "<html" in (run.stdout or "").lower():
                        result["launch_ok"] = True
                    else:
                        tail = (run.stderr or run.stdout or "").strip().splitlines()[-3:]
                        result["error"] = redact(f"exit {run.returncode}: {' | '.join(tail)}", 400)
                        low = result["error"].lower()
                        if "sandbox" in low or "root" in low:
                            result["hint"] = "Running as root needs --no-sandbox; set BROWSER_NO_SANDBOX=1 or use the provided chromium-safe wrapper."
                        elif "shared libraries" in low or "libnss" in low or ".so" in low:
                            result["hint"] = "Missing system libraries. Reinstall the chromium package (it pulls its own deps)."
                        elif "memory" in low or "killed" in low:
                            result["hint"] = "Out of memory. Free hosts with 512MB RAM often cannot run Chromium; use official free-tier API routes instead."
                except subprocess.TimeoutExpired:
                    result["error"] = "browser launch timed out after 25s"
                    result["hint"] = "Host is too slow/low on memory for browser providers; use the official free-tier API routes."
                except Exception as exc:
                    result["error"] = redact(f"{type(exc).__name__}: {exc}", 300)
                finally:
                    shutil.rmtree(profile, ignore_errors=True)
        _probe_cache.update({"at": now, "result": result})
        return dict(result)
