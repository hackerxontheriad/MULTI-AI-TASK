# Google Flow browser adapter (experimental)

Repository selected for integration research: https://github.com/eddie-fqh/flow-py

It advertises text-to-video, image-to-video, video extension and editing through Playwright-driven Google Flow UI. It is unofficial and not a Google API. Google may change the UI, require reCAPTCHA interaction, reject headless Chromium, or limit account credits. Render free-tier memory can be insufficient for Chromium.

## What this ZIP changes
- Installs Playwright Chromium in the Docker image.
- Adds the `flow-py` package dependency for adapter development.
- Includes `xvfb`/`xauth` to support a virtual display if a headed browser session is configured.

## What it does NOT claim
- It does not automatically authenticate each MadEx user into Flow.
- Google Drive OAuth permission is not the same as Google Flow browser authentication.
- It does not report a successful video until a provider adapter is connected, the real MP4 is received, and Drive upload confirms success.
- A persistent Flow browser profile must be supplied securely and tested. Do not commit profile/cookies to GitHub or share one account's profile across users.

## Deployment architecture needed for real generation
1. User signs into MadEx with Google.
2. User separately authorizes Drive `drive.file` scope when choosing “Save to Drive”.
3. The Flow adapter must have an authenticated Flow session for the correct user. A normal OAuth Drive token cannot create that Flow session.
4. The worker submits the prompt through the actual Flow UI, waits for completion, and downloads the real MP4.
5. The server uploads that MP4 to the user's Drive and sends the confirmed `webViewLink`.
6. If Flow auth, quota, CAPTCHA, or generation fails, stop and show a real error; never return a sample video as success.

For a multi-user public app, do not put one shared Flow login profile behind every user's request. That would generate under the wrong Google account and can leak access. A per-user authenticated browser/session design and a memory-tested worker are required. The official Google developer video-generation APIs are a more reliable alternative, but may have different pricing/credit terms.
