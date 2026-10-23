from __future__ import annotations

import json
import os
import re
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode
from xml.sax.saxutils import escape

import google.auth.exceptions
import httpx
import requests
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2 import id_token
from pydantic import BaseModel, ConfigDict, Field, field_validator
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    KeepTogether,
    LongTable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

NAVY = colors.HexColor("#1a2a3a")
GOLD = colors.HexColor("#c5a059")
PALE = colors.HexColor("#f1f5f9")
INK = colors.HexColor("#1e293b")
MUTED = colors.HexColor("#64748b")
GRID = colors.HexColor("#cbd5e1")
LOGO_PATH = Path(os.getenv("PDF_LOGO_PATH", Path(__file__).with_name("company_logo.png"))).resolve()
FRONTEND_PATH = Path(__file__).resolve().parents[2] / "frontend"
MAX_REQUEST_BYTES = 20 * 1024 * 1024
bearer_scheme = HTTPBearer(auto_error=False)


def _required_environment() -> dict[str, str]:
    return {
        "google_client_id": os.getenv("GOOGLE_CLIENT_ID", "").strip(),
        "allowed_email_domain": os.getenv("GOOGLE_ALLOWED_EMAIL_DOMAIN", "").strip().lower().lstrip("@"),
        "apps_script_url": os.getenv("APPS_SCRIPT_URL", "").strip(),
        "apps_script_proxy_key": os.getenv("APPS_SCRIPT_PROXY_KEY", "").strip(),
    }


def _validate_required_environment() -> dict[str, str]:
    configuration = _required_environment()
    missing = [name for name, value in configuration.items() if not value]
    if missing:
        raise HTTPException(
            status_code=503,
            detail="The service is not configured. An administrator must set the required deployment environment variables.",
        )
    if not configuration["apps_script_url"].startswith("https://script.google.com/macros/s/"):
        raise HTTPException(status_code=503, detail="The Apps Script endpoint configuration is invalid.")
    return configuration


async def require_company_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict[str, str]:
    configuration = _validate_required_environment()
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Sign in with your company Google account.")
    try:
        claims = id_token.verify_oauth2_token(
            credentials.credentials,
            GoogleAuthRequest(),
            audience=configuration["google_client_id"],
        )
    except (ValueError, google.auth.exceptions.GoogleAuthError, requests.exceptions.RequestException) as exc:
        raise HTTPException(status_code=401, detail="The Google sign-in token is invalid or expired.") from exc

    email = str(claims.get("email", "")).strip().lower()
    hosted_domain = str(claims.get("hd", "")).strip().lower()
    allowed_domain = configuration["allowed_email_domain"]
    if (
        claims.get("email_verified") is not True
        or not email.endswith(f"@{allowed_domain}")
        or hosted_domain != allowed_domain
    ):
        raise HTTPException(status_code=403, detail="This Google account is not in the allowed company domain.")
    return {"email": email}


async def _apps_script_request(
    params: dict[str, str] | None = None,
    content: bytes | None = None,
) -> dict[str, Any]:
    configuration = _validate_required_environment()
    fields = [
        (key, value)
        for key, value in parse_qsl(content.decode("utf-8"), keep_blank_values=True)
        if key != "proxyKey"
    ] if content else []
    existing_keys = {key for key, _ in fields}
    fields.extend((key, value) for key, value in (params or {}).items() if key not in existing_keys)
    fields.append(("proxyKey", configuration["apps_script_proxy_key"]))
    form_body = urlencode(fields).encode("utf-8")
    try:
        async with httpx.AsyncClient(timeout=45, follow_redirects=True) as client:
            response = await client.post(
                configuration["apps_script_url"],
                content=form_body,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail="Could not reach the Google Apps Script service.") from exc
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail="Google Apps Script rejected the work-order request.")
    try:
        result = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="Google Apps Script returned an invalid response.") from exc
    if not isinstance(result, dict):
        raise HTTPException(status_code=502, detail="Google Apps Script returned an invalid response.")
    return result


