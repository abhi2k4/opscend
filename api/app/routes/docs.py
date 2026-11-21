"""API reference: Swagger UI in Opscend's own skin, served at /api/docs.

FastAPI's stock page is generated, then the theme stylesheet, fonts and a small
header are added to it. The assets live in app/static so the page looks the same
whether it is opened through the web app's proxy or straight from the API port.
"""

import hashlib
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse, Response

router = APIRouter(include_in_schema=False)

STATIC = Path(__file__).resolve().parents[1] / "static"
ASSETS = {
    "theme.css": ("swagger-theme.css", "text/css"),
    "icon.svg": ("icon.svg", "image/svg+xml"),
    "sherlog.svg": ("sherlog.svg", "image/svg+xml"),
}

# Cache-busting tag, so a restyled theme is picked up without a hard refresh.
THEME_VERSION = hashlib.sha1((STATIC / "swagger-theme.css").read_bytes()).hexdigest()[:10]  # noqa: S324

HEAD = f"""
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
    <link rel="stylesheet" href="/api/docs/assets/theme.css?v={THEME_VERSION}">
    <meta name="theme-color" content="#0f0f0e">
"""  # noqa: E501
HEADER = """
    <header class="ops-bar">
      <a class="ops-brand" href="/">
        <img src="/api/docs/assets/icon.svg" width="20" height="20" alt="">
        opscend <span>/ API reference</span>
      </a>
      <a class="ops-console" href="/console">Console &rarr;</a>
    </header>
    <img class="ops-sherlog" src="/api/docs/assets/sherlog.svg" alt="Sherlog, the Opscend mascot">
"""

SWAGGER_UI = {
    "docExpansion": "list",
    "filter": True,
    "tryItOutEnabled": True,
    "displayRequestDuration": True,
    "defaultModelsExpandDepth": 0,
    "syntaxHighlight": {"theme": "nord"},
}


@router.get("/docs")
async def api_reference(request: Request) -> HTMLResponse:
    app = request.app
    page = get_swagger_ui_html(
        openapi_url=app.openapi_url,
        title=f"{app.title} reference",
        swagger_favicon_url="/api/docs/assets/icon.svg",
        swagger_ui_parameters=SWAGGER_UI,
    ).body.decode()
    page = page.replace("</head>", f"{HEAD}</head>", 1).replace("<body>", f"<body>{HEADER}", 1)
    return HTMLResponse(page)


@router.get("/docs/assets/{name}")
async def docs_asset(name: str) -> Response:
    if name not in ASSETS:
        raise HTTPException(404, "Not found")
    filename, media_type = ASSETS[name]
    return Response(
        (STATIC / filename).read_bytes(),
        media_type=media_type,
        headers={"Cache-Control": "public, max-age=3600"},
    )
