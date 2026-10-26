# Optional React + TypeScript (TSX) landing source

The primary deployed landing page is `static/landing.html` because the active application is a Python/FastAPI deployment and can serve it without a Node build step. `src/main.tsx` is the editable React/TypeScript companion source.

## Local build

```bash
cd frontend
npm install
npm run check
npm run build
```

The compiled preview is written to `static/landing-tsx/`. It is a separate preview build; it does not replace the FastAPI-served `/` route automatically.

**Security note:** TSX, minification and compiled JavaScript do not hide frontend logic or secrets. Treat every browser-delivered file as public. Keep model/provider keys on the server and enforce authentication, authorization, rate limits and storage ownership in the backend.
