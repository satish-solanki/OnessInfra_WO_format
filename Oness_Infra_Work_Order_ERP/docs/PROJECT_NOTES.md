# Project notes

## Technology
- Frontend: HTML, CSS, JavaScript, Tailwind CSS CDN, Font Awesome CDN
- Backend: Python FastAPI (`backend/python/app.py`) with Google Apps Script (`Code.gs`) as the Sheets/Drive integration
- Data store: Google Sheets
- PDF storage: Google Drive
- PDF generation: Python FastAPI + ReportLab
- Authentication: Google Identity Services ID tokens restricted to one Google Workspace domain
- Hosting: same-origin Render Blueprint from a private GitHub repository

## Expected sheet tabs
- `Vendors`
- `Sites`
- `WO_Log`
- `Terms`

## Protected backend endpoints
- `POST /api/session` — verifies a Google Workspace ID token.
- `GET /api/sheets/data` — loads vendors, sites, work-order log, and terms through the server-side Apps Script proxy.
- `GET /api/sheets/work-orders?woNumber=...` — searches for a work order through the proxy.
- `POST /api/sheets/work-orders` — saves/updates a work order and supplied PDF to Drive, then records the Drive link in `WO_Log`.
- `POST /api/work-orders/pdf` — returns the branded PDF.
- `GET /health` — Render health check.

## Python service
- Work-order storage remains in Google Sheets via Apps Script; the same generated PDF is saved to Drive and downloaded by the browser.
- Sheet API requests are proxied by FastAPI and protected by verified company Google sign-in plus a server-side shared key checked by Apps Script.
