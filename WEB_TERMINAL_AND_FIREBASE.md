# MADX Web Terminal + Firebase Storage

## What changed

- The MADX site includes `/terminal`, with command history, output console, runtime status, provider catalog refresh, Ollama diagnostics, and storage status.
- The hosted terminal is intentionally allow-list only. It is not a general Linux shell, root console, Termux clone, or arbitrary script runner. Commands include `help`, `status`, `whoami`, `pwd`, `uname -a`, `python --version`, `pip --version`, `pip list`, `df -h`, `free -m`, `git status`, `ls [workspace-relative-path]`, `providers`, `connectors status`, `models`, `providers refresh`, `ollama status`, `storage status`, and `db status`. Arbitrary shell operators, `sudo`, and unrecognized commands are rejected.
- Adapter checks inspect configured provider/API routes; they do not install or host separate gateway products such as LiteLLM, OmniRoute, 9Router, New-API, One-API, or PawanOsman-compatible gateways. Configure those in a separately reachable service first.
- Agent Lab no longer includes the `MAD X Auto` catalog display row as a selectable provider. Auto is resolved once by the backend when supplied as the requested route. The actual configured model is used for all six task roles in Free Edition; a failure does not switch to another model.
- Local Ollama preset IDs are marked not-ready until a live `/api/tags` response proves the server is reachable and the model is installed.

## Firebase setup for uploads and generated project ZIPs

1. Create or select a Firebase project.
2. Create a Cloud Storage bucket and enable Cloud Firestore (Native mode) in that project.
3. Create/download a service-account JSON key in Firebase Project settings → Service accounts. Protect that key as a production secret.
4. In Render → MADX service → Environment, set:
   - `FIREBASE_SERVICE_ACCOUNT_JSON`: the complete service-account JSON as one environment-variable value (do not commit it to GitHub).
   - `FIREBASE_STORAGE_BUCKET`: the exact bucket name from the Firebase Storage console (not a download URL).
   - `FIREBASE_PROJECT_ID`: optional if `project_id` is already present in the service-account JSON.
5. Redeploy. Open `/terminal`, run `storage status`, then upload a small file and verify list/download/delete in My Files.

The Admin SDK runs server-side with privileged credentials, so these environment variables must never be sent to frontend JavaScript or returned by diagnostics. Restrict access to the service-account key and grant only the IAM permissions needed for the chosen bucket and Firestore database. Firebase costs/quotas and bucket availability depend on current project settings; persistent storage is not guaranteed to be unlimited or free.

### Storage behavior

- Both Firebase variables must be set to select the Firebase backend. If absent, the app uses the temporary local file store for uploads and stores generated ZIP bytes in the application database.
- If Firebase is configured but unreachable or misconfigured, uploads and generated ZIP creation return explicit errors rather than silently writing to ephemeral Render storage.
- Uploaded file bytes live in Cloud Storage; private file metadata and ownership hashes live in the `madx_files` Firestore collection. Generated ZIP files live under `madx-project-artifacts/<owner-hash>/<project-id>.zip`; the owner-scoped project record stores the private object reference. Downloads still require MADX authentication and an owner check; objects are not made public.
- Existing local temporary uploads and old database-backed project ZIPs are not migrated automatically when Firebase is enabled. Download them first if they matter.
- Firebase stores file bytes, but the project/task index and Firebase object reference remain in the application database. Set `DATABASE_URL` to a persistent PostgreSQL database if projects must remain listed and downloadable across Render restarts. Without a persistent database, the free-tier app's SQLite metadata can be lost when the container restarts even though an uploaded Firebase object remains.

## Fixing `Task pipeline failed: Auto must resolve...`

The previous task model list could treat the `MAD X Auto` UI row as a real provider route. In v18.1.0, the task selector filters that row out, only keeps configured/live routes selectable, and the backend resolves an explicit `auto` alias to one exact route before validating/starting the task. If no hosted route is configured, the server responds with a specific `no_auto_route_configured`/default-not-ready error and setup hint; no provider is secretly retried after a request failure.

For hosted free mode, configure a provider key with an eligible quota or set `MADX_DEFAULT_MODEL` to an exact configured route ID such as `Gemini API|<exact-model-id>`. The placeholder is illustrative; use an actual model ID returned by `/v1/catalog`. If using Ollama, `OLLAMA_BASE_URL` must point to a reachable server that already has the requested model installed. `127.0.0.1` on Render does not refer to your Android phone or PC.

## References

- Firebase Admin SDK setup: https://firebase.google.com/docs/admin/setup
- Firestore data writes: https://firebase.google.com/docs/firestore/manage-data/add-data
