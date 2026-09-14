from __future__ import annotations

import time

from test_web_responsive_browser import _serve_ui, _set_viewport, _wait_for, chrome_driver


def test_history_live_refresh_preserves_mobile_scroll_position(chrome_driver):
    script = r"""
(() => {
  window.__radmonTestEventSources = [];
  class RadMonTestEventSource {
    constructor() {
      this.onmessage = null;
      window.__radmonTestEventSources.push(this);
    }
    close() {}
  }
  window.EventSource = RadMonTestEventSource;
  window.__radmonEmitLiveUpdate = () => {
    const message = { data: JSON.stringify({ type: 'live_update', source_id: 'test' }) };
    for (const source of window.__radmonTestEventSources) {
      if (typeof source.onmessage === 'function') source.onmessage(message);
    }
  };
})();
"""
    registration = chrome_driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {"source": script},
    )
    try:
        with _serve_ui() as base:
            _set_viewport(chrome_driver, 390, 844)
            chrome_driver.get(f"{base}/app/history?station=3801")
            _wait_for(chrome_driver, ".record-card")
            content = chrome_driver.find_element("css selector", ".mobile-content")
            before = chrome_driver.execute_script(
                "const el=arguments[0]; el.scrollTop=Math.min(420, el.scrollHeight-el.clientHeight-20); return el.scrollTop;",
                content,
            )
            assert before > 100
            chrome_driver.execute_script("window.__radmonEmitLiveUpdate()")
            time.sleep(1.2)
            after = chrome_driver.execute_script("return arguments[0].scrollTop", content)
            assert abs(after - before) <= 16, f"scroll meloncat saat live refresh: {before} -> {after}"
    finally:
        chrome_driver.execute_cdp_cmd(
            "Page.removeScriptToEvaluateOnNewDocument",
            {"identifier": registration["identifier"]},
        )
