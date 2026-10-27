"""Smoke-test a running local or Render deployment without generating media."""
import json
import os
import sys
import urllib.error
import urllib.request

BASE = os.getenv("API_BASE", "http://127.0.0.1:10000").rstrip("/")
TOKEN = os.getenv("API_ACCESS_TOKEN", "").strip()


def fetch(path):
    req = urllib.request.Request(BASE + path, headers={"User-Agent": "MADX-Smoke-Test/18.0"})
    if TOKEN:
        req.add_header("Authorization", "Bearer " + TOKEN)
    with urllib.request.urlopen(req, timeout=20) as response:
        return response.status, response.read().decode("utf-8", "replace")


def main():
    failed = False
    for path in ("/", "/health", "/auth", "/builder", "/reverse", "/v1/status", "/v1/catalog", "/v1/models", "/docs"):
        try:
            status, body = fetch(path)
            if status != 200:
                raise RuntimeError(f"HTTP {status}")
            print(f"PASS {path}: HTTP {status} ({len(body)} bytes)")
            if path == "/health":
                parsed = json.loads(body)
                print(f"  version={parsed.get('version')} adapter_mode={parsed.get('provider_adapters')}")
            if path == "/v1/catalog":
                parsed = json.loads(body)
                print(f"  source={parsed.get('source')}, rows={len(parsed.get('rows', []))}")
        except Exception as exc:
            failed = True
            print(f"FAIL {path}: {type(exc).__name__}: {exc}")
    if failed:
        return 1
    print("Smoke check passed. This checks service endpoints, not live AI generation.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
