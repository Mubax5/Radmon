from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from radmon.security import SecurityStore
from radmon.web_api import attach_web_api_routes

ROOT = Path(__file__).resolve().parents[1]


def test_web_event_broker_exists_and_keeps_subscriber_queues_bounded() -> None:
    assert (ROOT / "radmon/web_events.py").is_file()
    from radmon.web_events import WebEventBroker

    broker = WebEventBroker(max_queue=8)
    subscriber = broker.subscribe()
    for index in range(20):
        broker.publish({"type": "tick", "index": index})

    assert subscriber.qsize() <= 8
    assert subscriber.get_nowait()["index"] == 12


def test_web_event_broker_unsubscribe_releases_subscriber() -> None:
    assert (ROOT / "radmon/web_events.py").is_file()
    from radmon.web_events import WebEventBroker

    broker = WebEventBroker(max_queue=2)
    subscriber = broker.subscribe()
    assert broker.subscriber_count == 1
    broker.unsubscribe(subscriber)
    assert broker.subscriber_count == 0


def test_anonymous_web_event_stream_is_rejected(tmp_path: Path) -> None:
    assert (ROOT / "radmon/web_events.py").is_file()
    from radmon.web_events import WebEventBroker

    app = FastAPI()
    security = SecurityStore(tmp_path / "security.db")
    attach_web_api_routes(
        app,
        security=security,
        repository=object(),
        event_broker=WebEventBroker(),
    )

    response = TestClient(app).get("/api/v1/web/events")
    assert response.status_code == 401
