from radmon.config import Settings
from radmon.web_host import monitoring_url


def test_monitoring_url_is_grafana_kiosk_only() -> None:
    url = monitoring_url(Settings(central_host="192.168.1.2", grafana_fallback_port=3300))
    assert url.startswith("http://192.168.1.2:3300/")
    assert "kiosk" in url
    assert "autofitpanels" in url
    assert "/app" not in url
    assert "login" not in url.lower()
