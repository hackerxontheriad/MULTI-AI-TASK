# Security status / limits

- Google login verifies the Google ID token signature/client ID and requires `email_verified == true`; session cookies are encrypted, HttpOnly, SameSite=Lax and Secure by default. Configure Google OAuth authorized JavaScript origins and set `GOOGLE_CLIENT_ID` + `SESSION_ENCRYPTION_KEY`.
- API access token is a machine credential. Anyone who obtains it can use protected API routes, so it must stay server-side or in an owner-controlled client secret store; do not embed it in frontend source, a public APK, a screenshot, or a repository.
- `DIAGNOSTICS_PASSWORD` gates `/v1/diagnostics`; if unset, the route intentionally returns 404. The diagnostics HTML itself is public but cannot fetch private diagnostics without the password.
- Security headers include CSP, `nosniff`, frame protections, referrer policy and HSTS on HTTPS requests. No implementation makes a web application uncrackable. TSX and minification are not security boundaries.
- HTML preview executes only inside `iframe sandbox="allow-scripts"` without same-origin permission; preview CSP blocks network `connect-src`. It is for visual/testing preview, not a fully secure browser sandbox against every browser vulnerability.
- The six agents and external adapters use server-configured routes. Connector `configured` means a key/URL exists; `reachable` means the configured gateway `/models` endpoint responded. Neither proves that a prompt will succeed.
- Reverse-engineering utility in `scripts/audit_project.py` never executes input content. A static scan is not a complete security audit.
- Free tiers are quota-limited and may require keys/verification. OmniRoute/New-API/One-API are gateway software; they do not grant unlimited hosted tokens or cloud compute by themselves.
- No API keys, Google secrets, bearer token values or signing key were intentionally added to this archive.