def _parse_rows(value: Any) -> list[dict[str, Any]]:
    if value in (None, ""):
        return []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError("Items and milestones must be valid JSON arrays.") from exc
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise ValueError("Items and milestones must be arrays of objects.")
    return value


class WorkOrderRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    woNumber: str = Field(default="WORK-ORDER", max_length=120)
    woDate: str = Field(default="", max_length=120)
    contractor: str = Field(default="", max_length=500)
    contractorType: str = Field(default="", max_length=200)
    contractorAddress: str = Field(default="", max_length=2000)
    aadhaar: str = Field(default="", max_length=100)
    pan: str = Field(default="", max_length=100)
    gst: str = Field(default="", max_length=100)
    site: str = Field(default="", max_length=500)
    siteAddress: str = Field(default="", max_length=2000)
    siteContact: str = Field(default="", max_length=300)
    siteMobile: str = Field(default="", max_length=100)
    workType: str = Field(default="", max_length=200)
    amount: float = Field(default=0, ge=0, le=1_000_000_000_000)
    scopeOfWork: str = Field(default="", max_length=20_000)
    basicTerms: str = Field(default="", max_length=20_000)
    paymentTerms: str = Field(default="", max_length=20_000)
    specificTerms: str = Field(default="", max_length=20_000)
    status: str = Field(default="Submitted", max_length=100)
    items: list[dict[str, Any]] = Field(default_factory=list, max_length=250)
    milestones: list[dict[str, Any]] = Field(default_factory=list, max_length=100)

    @field_validator("items", "milestones", mode="before")
    @classmethod
    def parse_json_rows(cls, value: Any) -> list[dict[str, Any]]:
        return _parse_rows(value)


def _register_unicode_font() -> tuple[str, str]:
    configured_path = os.getenv("PDF_FONT_PATH")
    regular_candidates = [
        Path(configured_path) if configured_path else None,
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"),
    ]
    bold_candidates = [
        Path("C:/Windows/Fonts/arialbd.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"),
    ]
    regular = next((path for path in regular_candidates if path and path.is_file()), None)
    bold = next((path for path in bold_candidates if path.is_file()), regular)
    registered_fonts = pdfmetrics.getRegisteredFontNames()
    if regular is None:
        return "Helvetica", "Helvetica-Bold"
    if "OnessSans" not in registered_fonts:
        pdfmetrics.registerFont(TTFont("OnessSans", str(regular)))
    if bold and "OnessSans-Bold" not in registered_fonts:
        pdfmetrics.registerFont(TTFont("OnessSans-Bold", str(bold)))
    elif "OnessSans-Bold" not in registered_fonts:
        pdfmetrics.registerFont(TTFont("OnessSans-Bold", str(regular)))
    return "OnessSans", "OnessSans-Bold"


def _text(value: Any) -> str:
    return escape(str(value if value is not None else "")).replace("\n", "<br/>")


def _paragraph(value: Any, style: ParagraphStyle) -> Paragraph:
    return Paragraph(_text(value).replace("\r", ""), style)


def _money(value: Any) -> str:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        number = 0
    whole, fraction = f"{number:.2f}".split(".")
    if len(whole) > 3:
        last_three = whole[-3:]
        rest = whole[:-3]
        groups = []
        while rest:
            groups.insert(0, rest[-2:])
            rest = rest[:-2]
        whole = ",".join(groups + [last_three])
    return f"INR {whole}.{fraction}"


def _format_number(value: Any) -> str:
    try:
        return f"{float(value or 0):,.2f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return str(value or "")


def _safe_filename(value: str) -> str:
    cleaned = re.sub(r'[^A-Za-z0-9._-]+', "_", value).strip("._")
    return (cleaned or "WORK-ORDER")[:120]


