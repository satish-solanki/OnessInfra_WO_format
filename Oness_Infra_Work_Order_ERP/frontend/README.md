# Frontend — Oness Infra Work Order ERP

The supplied HTML interface is in `index.html`.

## Run locally
1. Configure the Google OAuth and Apps Script environment variables listed in `backend/README.md`.
2. Start FastAPI from `backend/python` with `uvicorn app:app --reload`.
3. Open `http://127.0.0.1:8000`. Do not open the HTML directly or use a separate static frontend host; the UI and protected API are served from one origin.
4. Tailwind CSS, Font Awesome, Google Fonts, and Google sign-in load from CDNs, so an internet connection is needed.

## Connect to your Google Sheet
The frontend does not contain or call the Apps Script URL. FastAPI proxies Sheets requests after verifying the user's Google Workspace ID token. Set `APPS_SCRIPT_URL` and `APPS_SCRIPT_PROXY_KEY` only in the backend environment.

## Polished PDF downloads
Users must sign in with a verified Google Workspace account in the configured company domain. Both **Print / Save PDF** and **Submit to Log** use the same branded A4 PDF from the Python service in `backend/python`. The first opens it for printing or saving. Submitting uploads the exact generated file to Google Drive through Apps Script, saves its link in `WO_Log`, and offers that same PDF for download.

Deploy the UI and API together using the root `render.yaml` Blueprint. Do not deploy this frontend as an unprotected static site on a separate host.
