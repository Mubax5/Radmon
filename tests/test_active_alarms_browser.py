"""Isolated browser fixtures: never contact a real source or production API."""
import json
import threading
from http.server import ThreadingHTTPServer

import pytest

from test_web_responsive_browser import RadMonUIHandler


def test_native_selector_uses_canonical_sources_and_tracks_polling():
    playwright = pytest.importorskip('playwright.sync_api')
    active = [dict(event_id='source:gd52:5702:time', event_type='source_alarm',
                   source_id='gd52', serid=5702, remote_serid=52, status='ACTIVE', kind='SOURCE_ALARM',
                   event_time='2026-10-07T11:27:10', surfaced_at='2026-10-07T11:27:10', measured_value=76.82)]
    requests = []

    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(channel='msedge', headless=True)
        page = browser.new_page()
        server = ThreadingHTTPServer(('127.0.0.1', 0), RadMonUIHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def route(request):
            path = request.request.url.split(str(server.server_port), 1)[-1]
            if path.startswith('/api/v1/web/active-alarms'):
                request.fulfill(json={'items': active, 'total': len(active)})
            elif path.startswith('/api/v1/web/alarm-history'):
                request.fulfill(json={'items': [], 'total': 501, 'limit': 500, 'offset': 0})
            elif path.startswith('/api/v1/control/alarm-events/since'):
                request.fulfill(json={'events': [dict(event_id='transient', serid=5702, kind='ALARM', status='AUTO_RESOLVED_NORMAL', reason='HIGH_THRESHOLD', measured_value=76.82, surfaced_at='2026-10-07T11:27:10')], 'next_cursor': '4', 'has_more': False})
            elif request.request.method == 'POST':
                requests.append((path, request.request.post_data_json))
                request.fulfill(status=403, json={'detail': 'PIN salah'})
            else:
                request.continue_()

        page.route('**/*', route)
        try:
            page.goto(f'http://127.0.0.1:{server.server_port}/app/alarms')
            page.locator('.policy-alarm-toast').filter(has_text='Pulih otomatis').wait_for()
            assert '2026' in page.locator('.policy-alarm-toast').inner_text()
            page.get_by_role('button', name='Tutup notifikasi', exact=True).click()
            page.locator('.action-card').first.get_by_role('button', name='Respons alarm', exact=True).click()
            select = page.get_by_test_id('alarm-event-select')
            assert select.input_value() == active[0]['event_id']
            assert select.locator('option').count() == 2
            assert 'gd52' in select.locator('option').nth(1).inner_text()
            assert page.locator('.active-alarm-list .alarm-card').count() == 1
            active.append(dict(active[0], event_id='source:gd38:5702:time', source_id='gd38'))
            page.get_by_role('button', name='Batal', exact=True).click()
            page.get_by_role('button', name='Muat ulang', exact=True).click()
            page.wait_for_function("document.querySelectorAll('.active-alarm-list .alarm-card').length === 2")
            page.locator('.action-card').first.get_by_role('button', name='Respons alarm', exact=True).click()
            assert select.locator('option').count() == 3
            select.select_option('source:gd38:5702:time')
            page.get_by_role('textbox', name='Alasan', exact=True).fill('checked')
            page.get_by_role('textbox', name='PIN', exact=True).fill('9999')
            page.get_by_role('button', name='Kirim respons', exact=True).click()
            page.wait_for_function("document.querySelector('.form-error')?.textContent.includes('PIN salah')")
            assert requests[0][0] == '/api/v1/control/alarms/gd38/5702/ack'
            assert requests[0][1]['pin'] == '9999'
            assert select.is_visible()
            active.clear()
            page.get_by_role('button', name='Batal', exact=True).click()
            page.get_by_role('button', name='Muat ulang', exact=True).click()
            page.wait_for_function("document.querySelectorAll('.active-alarm-list .alarm-card').length === 0")
            page.locator('.action-card').first.get_by_role('button', name='Respons alarm', exact=True).click()
            assert select.input_value() == '' and select.locator('option').count() == 1
            assert select.is_disabled()
        finally:
            browser.close()
            server.shutdown()
            server.server_close()