def build_work_order_pdf(work_order: WorkOrderRequest) -> bytes:
    regular_font, bold_font = _register_unicode_font()
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="WOBody", parent=styles["BodyText"], fontName=regular_font,
        fontSize=8, leading=11, textColor=INK, spaceAfter=0,
    ))
    styles.add(ParagraphStyle(
        name="WOBodySmall", parent=styles["WOBody"], fontSize=7, leading=9,
    ))
    styles.add(ParagraphStyle(
        name="WOHeading", parent=styles["Heading2"], fontName=bold_font,
        fontSize=9, leading=12, textColor=NAVY, spaceBefore=8, spaceAfter=5,
    ))
    styles.add(ParagraphStyle(
        name="WOTableHeader", parent=styles["WOBodySmall"], fontName=bold_font,
        textColor=colors.white, alignment=TA_LEFT,
    ))
    styles.add(ParagraphStyle(
        name="WORight", parent=styles["WOBody"], alignment=TA_RIGHT,
    ))
    styles.add(ParagraphStyle(
        name="WOCenter", parent=styles["WOBody"], alignment=TA_CENTER,
    ))

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=15 * mm,
        leftMargin=15 * mm,
        topMargin=38 * mm,
        bottomMargin=20 * mm,
        title=f"Work Order {work_order.woNumber}",
        author="Oness Infra Private Limited",
    )

    def draw_page(canvas: Any, document: Any) -> None:
        canvas.saveState()
        width, height = A4
        canvas.setFillColor(NAVY)
        canvas.rect(0, height - 30 * mm, width, 30 * mm, fill=1, stroke=0)
        if LOGO_PATH.is_file():
            if LOGO_PATH.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
                raise ValueError("Company logo must be a PNG or JPEG image.")
            canvas.setFillColor(colors.white)
            canvas.rect(15 * mm, height - 25 * mm, 20 * mm, 20 * mm, fill=1, stroke=0)
            logo_image = ImageReader(str(LOGO_PATH))
            canvas.drawImage(
                logo_image,
                15 * mm,
                height - 25 * mm,
                width=20 * mm,
                height=20 * mm,
                preserveAspectRatio=True,
                anchor="c",
                mask="auto",
            )
        canvas.setFillColor(colors.white)
        canvas.setFont(bold_font, 13)
        canvas.drawString(41 * mm, height - 16 * mm, "ONESS INFRA PRIVATE LIMITED")
        canvas.drawRightString(width - 15 * mm, height - 12 * mm, "CIN: U45201MP2022PTC062145")
        canvas.setStrokeColor(GOLD)
        canvas.setLineWidth(1.2)
        canvas.line(15 * mm, 14 * mm, width - 15 * mm, 14 * mm)
        canvas.setFillColor(MUTED)
        canvas.setFont(regular_font, 7)
        canvas.drawString(15 * mm, 9 * mm, "ONESS INFRA PRIVATE LIMITED  |  WORK ORDER")
        canvas.drawRightString(width - 15 * mm, 9 * mm, f"Page {document.page}")
        canvas.restoreState()

    story: list[Any] = [
        Paragraph("WORK ORDER", ParagraphStyle(
            name="WOTitle", fontName=bold_font, fontSize=17, leading=21,
            textColor=NAVY, alignment=TA_CENTER, spaceAfter=3,
        )),
        Paragraph(f"Work Order No. {_text(work_order.woNumber)}", ParagraphStyle(
            name="WONumber", fontName=bold_font, fontSize=10, leading=14,
            textColor=GOLD, alignment=TA_CENTER, spaceAfter=9,
        )),
    ]

    details = [
        [_paragraph("CONTRACTOR", styles["WOTableHeader"]),
         _paragraph("PROJECT SITE", styles["WOTableHeader"])],
        [Paragraph(f"<b>{_text(work_order.contractor)}</b><br/>"
                   f"{_text(work_order.contractorType)}<br/>"
                   f"{_text(work_order.contractorAddress)}<br/>"
                   f"PAN: {_text(work_order.pan)}  |  GST: {_text(work_order.gst)}",
                   styles["WOBody"]),
         Paragraph(f"<b>{_text(work_order.site)}</b><br/>"
                   f"{_text(work_order.siteAddress)}<br/>"
                   f"Contact: {_text(work_order.siteContact)}"
                   f"  |  Mobile: {_text(work_order.siteMobile)}",
                   styles["WOBody"])],
        [Paragraph("<b>Work type:</b> " + _text(work_order.workType), styles["WOBody"]),
         Paragraph("<b>Date:</b> " + _text(work_order.woDate), styles["WOBody"])],
    ]
    detail_table = Table(details, colWidths=[90 * mm, 90 * mm], repeatRows=1)
    detail_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("BACKGROUND", (0, 1), (-1, -1), PALE),
        ("GRID", (0, 0), (-1, -1), 0.5, GRID),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("SPAN", (0, 2), (0, 2)),
    ]))
    story.extend([detail_table, Spacer(1, 5 * mm)])

    story.append(Paragraph("SCOPE OF WORK", styles["WOHeading"]))
    story.append(_paragraph(work_order.scopeOfWork or "—", styles["WOBody"]))

    story.append(Paragraph("SCHEDULE OF WORK & RATES", styles["WOHeading"]))
    item_rows: list[list[Any]] = [[
        _paragraph(label, styles["WOTableHeader"])
        for label in ("#", "Description", "Specification", "Qty", "Unit", "Rate (INR)", "Amount (INR)")
    ]]
    for index, item in enumerate(work_order.items, start=1):
        quantity = item.get("measurement", item.get("quantity", ""))
        rate = item.get("rate", 0)
        try:
            line_amount = float(quantity or 0) * float(rate or 0)
        except (TypeError, ValueError):
            line_amount = 0
        item_rows.append([
            _paragraph(index, styles["WOCenter"]),
            _paragraph(item.get("area", item.get("description", "")), styles["WOBodySmall"]),
            _paragraph(item.get("tech", item.get("specification", "")), styles["WOBodySmall"]),
            _paragraph(_format_number(quantity), styles["WORight"]),
            _paragraph(item.get("unit", ""), styles["WOCenter"]),
            _paragraph(_format_number(rate), styles["WORight"]),
            _paragraph(_format_number(line_amount), styles["WORight"]),
        ])
    if len(item_rows) == 1:
        item_rows.append([_paragraph("No work items provided.", styles["WOBody"])] + [""] * 6)
    item_table = LongTable(
        item_rows,
        colWidths=[8 * mm, 36 * mm, 42 * mm, 16 * mm, 14 * mm, 31 * mm, 33 * mm],
        repeatRows=1,
    )
    item_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("GRID", (0, 0), (-1, -1), 0.45, GRID),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, PALE]),
    ]))
    story.extend([item_table, Spacer(1, 2 * mm)])
    total_table = Table(
        [[_paragraph("TOTAL WORK ORDER VALUE", styles["WOBody"]),
          _paragraph(_money(work_order.amount), styles["WORight"])]],
        colWidths=[132 * mm, 48 * mm],
    )
    total_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PALE),
        ("TEXTCOLOR", (0, 0), (-1, -1), NAVY),
        ("FONTNAME", (0, 0), (-1, -1), bold_font),
        ("BOX", (0, 0), (-1, -1), 0.7, GOLD),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    story.extend([total_table, Spacer(1, 2 * mm)])

    if work_order.milestones:
        story.append(Paragraph("PAYMENT MILESTONES", styles["WOHeading"]))
        milestone_rows: list[list[Any]] = [[
            _paragraph(label, styles["WOTableHeader"])
            for label in ("Milestone", "Basis", "Share", "Amount (INR)")
        ]]
        for milestone in work_order.milestones:
            try:
                milestone_amount = work_order.amount * float(milestone.get("pct", 0) or 0) / 100
            except (TypeError, ValueError):
                milestone_amount = 0
            milestone_rows.append([
                _paragraph(milestone.get("desc", ""), styles["WOBody"]),
                _paragraph(milestone.get("type", ""), styles["WOBody"]),
                _paragraph(f'{_format_number(milestone.get("pct", 0))}%', styles["WORight"]),
                _paragraph(_format_number(milestone_amount), styles["WORight"]),
            ])
        milestone_table = LongTable(milestone_rows, colWidths=[76 * mm, 35 * mm, 25 * mm, 44 * mm], repeatRows=1)
        milestone_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), NAVY),
            ("GRID", (0, 0), (-1, -1), 0.45, GRID),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, PALE]),
        ]))
        story.append(milestone_table)

    for heading, content in (
        ("BASIC TERMS & CONDITIONS", work_order.basicTerms),
        ("PAYMENT TERMS & CONDITIONS", work_order.paymentTerms),
        ("SPECIFIC TERMS & CONDITIONS", work_order.specificTerms),
    ):
        if content.strip():
            story.extend([Paragraph(heading, styles["WOHeading"]), _paragraph(content, styles["WOBody"])])

    story.extend([
        Spacer(1, 10 * mm),
        KeepTogether([
            Paragraph("AUTHORIZED SIGNATURES", styles["WOHeading"]),
            Table(
                [[_paragraph("For Oness Infra Private Limited", styles["WOCenter"]),
                  _paragraph("Accepted by Contractor", styles["WOCenter"])],
                 ["", ""]],
                colWidths=[90 * mm, 90 * mm],
                style=TableStyle([
                    ("LINEABOVE", (0, 1), (-1, 1), 0.7, GRID),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("TOPPADDING", (0, 1), (-1, 1), 14 * mm),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]),
            ),
        ]),
    ])

    doc.build(story, onFirstPage=draw_page, onLaterPages=draw_page)
    return buffer.getvalue()


