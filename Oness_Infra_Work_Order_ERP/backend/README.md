# Backend — Google Apps Script

`Code.gs` is the Google Apps Script data backend. It reads/writes the Google Sheets tabs `Vendors`, `Sites`, `WO_Log`, and `Terms`. The Python service generates the styled PDF and proxies authenticated access to Apps Script; on submission, Apps Script saves the same PDF to Drive and writes its link to `WO_Log`.

## Setup
1. Open the Google Sheet that should store the work orders.
2. Select **Extensions → Apps Script**.
3. Replace the editor contents with `Code.gs` (or copy its contents into the project).
4. Save, then run `setupSheetTemplates` once and authorize the requested Google permissions.
5. `WO_Log` uses these columns in order: `Timestamp / Date`, `Contractor Type`, `Contractor Name`, `Project Site`, `Work Order No`, `Work Type`, `Total Amount (₹)`, `PDF Drive Link`, `Scope of Work`, `Item Details (JSON)`, `Milestones (JSON)`, and `Status`.
6. In **Project Settings → Script Properties**, add `ERP_PROXY_KEY` with a randomly generated value. Generate one with `python -c "import secrets; print(secrets.token_urlsafe(48))"` and keep it private.
7. Contractor type is stored in column B. Status is `Submitted` unless a client sends a `status` value. Drive PDFs are shared with signed-in users in the Workspace domain.
8. Select **Deploy → Manage deployments → Edit** for the Web App, or create a deployment.
9. Set **Execute as** to your account. Set Web App access to **Anyone** because Render makes the request server-to-server; the script rejects calls without the private `ERP_PROXY_KEY`. Do not put this key in frontend files or GitHub.
10. Deploy and copy the Web App URL. Set `APPS_SCRIPT_URL` in Render to that URL. Redeploy Apps Script after making the proxy-key and Drive-sharing changes.

The deployed endpoints support `GET?action=getData`, `GET?action=getWorkOrder&woNumber=...`, and `POST` with `action=saveWorkOrder`. Items and milestones may be sent as JSON arrays or JSON-encoded strings; both are stored as JSON in `WO_Log`.

## Secure Render deployment from GitHub

The included `render.yaml` deploys one Render web service that serves the frontend and API from the same HTTPS origin. This keeps the Apps Script URL and proxy key out of browser code and avoids public cross-origin API access.

1. Push this project to a **private GitHub repository**. Review the repository for company data or secrets first; keep `.env` files and credentials out of Git.
2. In Google Cloud Console, configure OAuth consent for your Google Workspace organization and create a **Web application OAuth client ID**. Add the Render service URL (for example, `https://your-service.onrender.com`) as an authorized JavaScript origin. Use the OAuth **client ID**, not a client secret.
3. In Render, choose **New → Blueprint**, connect the private repo, and deploy `render.yaml`. Render prompts for the four values marked `sync: false`.
4. Set these Render environment values:
   - `GOOGLE_CLIENT_ID`: the Google OAuth web client ID.
   - `GOOGLE_ALLOWED_EMAIL_DOMAIN`: your Workspace domain, e.g. `company.com` (domain only).
   - `APPS_SCRIPT_URL`: the deployed Apps Script `/exec` URL.
   - `APPS_SCRIPT_PROXY_KEY`: the exact random value stored in Apps Script Script Property `ERP_PROXY_KEY`.
5. Confirm Google OAuth's authorized JavaScript origin is exactly your Render HTTPS origin. Save/redeploy in Render.
6. Open the Render URL. Sign in with a verified account in the configured Workspace domain. The backend verifies Google's token audience, signature, email verification, and hosted domain.

The app fails closed until all required environment values are configured. The Google client ID is public by design; `APPS_SCRIPT_URL` and `APPS_SCRIPT_PROXY_KEY` are server-only. Rotate the proxy key in both Render and Apps Script if it is exposed.

The Apps Script Web App must be deployed with access set to **Anyone** for the Render server-to-server call. The shared proxy key is checked in both Apps Script GET and POST handlers. Keep `ERP_PROXY_KEY` in Script Properties and do not share it. Drive PDFs use `DOMAIN_WITH_LINK`; verify your Workspace Drive-sharing policy supports domain-only access.

Local secure development: configure the same environment variables in your shell, run `uvicorn app:app --reload` from `backend\python`, then open `http://127.0.0.1:8000`. Do not open the frontend HTML directly from disk; same-origin serving is required for the protected API. Use the Render service's HTTPS origin in Google OAuth's authorized JavaScript origins.

## Python service and PDF generation

The frontend uses ReportLab to generate a polished, multi-page A4 PDF with the company logo, contractor/site details, scope, item and milestone tables, terms, signature lines, and page footer. Submitting a work order sends this PDF to Apps Script, which saves it to Drive and records the link in column H of `WO_Log`. The download popup downloads the same PDF file that was uploaded.

The supplied company logo is stored at `backend\python\company_logo.png`. Both the PDF and frontend header load this image from the same-origin service. For a different logo location, set `PDF_LOGO_PATH` to the image's absolute path before starting Uvicorn.

From PowerShell, run:

```powershell
cd backend\python
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
uvicorn app:app --reload
```

Both the **Print / Save PDF** and **Submit to Log** actions use the authenticated endpoint `/api/work-orders/pdf`. The service health check is `/health`. The service does not enable cross-origin access by default. If a separate development frontend is needed, set `CORS_ORIGINS` to its exact origin; do not use `*` or `null`.

To run tests, install `requirements-dev.txt`, then run `python -m pytest` from `backend\python`.
