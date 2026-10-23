# Oness Infra — Work Order ERP

A VS Code project organized into a frontend and backend from the two code files supplied.

## Folder structure

```text
Oness_Infra_Work_Order_ERP/
├── frontend/
│   ├── index.html
│   └── README.md
├── backend/
│   ├── Code.gs
│   ├── README.md
│   └── python/
│       ├── app.py
│       ├── requirements.txt
│       ├── requirements-dev.txt
│       └── test_app.py
├── docs/
│   └── PROJECT_NOTES.md
├── render.yaml
├── .gitignore
└── README.md
```

## Quick start
- **Local preview:** start the FastAPI service from `backend/python`; it serves the app and PDF API together. Local use also requires the Google OAuth and Apps Script environment variables described in `backend/README.md`.
- **Live deployment:** connect the private GitHub repository to Render using the included `render.yaml`, then set the required secrets and company-domain settings in Render.
- **Data and PDFs:** Apps Script writes work orders to Sheets and saves the same generated PDF to Drive.
- **Google Sheets:** the backend expects the tabs `Vendors`, `Sites`, `WO_Log`, and `Terms`. Run `setupSheetTemplates` once from Apps Script to create missing tabs/headers.

## Important
- Google sign-in is restricted to the configured Google Workspace domain; all work-order and PDF API routes require a verified Google ID token.
- Apps Script access is proxied through the authenticated Python service. Its URL and shared proxy key are server-side environment values, never frontend code.
- Drive PDFs are shared with signed-in members of the Workspace domain, not anyone with the link.
- Do not commit Render secrets, OAuth client secrets, or `.env` files to GitHub.
- Before deployment, update and redeploy `backend/Code.gs`, add its matching `ERP_PROXY_KEY` Script Property, and configure the required Render environment variables as documented in `backend/README.md`.
- The Apps Script code had a variable-name typo in work-order lookup (`sheet` instead of `logSheet`); that typo is corrected in this packaged copy.
