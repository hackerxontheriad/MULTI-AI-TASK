# MADX v18 security notes

- Google sign-in uses the official ID-token flow; passwords are not collected by the app. Optional allowlisting can restrict eligible verified email addresses. The encrypted HttpOnly session is capped at 30 days by the current setting. Provider web logins and 2-step verification are not bypassed.
- `API_ACCESS_TOKEN` gates protected APIs when configured; an authenticated Google session is also accepted. Keep the API token private and do not embed it into public source or an APK.
- `ADMIN_ACCESS_TOKEN` is a separate independent secret (minimum 32 characters). `/admin?token=...` exchanges it for a signed HttpOnly cookie and redirects to a clean URL; the token still may be visible to hosting/proxy access logs, so use HTTPS and rotate it if exposed. Admin diagnostics/terminal routes are protected by that cookie. The terminal accepts an allowlist only; no arbitrary shell, command chaining, sudo or secret-file reading.
- Security headers, rate limits, request limits, provider error redaction and non-root Docker execution are configured, but do not make a system unbreakable. Review platform proxy logging, secret-manager settings and OAuth origins as well.
- Project-generated files are validated against path traversal, blocked secret filenames, duplicate paths and output limits. Generated project code is packaged but never executed by the application. Test it inside a separate sandbox before deployment.
- Reverse Audit heuristics can miss threats or flag harmless patterns. It does not extract archive files or execute them. Treat results as triage, not a full audit or proof of vulnerability.
- Kali runs in the separate local Docker lab, not as a hosted arbitrary-command interface. Only scan systems you own or have explicit authorization to test.
- Render Free local filesystem is ephemeral; a persistent database/storage plan is required for durable project records and archive blobs.
- No API keys, OAuth secrets, end-user passwords, bearer token values or signing keys are intentionally included in the archive.