app = FastAPI(
    title="Oness Infra Work Order Service",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
allowed_origins = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", "").split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
    allow_credentials=False,
)


@app.middleware("http")
async def apply_security_headers_and_request_limit(request: Request, call_next: Any) -> Response:
    if request.url.path.lower() == "/index_old.html" or request.url.path.lower().endswith("_old.html"):
        return JSONResponse(status_code=404, content={"detail": "Not found."})
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_REQUEST_BYTES:
                return JSONResponse(status_code=413, content={"detail": "Request is too large."})
        except ValueError:
            return JSONResponse(status_code=400, content={"detail": "Invalid Content-Length header."})
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if request.headers.get("x-forwarded-proto", request.url.scheme) == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/config")
def public_configuration() -> dict[str, Any]:
    configuration = _required_environment()
    return {
        "configured": all(configuration.values()),
        "googleClientId": configuration["google_client_id"] or None,
    }


@app.post("/api/session")
async def verify_company_session(user: dict[str, str] = Depends(require_company_user)) -> dict[str, str]:
    return user


@app.get("/api/sheets/data")
async def get_sheet_data(_: dict[str, str] = Depends(require_company_user)) -> dict[str, Any]:
    return await _apps_script_request({"action": "getData"})


@app.get("/api/sheets/work-orders")
async def get_sheet_work_order(
    wo_number: str = Query(..., alias="woNumber", max_length=120),
    _: dict[str, str] = Depends(require_company_user),
) -> dict[str, Any]:
    return await _apps_script_request({"action": "getWorkOrder", "woNumber": wo_number})


