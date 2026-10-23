import json
import re

from fastapi.testclient import TestClient

import app as app_module
from app import WorkOrderRequest, app, build_work_order_pdf, create_work_order_pdf


def test_pdf_endpoint_response_has_download_headers_and_pdf_bytes():
    work_order = WorkOrderRequest(
        woNumber="RESI/OGR/PO1/20261014",
        woDate="14/10/2026",
        contractor="Shiv Buildcon & Infra",
        site="Oness Grandeur Residency",
        amount=5000,
        items=json.dumps([
            {
                "area": "Foundation work",
                "tech": "M25 concrete",
                "measurement": 10,
                "unit": "cum",
                "rate": 500,
            }
        ]),
        milestones=json.dumps([{"desc": "Foundation completion", "pct": 100}]),
    )

    response = create_work_order_pdf(work_order)

    assert response.media_type == "application/pdf"
    assert response.headers["Content-Disposition"] == (
        'attachment; filename="RESI_OGR_PO1_20261014.pdf"'
    )
    assert response.body.startswith(b"%PDF-")
    assert b"/Subtype /Image" in response.body


def test_long_work_order_spans_multiple_pages():
    work_order = WorkOrderRequest(
        woNumber="LONG-001",
        contractor="Example Contractor",
        site="Example Site",
        amount=8000,
        items=[
            {
                "area": f"Work item {index}",
                "tech": "Construction specification " * 4,
                "measurement": 1,
                "unit": "lot",
                "rate": 100,
            }
            for index in range(80)
        ],
    )

    pdf = build_work_order_pdf(work_order)

    assert len(re.findall(rb"/Type\s*/Page\b", pdf)) > 1


def test_protected_routes_require_company_google_sign_in(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "company-client-id")
    monkeypatch.setenv("GOOGLE_ALLOWED_EMAIL_DOMAIN", "company.example")
    monkeypatch.setenv("APPS_SCRIPT_URL", "https://script.google.com/macros/s/test/exec")
    monkeypatch.setenv("APPS_SCRIPT_PROXY_KEY", "test-proxy-secret")
    client = TestClient(app)

    assert client.get("/api/sheets/data").status_code == 401
    assert client.get("/api/sheets/work-orders", params={"woNumber": "WO/123"}).status_code == 401
    assert client.post("/api/work-orders/pdf", json={"woNumber": "WO-123"}).status_code == 401
    assert client.post("/api/sheets/work-orders", data={"action": "saveWorkOrder"}).status_code == 401


def test_unconfigured_service_fails_closed_and_does_not_publish_secrets(monkeypatch):
    for key in (
        "GOOGLE_CLIENT_ID",
        "GOOGLE_ALLOWED_EMAIL_DOMAIN",
        "APPS_SCRIPT_URL",
        "APPS_SCRIPT_PROXY_KEY",
    ):
        monkeypatch.delenv(key, raising=False)
    client = TestClient(app)

    config = client.get("/api/config")
    assert config.status_code == 200
    assert config.json() == {"configured": False, "googleClientId": None}
    assert client.get("/api/sheets/data").status_code == 503


def test_company_user_can_search_work_order_through_authenticated_proxy(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "company-client-id")
    monkeypatch.setenv("GOOGLE_ALLOWED_EMAIL_DOMAIN", "company.example")
    monkeypatch.setenv("APPS_SCRIPT_URL", "https://script.google.com/macros/s/test/exec")
    monkeypatch.setenv("APPS_SCRIPT_PROXY_KEY", "test-proxy-secret")
    monkeypatch.setattr(
        app_module.id_token,
        "verify_oauth2_token",
        lambda token, request, audience: {
            "email": "worker@company.example",
            "email_verified": True,
            "hd": "company.example",
        },
    )
    forwarded: dict[str, str] = {}

    async def fake_apps_script_request(params=None, content=None):
        forwarded.update(params or {})
        return {"success": True, "record": {"woNumber": forwarded["woNumber"]}}

    monkeypatch.setattr(app_module, "_apps_script_request", fake_apps_script_request)
    response = TestClient(app).get(
        "/api/sheets/work-orders",
        params={"woNumber": "WO/123"},
        headers={"Authorization": "Bearer valid-token"},
    )

    assert response.status_code == 200
    assert response.json() == {"success": True, "record": {"woNumber": "WO/123"}}
    assert forwarded == {"action": "getWorkOrder", "woNumber": "WO/123"}


def test_google_user_from_another_domain_is_rejected(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "company-client-id")
    monkeypatch.setenv("GOOGLE_ALLOWED_EMAIL_DOMAIN", "company.example")
    monkeypatch.setenv("APPS_SCRIPT_URL", "https://script.google.com/macros/s/test/exec")
    monkeypatch.setenv("APPS_SCRIPT_PROXY_KEY", "test-proxy-secret")
    monkeypatch.setattr(
        app_module.id_token,
        "verify_oauth2_token",
        lambda token, request, audience: {
            "email": "worker@other.example",
            "email_verified": True,
            "hd": "other.example",
        },
    )

    response = TestClient(app).get(
        "/api/sheets/data",
        headers={"Authorization": "Bearer valid-token"},
    )

    assert response.status_code == 403


def test_public_health_and_frontend_routes_block_legacy_html():
    client = TestClient(app)

    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/").status_code == 200
    assert client.get("/index_Old.html").status_code == 404
