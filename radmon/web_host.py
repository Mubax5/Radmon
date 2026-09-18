from __future__ import annotations

from ipaddress import ip_address
import logging
from pathlib import Path
import sys
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse, Response

from .config import Settings
from .grafana_tv import playlist_url

_HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}
_REMOTE_BLOCKED_GRAFANA_PREFIXES = (
    "login",
    "logout",
    "signup",
    "admin",
    "api/login",
    "api/admin",
)
_SPA_HEADERS = {
    "Cache-Control": "no-store, max-age=0",
    "Pragma": "no-cache",
}
LOG = logging.getLogger(__name__)


def monitoring_url(settings: Settings) -> str:
    """Return a same-origin kiosk URL; Grafana itself stays loopback-only."""
    return playlist_url("")


def bundled_web_dist() -> Path:
    if bool(getattr(sys, "frozen", False)):
        root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
        return root / "web"
    return Path(__file__).resolve().parents[1] / "web" / "dist"


def _is_loopback(request: Request) -> bool:
    host = request.client.host if request.client else ""
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return host.lower() == "localhost"


def _grafana_headers(request: Request, *, trusted_local: bool) -> dict[bytes, bytes]:
    headers: dict[bytes, bytes] = {}
    for key, value in request.headers.raw:
        lower = key.lower()
        name = lower.decode("ascii")
        if name in _HOP_BY_HOP or name == "content-length":
            continue
        if not trusted_local and name in {"authorization", "cookie"}:
            continue
        headers[lower] = value
    if b"host" in headers:
        headers[b"x-forwarded-host"] = headers[b"host"]
    headers[b"x-forwarded-proto"] = request.url.scheme.encode("ascii")
    if request.client:
        headers[b"x-forwarded-for"] = request.client.host.encode("ascii")
    return headers


def _public_location(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.hostname in {"127.0.0.1", "localhost", "::1"}:
        path = parsed.path or "/"
        return f"{path}?{parsed.query}" if parsed.query else path
    return value


def _spa_shell(index: Path) -> FileResponse:
    return FileResponse(index, headers=_SPA_HEADERS)


def _grafana_client(app: FastAPI, *, transport: httpx.AsyncBaseTransport | None) -> httpx.AsyncClient:
    client = getattr(app.state, "radmon_grafana_client", None)
    if client is None or client.is_closed:
        client = httpx.AsyncClient(
            transport=transport,
            timeout=httpx.Timeout(connect=5.0, read=30.0, write=30.0, pool=5.0),
            limits=httpx.Limits(max_connections=32, max_keepalive_connections=16, keepalive_expiry=30.0),
            follow_redirects=False,
        )
        app.state.radmon_grafana_client = client
    return client


def _upstream_error_detail(exc: Exception) -> str:
    try:
        return str(exc).replace("\r", " ").replace("\n", " ")[:500]
    except Exception:
        return "unprintable exception"


def attach_web_routes(
    app: FastAPI,
    *,
    settings: Settings,
    web_dist: Path | None = None,
    grafana_transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    """Attach BRIN monitoring gateway and authenticated app static shell."""
    dist = Path(web_dist) if web_dist is not None else bundled_web_dist()

    @app.on_event("startup")
    async def start_grafana_client() -> None:
        _grafana_client(app, transport=grafana_transport)

    @app.on_event("shutdown")
    async def stop_grafana_client() -> None:
        client = getattr(app.state, "radmon_grafana_client", None)
        if client is not None and not client.is_closed:
            await client.aclose()

    @app.get("/", include_in_schema=False)
    def monitoring_landing():
        return RedirectResponse(monitoring_url(settings), status_code=307)

    @app.get("/app", include_in_schema=False)
    @app.get("/app/{asset_path:path}", include_in_schema=False)
    def web_application(asset_path: str = ""):
        index = dist / "index.html"
        if not index.is_file():
            raise HTTPException(status_code=503, detail="RadMon web interface is not installed")

        requested = (dist / asset_path).resolve() if asset_path else index.resolve()
        try:
            requested.relative_to(dist.resolve())
        except ValueError:
            raise HTTPException(status_code=404, detail="resource not found")

        if asset_path and requested.is_file():
            if requested.name.casefold() == "index.html":
                return _spa_shell(requested)
            return FileResponse(requested)
        return _spa_shell(index)

    @app.api_route(
        "/{grafana_path:path}",
        methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        include_in_schema=False,
    )
    async def grafana_gateway(grafana_path: str, request: Request):
        path = grafana_path.lstrip("/")
        normalized_path = path.casefold()
        trusted_local = _is_loopback(request)
        if not trusted_local and any(
            normalized_path == prefix or normalized_path.startswith(prefix + "/")
            for prefix in _REMOTE_BLOCKED_GRAFANA_PREFIXES
        ):
            raise HTTPException(status_code=404, detail="resource not found")

        upstream_url = f"http://127.0.0.1:{int(settings.grafana_fallback_port)}/{path}"
        if request.url.query:
            upstream_url += f"?{request.url.query}"

        body = await request.body()
        try:
            upstream = await _grafana_client(app, transport=grafana_transport).request(
                request.method,
                upstream_url,
                headers=_grafana_headers(request, trusted_local=trusted_local),
                content=body,
            )
        except httpx.HTTPError as exc:
            LOG.warning(
                "Grafana upstream request failed method=%s path=/%s error=%s: %s",
                request.method,
                path,
                type(exc).__name__,
                _upstream_error_detail(exc),
            )
            raise HTTPException(status_code=502, detail="Grafana monitoring is unavailable") from exc

        response_headers: dict[str, str] = {}
        for key, value in upstream.headers.items():
            lower = key.lower()
            if lower in _HOP_BY_HOP or lower in {"content-length", "content-encoding"}:
                continue
            if not trusted_local and lower == "set-cookie":
                continue
            response_headers[key] = value

        if "location" in response_headers:
            response_headers["location"] = _public_location(response_headers["location"])

        return Response(
            content=upstream.content,
            status_code=upstream.status_code,
            headers=response_headers,
            media_type=None,
        )

    return app
