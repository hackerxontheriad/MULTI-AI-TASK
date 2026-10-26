# MadEx Code Preview Environments

This folder defines language-specific preview/build environments for generated code.

- HTML/CSS/JS: render in a sandboxed iframe (`srcdoc`) in the browser.
- PHP: `php:8.3-cli` runtime template; render server-side only in a separate, isolated worker/container.
- Python: `python:3.12-slim` runtime template; execute only in a separate isolated worker/container.
- Java: `eclipse-temurin:21-jdk` runtime template; compile/run only in a separate isolated worker/container.
- Android: Android Gradle project template; build signed APK in CI/Android Studio.

**Security boundary:** do not execute user-generated PHP/Python/Java code inside the public FastAPI web service. A subprocess timeout is not a security sandbox. Use a separate ephemeral container/worker with no secrets, no network, read-only filesystem, CPU/memory/pid limits and a strict timeout. Render's normal web service cannot safely start sibling Docker containers without a separate sandbox service.

The web app should show a code block immediately. For HTML, it can show a live iframe preview. For PHP/Java/Python, show output only when a properly isolated runner is configured; otherwise offer source preview/download and a clear “runtime not connected” status.
