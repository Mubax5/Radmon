from datetime import datetime

from fastapi.testclient import TestClient

from radmon.config import Settings
from radmon.models import LatestReading, StationConfig
from radmon.public_api import create_public_app


class FakeRepo:
    def latest_reading(self, serid=None):
        station = StationConfig(5202, "52", "IS-1 Koridor", "Gd.52", 8, 10, 5, "uSv/h")
        return LatestReading(station, datetime.now(), 0.123, 0.120)


def client():
    return TestClient(create_public_app(FakeRepo(), Settings()))


def test_latest_api_exposes_demo_station_and_thresholds():
    payload = client().get("/api/latest").json()
    assert payload["serid"] == 5202
    assert payload["room"] == "IS-1 Koridor"
    assert payload["building"] == "52"
    assert payload["warnlevel"] == 8
    assert payload["alarmlevel"] == 10
    assert payload["status"] == "NORMAL"
    assert payload["trend"] == "UP"
    assert payload["trend_symbol"] == "↑"


def test_fullscreen_page_contains_public_station_identity_and_no_admin_controls():
    response = client().get("/")
    assert response.status_code == 200
    assert "REAL-TIME DOSE RATE MONITORING SYSTEM" in response.text
    assert "IS-1 Koridor" in response.text
    assert "Gd. 52" in response.text
    assert "Reports" not in response.text
    assert "Acknowledge" not in response.text
    assert "/static/js/monitor.js" in response.text
