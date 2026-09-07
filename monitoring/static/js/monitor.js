const els = {
  label: document.getElementById('station-label'),
  last: document.getElementById('last-update'),
  freshness: document.getElementById('freshness'),
  trend: document.getElementById('trend-symbol'),
  dose: document.getElementById('dose-rate'),
  status: document.getElementById('status'),
  warning: document.getElementById('warnlevel'),
  alarm: document.getElementById('alarmlevel'),
  clock: document.getElementById('clock'),
};

function setStatusClass(status) {
  document.body.classList.remove('status-normal', 'status-alert', 'status-alarm', 'status-offline');
  document.body.classList.add(`status-${String(status).toLowerCase()}`);
}

function render(data) {
  els.label.textContent = data.label;
  els.last.textContent = data.last_update || 'NO DATA';
  els.freshness.textContent = data.age_seconds == null ? '-' : `${data.age_seconds} s`;
  els.trend.textContent = data.trend_symbol || '→';
  els.dose.textContent = data.dose_rate == null ? '---' : Number(data.dose_rate).toFixed(3);
  els.status.textContent = data.status;
  els.warning.textContent = Number(data.warnlevel).toLocaleString('id-ID');
  els.alarm.textContent = Number(data.alarmlevel).toLocaleString('id-ID');
  setStatusClass(data.status);
}

async function refresh() {
  try {
    const response = await fetch('/api/latest', { cache: 'no-store' });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    render(await response.json());
  } catch (error) {
    els.status.textContent = 'OFFLINE';
    els.freshness.textContent = 'server error';
    setStatusClass('OFFLINE');
  }
}

function updateClock() {
  els.clock.textContent = new Intl.DateTimeFormat('id-ID', { dateStyle: 'full', timeStyle: 'medium' }).format(new Date());
}

updateClock();
setInterval(updateClock, 2000);
setInterval(refresh, 2000);
refresh();
