from __future__ import annotations

import time

from test_web_responsive_browser import _serve_ui, _wait_for, chrome_driver


def test_overview_live_refresh_never_overlaps_slow_request(chrome_driver):
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

  const originalFetch = window.fetch.bind(window);
  window.__radmonOverviewStats = { count: 0, inflight: 0, maxInflight: 0 };
  window.fetch = async (...args) => {
    const input = args[0];
    const url = typeof input === 'string' ? input : input.url;
    if (!url.includes('/api/v1/web/overview')) return originalFetch(...args);

    const stats = window.__radmonOverviewStats;
    stats.count += 1;
    stats.inflight += 1;
    stats.maxInflight = Math.max(stats.maxInflight, stats.inflight);
    await new Promise((resolve) => setTimeout(resolve, 900));
    try {
      return await originalFetch(...args);
    } finally {
      stats.inflight -= 1;
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
            chrome_driver.get(f"{base}/app")
            _wait_for(chrome_driver, ".metric-grid")
            chrome_driver.execute_script(
                "window.__radmonOverviewStats.count=0;"
                "window.__radmonOverviewStats.maxInflight=0;"
            )

            chrome_driver.execute_script("window.__radmonEmitLiveUpdate()")
            time.sleep(0.6)
            chrome_driver.execute_script("window.__radmonEmitLiveUpdate()")
            time.sleep(2.2)

            stats = chrome_driver.execute_script("return {...window.__radmonOverviewStats}")
            assert stats["count"] >= 1
            assert stats["maxInflight"] == 1, f"overview refresh overlap: {stats}"
    finally:
        chrome_driver.execute_cdp_cmd(
            "Page.removeScriptToEvaluateOnNewDocument",
            {"identifier": registration["identifier"]},
        )
