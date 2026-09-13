from __future__ import annotations

from pathlib import Path
import sys

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, RedirectResponse

from .config import Settings
from .grafana_tv import PLAYLIST_UID, playlist_url


def monitoring_url(settings: Settings) -> str:
    """Return the BRIN-LAN Grafana kiosk URL used as the anonymous landing page."""
    host = (settings.central_host or "127.0.0.1").strip()
    base = f"http://{host}:{int(settings.grafana_fallback_port)}"
    return playlist_url(base)


def bundled_web_dist() -> Path:
    if bool(getattr(sys, "frozen", False)):
        root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
        return root / "web"
    return Path(__file__).resolve().parents[1] / "web" / "dist"


def attach_web_routes(
    app: FastAPI,
    *,
    settings: Settings,
    web_dist: Path | None = None,
) -> FastAPI:
    """Attach the anonymous Grafana landing and authenticated-app static shell."""
    dist = Path(web_dist) if web_dist is not None else bundled_web_dist()

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
            return FileResponse(requested)
        return FileResponse(index)

    return app
