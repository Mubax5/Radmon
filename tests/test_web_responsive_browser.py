from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import shutil
import threading
from urllib.parse import urlparse

import pytest


ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "web" / "dist"


def _station(serid: int, name: str, location: str, status: str, doserate: float):
    return {
        "serid": serid,
        "name": name,
        "location": location,
        "warnlevel": 20.0,
        "alarmlevel": 25.0,
        "unit": "uSv/h",
        "status": status,
        "doserate": doserate,
        "dtom": datetime.now(timezone.utc).isoformat(),
    }


STATIONS = [
    _station(3801, "Kolam Reaktor", "Gd. 38", "normal", 0.12),
    _station(5001, "Server 50", "Gd. 50", "warning", 21.4),
    _station(5201, "Server 52", "Gd. 52", "offline", 0.0),
]


def _send_json(handler: BaseHTTPRequestHandler, payload, status: int = 200):
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


class RadMonUIHandler(BaseHTTPRequestHandler):
    server_version = "RadMonUITest/1.0"

    def log_message(self, format, *args):  # noqa: A003 - stdlib signature
        return

    def do_GET(self):  # noqa: N802 - stdlib signature
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/auth/me":
            return _send_json(
                self,
                {"username": "admin", "display_name": "RadMon Administrator With A Long Name", "role": "Administrator"},
            )

        if path == "/api/v1/web/overview":
            return _send_json(
                self,
                {
                    "counts": {"normal": 1, "warning": 1, "alarm": 0, "offline": 1},
                    "stations": STATIONS,
                    "role": "Administrator",
                },
            )

        if path == "/api/v1/web/stations":
            return _send_json(self, STATIONS)

        if path.startswith("/api/v1/web/stations/") and path.endswith("/history"):
            rows = [
                {
                    "serid": 3801,
                    "dtom": f"2026-09-14T03:{minute:02d}:00+00:00",
                    "doserate": 0.10 + minute / 1000,
                    "dose": 1.0 + minute / 100,
                    "stat": 0,
                }
                for minute in range(10, 20)
            ]
            return _send_json(self, rows)

        if path == "/api/v1/control/archives":
            return _send_json(
                self,
                [
                    {"quarter_id": "2026-Q2", "state": "COMPLETE", "start_at": "2026-04-01T00:00:00+00:00", "end_at": "2026-06-30T23:59:59+00:00"},
                    {"quarter_id": "2026-Q3", "state": "COMPLETE", "start_at": "2026-07-01T00:00:00+00:00", "end_at": "2026-09-30T23:59:59+00:00"},
                ],
            )

        if path == "/api/v1/control/alarm-events":
            return _send_json(
                self,
                [
                    {
                        "event_id": "alarm-1",
                        "serid": 5001,
                        "status": "ACTIVE",
                        "kind": "ALARM",
                        "measured_value": 27.1,
                        "threshold": 25.0,
                        "surfaced_at": "2026-09-14T03:40:00+00:00",
                    }
                ],
            )

        if path == "/api/v1/control/users":
            return _send_json(
                self,
                [
                    {"username": "admin", "display_name": "RadMon Administrator With A Long Name", "role": "Administrator", "enabled": True, "updated_at": "2026-09-14T03:00:00+00:00"},
                    {"username": "operator", "display_name": "Operator", "role": "Operator", "enabled": True, "updated_at": "2026-09-14T03:00:00+00:00"},
                ],
            )

        if path == "/api/v1/web/system":
            return _send_json(
                self,
                {
                    "service": "radmon-central",
                    "role": "Administrator",
                    "grafana_admin_url": "http://localhost:3300",
                    "sources": [
                        {
                            "source_id": "server38",
                            "host": "192.168.1.38",
                            "state": "CONNECTED",
                            "last_success": "2026-09-14T03:45:00+00:00",
                            "last_live_poll": "2026-09-14T03:45:00+00:00",
                            "last_failure": None,
                            "last_history_import": "2026-09-14T03:44:00+00:00",
                            "last_error": None,
                            "consecutive_failures": 0,
                        },
                        {
                            "source_id": "server50",
                            "host": "192.168.1.50",
                            "state": "OFFLINE",
                            "last_success": None,
                            "last_live_poll": None,
                            "last_failure": "2026-09-14T03:45:00+00:00",
                            "last_history_import": None,
                            "last_error": "connection refused",
                            "consecutive_failures": 3,
                        },
                    ],
                },
            )

        if path == "/api/v1/web/events":
            body = b"retry: 60000\nevent: ready\ndata: {\"type\":\"ready\"}\n\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if path.startswith("/app/assets/"):
            relative = path.removeprefix("/app/")
            asset = (DIST / relative).resolve()
            if DIST.resolve() not in asset.parents or not asset.is_file():
                self.send_error(404)
                return
            data = asset.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", mimetypes.guess_type(asset.name)[0] or "application/octet-stream")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        if path == "/app" or path.startswith("/app/"):
            index = DIST / "index.html"
            data = index.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        self.send_error(404)