@app.post("/api/sheets/work-orders")
async def save_sheet_work_order(
    request: Request,
    _: dict[str, str] = Depends(require_company_user),
) -> dict[str, Any]:
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/x-www-form-urlencoded":
        raise HTTPException(status_code=415, detail="Work orders must be submitted as form data.")
    body = await request.body()
    if len(body) > MAX_REQUEST_BYTES:
        raise HTTPException(status_code=413, detail="Work order PDF is too large.")
    return await _apps_script_request(content=body)


@app.get("/assets/company-logo")
def get_company_logo() -> FileResponse:
    if not LOGO_PATH.is_file():
        raise HTTPException(status_code=404, detail="Company logo has not been configured.")
    media_type = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}.get(
        LOGO_PATH.suffix.lower()
    )
    if media_type is None:
        raise HTTPException(status_code=415, detail="Company logo must be a PNG or JPEG image.")
    return FileResponse(LOGO_PATH, media_type=media_type)


@app.post("/api/work-orders/pdf")
def create_work_order_pdf(
    work_order: WorkOrderRequest,
    _: dict[str, str] = Depends(require_company_user),
) -> Response:
    pdf = build_work_order_pdf(work_order)
    filename = _safe_filename(work_order.woNumber) + ".pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


app.mount("/", StaticFiles(directory=FRONTEND_PATH, html=True), name="frontend")
