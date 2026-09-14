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
    *[
        _station(6000 + index, f"Detector {index:02d}", f"Area {index:02d}", "normal", 0.1 + index / 1000)
        for index in range(1, 13)
    ],
]


def _overview_counts():
    return {
        status: sum(1 for station in STATIONS if station["status"] == status)
        for status in ("normal", "warning", "alarm", "offline")
    }


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
        path = urlparse(self.path).path

        if path == "/auth/me":
            if not getattr(self.server, "authenticated", True):
                return _send_json(self, {"detail": "authentication required"}, status=401)
            return _send_json(
                self,
                {"username": "admin", "display_name": "RadMon Administrator With A Long Name", "role": "Administrator"},
            )

        if path == "/api/v1/web/overview":
            return _send_json(
                self,
                {"counts": _overview_counts(), "stations": STATIONS, "role": "Administrator"},
            )

        if path == "/api/v1/web/stations":
            return _send_json(self, STATIONS)

        if path.startswith("/api/v1/web/stations/") and path.endswith("/history"):
            return _send_json(
                self,
                [
                    {
                        "serid": 3801,
                        "dtom": f"2026-09-14T03:{minute:02d}:00+00:00",
                        "doserate": 0.10 + minute / 1000,
                        "dose": 1.0 + minute / 100,
                        "stat": 0,
                    }
                    for minute in range(10, 20)
                ],
            )

        if path == "/api/v1/control/archives":
            return _send_json(
                self,
                [
                    {"quarter_id": "2025-Q4", "state": "COMPLETE", "start_at": "2025-10-01T00:00:00+00:00", "end_at": "2025-12-31T23:59:59+00:00"},
                    {"quarter_id": "2026-Q1", "state": "COMPLETE", "start_at": "2026-01-01T00:00:00+00:00", "end_at": "2026-03-31T23:59:59+00:00"},
                    {"quarter_id": "2026-Q2", "state": "COMPLETE", "start_at": "2026-04-01T00:00:00+00:00", "end_at": "2026-06-30T23:59:59+00:00"},
                    {"quarter_id": "2026-Q3", "state": "COMPLETE", "start_at": "2026-07-01T00:00:00+00:00", "end_at": "2026-09-30T23:59:59+00:00"},
                ],
            )

        if path == "/api/v1/control/alarm-events":
            return _send_json(
                self,
                [
                    {"event_id": "alarm-1", "serid": 5001, "status": "ACTIVE", "kind": "ALARM", "measured_value": 27.1, "threshold": 25.0, "surfaced_at": "2026-09-14T03:40:00+00:00"},
                    {"event_id": "locked-1", "serid": 5001, "status": "ACTIVE", "kind": "RETRIGGER_LOCKED", "measured_value": 27.4, "threshold": 25.0, "surfaced_at": "2026-09-14T03:41:00+00:00"},
                ],
            )

        if path == "/api/v1/control/users":
            return _send_json(
                self,
                [
                    {"username": "admin", "display_name": "RadMon Administrator With A Long Name", "role": "Administrator", "enabled": True, "updated_at": "2026-09-14T03:00:00+00:00"},
                    {"username": "operator", "display_name": "Operator", "role": "Operator", "enabled": True, "updated_at": "2026-09-14T03:00:00+00:00"},
                    {"username": "viewer", "display_name": "Viewer", "role": "Viewer", "enabled": True, "updated_at": "2026-09-14T03:00:00+00:00"},
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
                        {"source_id": "server38", "host": "192.168.1.38", "state": "CONNECTED", "last_success": "2026-09-14T03:45:00+00:00", "last_live_poll": "2026-09-14T03:45:00+00:00", "last_failure": None, "last_history_import": "2026-09-14T03:44:00+00:00", "last_error": None, "consecutive_failures": 0},
                        {"source_id": "server50", "host": "192.168.1.50", "state": "OFFLINE", "last_success": None, "last_live_poll": None, "last_failure": "2026-09-14T03:45:00+00:00", "last_history_import": None, "last_error": "connection refused", "consecutive_failures": 3},
                        {"source_id": "server52", "host": "192.168.1.52", "state": "DEGRADED", "last_success": "2026-09-14T03:30:00+00:00", "last_live_poll": "2026-09-14T03:30:00+00:00", "last_failure": "2026-09-14T03:44:00+00:00", "last_history_import": None, "last_error": "timeout", "consecutive_failures": 1},
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
            asset = (DIST / path.removeprefix("/app/")).resolve()
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
            data = (DIST / "index.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        self.send_error(404)


@contextmanager
def _serve_ui(*, authenticated: bool = True):
    if not (DIST / "index.html").exists():
        pytest.skip("web/dist is missing; build the Vite frontend before browser UI tests")
    server = ThreadingHTTPServer(("127.0.0.1", 0), RadMonUIHandler)
    server.authenticated = authenticated
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
    pytest.importorskip("selenium")
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service

    chrome = shutil.which("google-chrome") or shutil.which("google-chrome-stable") or shutil.which("chromium")
    if not chrome:
        pytest.skip("Chrome/Chromium is not available on this runner")
    options = Options()
    options.binary_location = chrome
    for argument in ("--headless=new", "--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu", "--window-size=1366,900"):
        options.add_argument(argument)
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


def _wait_for(driver, selector: str):
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait

    WebDriverWait(driver, 12).until(lambda browser: browser.find_elements(By.CSS_SELECTOR, selector))


def _element_text(element) -> str:
    return (element.get_attribute("textContent") or "").strip()


def _button(driver, label: str):
    from selenium.webdriver.common.by import By

    return next(
        button for button in driver.find_elements(By.TAG_NAME, "button")
        if _element_text(button) == label
    )


def _assert_no_horizontal_overflow(driver):
    overflow = driver.execute_script(
        "return document.documentElement.scrollWidth - document.documentElement.clientWidth;"
    )
    assert overflow <= 1, f"page-level horizontal overflow: {overflow}px"


def _assert_mobile_content_not_covered(driver):
    final_gap = driver.execute_script(
        "const content=document.querySelector('.mobile-content');"
        "content.scrollTop=content.scrollHeight;"
        "const page=document.querySelector('.mobile-content > .page-stack');"
        "const nav=document.querySelector('.mobile-bottom-nav');"
        "return page.getBoundingClientRect().bottom - nav.getBoundingClientRect().top;"
    )
    assert final_gap <= 2, f"mobile content is covered by bottom navigation: {final_gap}px"


def test_login_is_centered_and_brin_logo_keeps_its_aspect_ratio(chrome_driver):
    from selenium.webdriver.common.by import By

    with _serve_ui(authenticated=False) as base:
        for width, height in ((360, 800), (1366, 768)):
            _set_viewport(chrome_driver, width, height)
            chrome_driver.get(f"{base}/app/login")
            _wait_for(chrome_driver, ".login-card")
            _assert_no_horizontal_overflow(chrome_driver)
            card = chrome_driver.execute_script("return document.querySelector('.login-card').getBoundingClientRect().toJSON()")
            assert card["left"] >= 0 and card["right"] <= width + 1
            ratio_error = chrome_driver.execute_script(
                "const img=document.querySelector('.login-brand img'); const r=img.getBoundingClientRect();"
                "return Math.abs((r.width/r.height)-(img.naturalWidth/img.naturalHeight));"
            )
            assert ratio_error < 0.03
            assert not chrome_driver.find_elements(By.CSS_SELECTOR, ".brand-mark")
            assert "Sign in to RadMon" in chrome_driver.find_element(By.TAG_NAME, "body").text


def test_responsive_shell_geometry_across_approved_viewports(chrome_driver):
    from selenium.webdriver.common.by import By

    viewports = [(360, 800), (390, 844), (430, 932), (768, 1024), (1024, 768), (1366, 768), (1920, 1080)]
    with _serve_ui() as base:
        for width, height in viewports:
            _set_viewport(chrome_driver, width, height)
            chrome_driver.get(f"{base}/app")
            _wait_for(chrome_driver, ".page-stack")
            _assert_no_horizontal_overflow(chrome_driver)
            shell_height = chrome_driver.execute_script("return document.querySelector('.app-shell').getBoundingClientRect().height")
            inner_height = chrome_driver.execute_script("return window.innerHeight")
            assert shell_height >= inner_height - 1
            if width < 640:
                assert chrome_driver.find_elements(By.CSS_SELECTOR, ".mobile-shell")
                assert not chrome_driver.find_elements(By.CSS_SELECTOR, ".desktop-shell")
                assert len(chrome_driver.find_elements(By.CSS_SELECTOR, ".mobile-bottom-nav .mobile-nav-button")) == 4
                nav_rect = chrome_driver.execute_script("return document.querySelector('.mobile-bottom-nav').getBoundingClientRect().toJSON()")
                assert nav_rect["bottom"] <= inner_height + 1 and nav_rect["top"] >= 0
                ratio_error = chrome_driver.execute_script(
                    "const img=document.querySelector('.mobile-topbar img'); const r=img.getBoundingClientRect();"
                    "return Math.abs((r.width/r.height)-(img.naturalWidth/img.naturalHeight));"
                )
                assert ratio_error < 0.03
                _assert_mobile_content_not_covered(chrome_driver)
            else:
                assert chrome_driver.find_elements(By.CSS_SELECTOR, ".desktop-shell")
                assert not chrome_driver.find_elements(By.CSS_SELECTOR, ".mobile-shell")
                content_width = chrome_driver.execute_script("return document.querySelector('.content-shell').getBoundingClientRect().width")
                assert content_width > chrome_driver.execute_script("return window.innerWidth") * 0.55


def test_all_control_plane_pages_fit_mobile_and_desktop_viewports(chrome_driver):
    from selenium.webdriver.common.by import By

    routes = [
        ("/app", ".attention-panel"),
        ("/app/stations", ".station-search"),
        ("/app/history?station=3801", ".history-summary"),
        ("/app/archives", ".archive-summary"),
        ("/app/alarms", ".active-alarm-list"),
        ("/app/users", ".user-summary"),
        ("/app/system", ".source-health-summary"),
    ]
    with _serve_ui() as base:
        for width, height in ((390, 844), (1366, 768)):
            _set_viewport(chrome_driver, width, height)
            for path, marker in routes:
                chrome_driver.get(f"{base}{path}")
                _wait_for(chrome_driver, marker)
                _assert_no_horizontal_overflow(chrome_driver)
                if width < 640:
                    assert chrome_driver.find_elements(By.CSS_SELECTOR, ".mobile-shell")
                    _assert_mobile_content_not_covered(chrome_driver)
                else:
                    assert chrome_driver.find_elements(By.CSS_SELECTOR, ".desktop-shell")


def test_mobile_more_sheet_and_history_deep_link_are_reachable(chrome_driver):
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait

    with _serve_ui() as base:
        _set_viewport(chrome_driver, 390, 844)
        chrome_driver.get(f"{base}/app")
        _wait_for(chrome_driver, ".page-stack")
        _button(chrome_driver, "More").click()
        _wait_for(chrome_driver, ".mobile-more-sheet")
        route_container = chrome_driver.find_element(By.CSS_SELECTOR, ".mobile-more-sheet")
        assert route_container.get_attribute("data-secondary-routes") == "history,archives,users,system"
        labels = {_element_text(element) for element in chrome_driver.find_elements(By.TAG_NAME, "button") if _element_text(element)}
        assert {"History", "Archives", "Users", "System", "Full monitoring", "Sign out"} <= labels
        _assert_no_horizontal_overflow(chrome_driver)
        _button(chrome_driver, "History").click()
        WebDriverWait(chrome_driver, 8).until(lambda browser: "/app/history" in browser.current_url)

        chrome_driver.get(f"{base}/app/history?station=3801")
        _wait_for(chrome_driver, ".history-summary")
        assert "station=3801" in chrome_driver.current_url
        assert chrome_driver.find_elements(By.CSS_SELECTOR, ".trend-chart svg")
        assert chrome_driver.find_elements(By.CSS_SELECTOR, ".record-card")
        _assert_no_horizontal_overflow(chrome_driver)


def test_mobile_alarm_and_user_dialogs_stay_inside_viewport(chrome_driver):
    from selenium.webdriver.common.by import By

    with _serve_ui() as base:
        _set_viewport(chrome_driver, 390, 844)

        chrome_driver.get(f"{base}/app/alarms")
        _wait_for(chrome_driver, ".active-alarm-list")
        content = chrome_driver.find_element(By.CSS_SELECTOR, ".mobile-content")
        chrome_driver.execute_script("arguments[0].scrollTop=arguments[0].scrollHeight", content)
        respond = _button(chrome_driver, "Respond to alarm")
        assert respond.is_enabled()
        respond.click()
        _wait_for(chrome_driver, ".dialog-form")
        dialog_rect = chrome_driver.execute_script("return document.querySelector('[role=dialog]').getBoundingClientRect().toJSON()")
        assert dialog_rect["left"] >= -1 and dialog_rect["right"] <= 391 and dialog_rect["height"] <= 844
        assert chrome_driver.execute_script("return Number(getComputedStyle(document.querySelector('[role=dialog]')).zIndex)") >= 90
        _assert_no_horizontal_overflow(chrome_driver)
        chrome_driver.find_element(By.TAG_NAME, "body").send_keys("\ue00c")

        chrome_driver.get(f"{base}/app/users")
        _wait_for(chrome_driver, ".user-summary")
        _button(chrome_driver, "Create user").click()
        _wait_for(chrome_driver, ".user-create-form")
        form_rect = chrome_driver.execute_script("return document.querySelector('.user-create-form').getBoundingClientRect().toJSON()")
        assert form_rect["left"] >= -1 and form_rect["right"] <= 391 and form_rect["height"] <= 844
        _assert_no_horizontal_overflow(chrome_driver)
