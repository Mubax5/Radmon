from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from radmon.alarm_policy import AlarmPolicyService
from radmon.alarm_policy_store import AlarmPolicyStore
from radmon.audit import AuditTrail
from radmon.remote_alarm import AlarmControlService, RemoteAlarmMirror
from radmon.secure_api import attach_secure_routes
from radmon.security import Role, SecurityStore
from radmon.web_api import attach_web_api_routes


def setup(tmp_path):
    security = SecurityStore(tmp_path / 'security.db')
    for name, role in [('operator', Role.OPERATOR), ('viewer', Role.VIEWER)]:
        security.create_user(name, name, role, 'Password123!', '1357')
    mirror = RemoteAlarmMirror(security)
    policy = AlarmPolicyService(AlarmPolicyStore(security), AuditTrail(security))
    calls = []

    class Remote:
        def respond_alarm(self, serid, event_time, **kwargs):
            calls.append((serid, event_time))
            return True

    control = AlarmControlService(
        security, mirror, AuditTrail(security),
        remote_factory=lambda _: Remote(),
        now=lambda: datetime(2026, 10, 7, 11, 27, 20),
    )
    control.policy_store = policy.store
    control.policy = policy
    app = FastAPI()
    attach_secure_routes(app, security=security, audit=AuditTrail(security), alarm_mirror=mirror, alarm_control=control, device_admin=None, alarm_policy=policy)
    attach_web_api_routes(app, security=security, repository=None, alarm_mirror=mirror, alarm_policy=policy)
    client = TestClient(app)
    client.post('/auth/login', json={'username': 'operator', 'password': 'Password123!'})
    return client, mirror, policy, calls


def source(mirror, source_id='gd52', at=datetime(2026, 10, 7, 11, 27, 10), flag=0):
    mirror.mirror(source_id, [{'serid': 5702, '_remote_serid': 52, 'dtoa': at, 'lvl': 2, 'mvalue': 76.82, 'thvalue': 25, 'i_flag': flag, 'ack': 0}])
    return at


def test_active_source_survives_resolved_policy_and_history_page(tmp_path):
    client, mirror, policy, _ = setup(tmp_path)
    at = source(mirror)
    policy.evaluate_live({'serid': 5702, '_remote_serid': 52, 'dtom': at, 'doserate': 76.82, 'warnlevel': 23, 'alarmlevel': 25}, source_id='gd52')
    policy.evaluate_live({'serid': 5702, 'dtom': at + timedelta(seconds=10), 'doserate': 1, 'warnlevel': 23, 'alarmlevel': 25})
    for index in range(501):
        source(mirror, 'gd38', at + timedelta(seconds=index + 20), flag=1)
    assert client.get('/api/v1/web/alarm-history?limit=25').json()['items'][0]['source_id'] == 'gd38'
    response = client.get('/api/v1/web/active-alarms')
    assert response.status_code == 200
    rows = response.json()['items']
    assert len(rows) == 1
    assert rows[0]['event_type'] == 'source_alarm'
    assert rows[0]['source_id'] == 'gd52' and rows[0]['remote_serid'] == 52
    assert rows[0]['status'] == 'ACTIVE' and rows[0]['is_active'] is True


def test_multi_source_identity_and_truly_empty(tmp_path):
    client, mirror, _, _ = setup(tmp_path)
    assert client.get('/api/v1/web/active-alarms').json()['items'] == []
    for source_id in ('gd52', 'gd38'):
        source(mirror, source_id)
    rows = client.get('/api/v1/web/active-alarms').json()['items']
    assert len(rows) == 2 and len({r['event_id'] for r in rows}) == 2


def test_correlated_active_policy_is_one_action_and_other_source_survives(tmp_path):
    client, mirror, policy, _ = setup(tmp_path)
    at = source(mirror)
    snap = policy.evaluate_live({'serid': 5702, '_remote_serid': 52, 'dtom': at, 'doserate': 76.82, 'warnlevel': 23, 'alarmlevel': 25}, source_id='gd52')
    with mirror.store._connection() as db:
        policy.store.link_source_policy_event('gd52', 5702, at, snap['active_event_id'], connection=db)
    source(mirror, 'gd38')
    rows = client.get('/api/v1/web/active-alarms').json()['items']
    assert len(rows) == 2
    assert {r['event_type'] for r in rows} == {'source_alarm', 'policy_lifecycle'}
    assert next(r for r in rows if r['event_type'] == 'policy_lifecycle')['event_id'] == snap['active_event_id']


def test_source_ack_requires_real_pin_role_and_remote_identifier(tmp_path):
    client, mirror, _, calls = setup(tmp_path)
    at = source(mirror)
    route = '/api/v1/control/alarms/gd52/5702/ack'
    payload = {'event_time': at.isoformat(), 'pin': '9999', 'action': 'Konfirmasi', 'pic': 'Operator', 'note': 'checked'}
    assert client.post(route, json=payload).status_code == 403
    assert calls == [] and mirror.get('gd52', 5702, at)['is_active']
    client.post('/auth/login', json={'username': 'viewer', 'password': 'Password123!'})
    payload['pin'] = '1357'
    assert client.post(route, json=payload).status_code == 403
    assert client.get('/api/v1/web/active-alarms').status_code == 200
    assert calls == []
    client.post('/auth/login', json={'username': 'operator', 'password': 'Password123!'})
    result = client.post(route, json=payload)
    assert result.status_code == 200
    assert calls == [(52, at)]
    assert result.json()['is_active'] is False and result.json()['source_i_flag'] == 1
    assert client.get('/api/v1/web/active-alarms').json()['items'] == []


def test_exact_correlation_without_dispatch_link_keeps_source_route(tmp_path):
    client, mirror, policy, _ = setup(tmp_path)
    at = source(mirror)
    policy.evaluate_live({'serid': 5702, '_remote_serid': 52, 'dtom': at, 'doserate': 76.82, 'warnlevel': 23, 'alarmlevel': 25}, source_id='gd52')
    rows = client.get('/api/v1/web/active-alarms').json()['items']
    assert len(rows) == 1 and rows[0]['event_type'] == 'source_alarm'
    result = client.post('/api/v1/control/alarms/gd52/5702/ack', json={
        'event_time': at.isoformat(), 'pin': '1357', 'action': 'Konfirmasi',
        'pic': 'Operator', 'note': 'checked',
    })
    assert result.status_code == 200
    assert policy.list_events(active_only=True) == []
    assert client.get('/api/v1/web/active-alarms').json()['items'] == []


def test_unlinked_policy_source_correlation_normalizes_source_clock_format(tmp_path):
    client, mirror, policy, _ = setup(tmp_path)
    source_time = datetime(2026, 10, 7, 11, 27, 10)
    policy.evaluate_live({
        'serid': 5702, '_remote_serid': 52,
        'dtom': source_time.replace(tzinfo=timezone.utc), 'doserate': 76.82,
        'warnlevel': 23, 'alarmlevel': 25,
    }, source_id='gd52')
    source(mirror, 'gd52', source_time)

    rows = client.get('/api/v1/web/active-alarms').json()['items']

    assert len(rows) == 1
    # The source route remains authoritative without a persisted dispatch link;
    # the policy must still not be duplicated as a second active row.
    assert rows[0]['event_type'] == 'source_alarm'