@contextmanager
def _serve_ui():
    if not (DIST / "index.html").exists():
        pytest.skip("web/dist is missing; build the Vite frontend before browser UI tests")
    server = ThreadingHTTPServer(("127.0.0.1", 0), RadMonUIHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture(scope="module")
def chrome_driver():
    selenium = pytest.importorskip("selenium")
    del selenium
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service

    chrome = shutil.which("google-chrome") or shutil.which("google-chrome-stable") or shutil.which("chromium")
    if not chrome:
        pytest.skip("Chrome/Chromium is not available on this runner")

    options = Options()
    options.binary_location = chrome
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1366,900")

    chromedriver = shutil.which("chromedriver")
    driver = webdriver.Chrome(service=Service(chromedriver) if chromedriver else Service(), options=options)
    driver.set_page_load_timeout(20)
    yield driver
    driver.quit()


def _set_viewport(driver, width: int, height: int):
    driver.execute_cdp_cmd(
        "Emulation.setDeviceMetricsOverride",
        {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": False},
    )


def _wait_for_app(driver):
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait

    WebDriverWait(driver, 12).until(lambda browser: browser.find_elements(By.CSS_SELECTOR, ".page-stack"))


def _assert_no_horizontal_overflow(driver):
    overflow = driver.execute_script(
        "return document.documentElement.scrollWidth - document.documentElement.clientWidth;"
    )
    assert overflow <= 1, f"page-level horizontal overflow: {overflow}px"


def test_responsive_shell_geometry_across_approved_viewports(chrome_driver):
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait

    driver = chrome_driver
    viewports = [
        (360, 800),
        (390, 844),
        (430, 932),
        (768, 1024),
        (1024, 768),
        (1366, 768),
        (1920, 1080),
    ]

    with _serve_ui() as base:
        for width, height in viewports:
            _set_viewport(driver, width, height)
            driver.get(f"{base}/app")
            _wait_for_app(driver)
            WebDriverWait(driver, 8).until(lambda browser: browser.execute_script("return window.innerWidth") == width)
            _assert_no_horizontal_overflow(driver)

            shell_height = driver.execute_script("return document.querySelector('.app-shell').getBoundingClientRect().height")
            inner_height = driver.execute_script("return window.innerHeight")
            assert shell_height >= inner_height - 1

            if width < 640:
                assert driver.find_elements(By.CSS_SELECTOR, ".mobile-shell")
                assert not driver.find_elements(By.CSS_SELECTOR, ".desktop-shell")
                buttons = driver.find_elements(By.CSS_SELECTOR, ".mobile-bottom-nav .mobile-nav-button")
                assert len(buttons) == 4
                nav_rect = driver.execute_script("return document.querySelector('.mobile-bottom-nav').getBoundingClientRect().toJSON()")
                assert nav_rect["bottom"] <= inner_height + 1
                assert nav_rect["top"] >= 0

                ratio_error = driver.execute_script(
                    "const img=document.querySelector('.mobile-topbar img');"
                    "const r=img.getBoundingClientRect();"
                    "return Math.abs((r.width/r.height)-(img.naturalWidth/img.naturalHeight));"
                )
                assert ratio_error < 0.03

                driver.execute_script("window.scrollTo(0, document.body.scrollHeight)")
                final_gap = driver.execute_script(
                    "const page=document.querySelector('.mobile-content > .page-stack');"
                    "const nav=document.querySelector('.mobile-bottom-nav');"
                    "return page.getBoundingClientRect().bottom - nav.getBoundingClientRect().top;"
                )
                assert final_gap <= 2, f"mobile content is covered by bottom navigation: {final_gap}px"
            else:
                assert driver.find_elements(By.CSS_SELECTOR, ".desktop-shell")
                assert not driver.find_elements(By.CSS_SELECTOR, ".mobile-shell")
                content_width = driver.execute_script("return document.querySelector('.content-shell').getBoundingClientRect().width")
                inner_width = driver.execute_script("return window.innerWidth")
                assert content_width > inner_width * 0.55


def test_mobile_more_sheet_and_history_deep_link_are_reachable(chrome_driver):
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait

    driver = chrome_driver
    with _serve_ui() as base:
        _set_viewport(driver, 390, 844)
        driver.get(f"{base}/app")
        _wait_for_app(driver)

        more = next(button for button in driver.find_elements(By.CSS_SELECTOR, ".mobile-nav-button") if button.text == "More")
        more.click()
        for label in ("History", "Archives", "Users", "System"):
            WebDriverWait(driver, 8).until(
                lambda browser, text=label: any(element.text == text for element in browser.find_elements(By.TAG_NAME, "button"))
            )
        _assert_no_horizontal_overflow(driver)

        driver.get(f"{base}/app/history?station=3801")
        WebDriverWait(driver, 12).until(lambda browser: browser.find_elements(By.CSS_SELECTOR, ".history-summary"))
        assert "station=3801" in driver.current_url
        assert driver.find_elements(By.CSS_SELECTOR, ".trend-chart svg")
        assert driver.find_elements(By.CSS_SELECTOR, ".record-card")
        _assert_no_horizontal_overflow(driver)
