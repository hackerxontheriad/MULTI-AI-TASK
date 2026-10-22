"""Live smoke test for a running MadEx Gateway. No provider keys are stored here."""
from __future__ import annotations

import os
import sys
import time
from urllib.parse import urljoin

import httpx

API_BASE = os.getenv("API_BASE", "http://127.0.0.1:10000").rstrip("/")
TOKEN = os.getenv("API_ACCESS_TOKEN", "").strip()
HEADERS = {"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}


def main() -> int:
    timeout = httpx.Timeout(30.0, connect=5.0)
    with httpx.Client(timeout=timeout, headers=HEADERS) as client:
        health = client.get(f"{API_BASE}/health")
        print("[*] Health:", health.status_code, health.text[:800])
        if not health.is_success:
            return 1

        payload = {
            "user_id": "smoke-test",
            "model": os.getenv("TEST_MODEL", "auto"),
            "messages": [
                {"role": "system", "content": "You are a concise Python assistant."},
                {"role": "user", "content": "Write a Python function that returns True when n is prime."},
            ],
            "stream": False,
            "max_tokens": 300,
        }
        print("\n[*] Testing chat completion...")
        try:
            response = client.post(f"{API_BASE}/v1/chat/completions", json=payload)
            print(response.status_code, response.text[:2500])
            if not response.is_success:
                print("Chat request did not succeed. Check configured provider keys and quota.")
        except httpx.HTTPError as exc:
            print("Chat HTTP error:", exc)
            return 1

        if os.getenv("TEST_VIDEO", "0") == "1":
            print("\n[*] Submitting real video-generation job...")
            video_payload = {
                "user_id": "smoke-test",
                "prompt": "A cinematic drone shot over a futuristic neon city at night, smooth camera movement.",
                "aspect_ratio": "16:9",
                "resolution": "720p",
            }
            submitted = client.post(f"{API_BASE}/v1/video/generate", json=video_payload)
            print(submitted.status_code, submitted.text[:1500])
            if submitted.status_code not in (200, 202):
                print("Video submission failed. Check GEMINI_API_KEY and video API access.")
                return 1
            job = submitted.json()
            status_url = urljoin(f"{API_BASE}/", job.get("status_url", ""))
            for _ in range(60):
                status = client.get(status_url)
                print("Video job:", status.text[:1000])
                if status.is_success and status.json().get("status") in {"completed", "failed"}:
                    break
                time.sleep(5)
    return 0


if __name__ == "__main__":
    sys.exit(main())
