import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

const read = (path) => readFile(new URL(path, import.meta.url), "utf8");

test("history station toolbar is unboxed and omits the selected-station status line", async () => {
  const [page, css] = await Promise.all([
    read("../src/pages/HistoryPage.tsx"),
    read("../src/ui-polish.css"),
  ]);

  assert.match(page, /<div className="history-filter">\s*<div className="history-toolbar">/);
  assert.doesNotMatch(page, /LayerCard className="(?:filter-card )?history-filter"/);
  assert.doesNotMatch(css, /\.history-filter\s*\{[^}]*background\s*:/);
  assert.doesNotMatch(css, /\.history-filter\s*\{[^}]*border\s*:/);
  assert.doesNotMatch(page, /history-selected-meta|SERID \{selectedStation\.serid\}|last-known/);
  assert.doesNotMatch(css, /history-selected-meta/);
  assert.match(page, /data-testid="history-prev"[\s\S]*?data-testid="history-station-combobox"[\s\S]*?data-testid="history-next"/);
  assert.match(css, /\.history-carousel\s*\{[^}]*grid-template-columns:\s*40px minmax\(0, 1fr\) 40px/);
  assert.doesNotMatch(page, /history-range-select|Rentang riwayat/);
});

test("page descriptions and headings use concise user-facing Indonesian", async () => {
  const pages = [
    "OverviewPage.tsx", "StationsPage.tsx", "StationDetailPage.tsx", "HistoryPage.tsx",
    "ArchivesPage.tsx", "ReportsPage.tsx", "AlarmsPage.tsx", "UsersPage.tsx", "SystemPage.tsx",
  ];
  const source = (await Promise.all(pages.map((page) => read(`../src/pages/${page}`)))).join("\n");
  const userCopy = [...source.matchAll(/(?:description=|title=)\s*"([^"]*)"/g)]
    .map((match) => match[1]).join("\n");

  for (const jargon of [/backend/i, /database central/i, /read model/i, /\bworker\b/i,
    /security sidecar/i, /policy PIN/i, /Burst policy/i, /\bjob laporan\b/i,
    /\bquery\b/i, /event tersimpan di central/i]) {
    assert.doesNotMatch(userCopy, jargon);
  }
  for (const copy of [
    "Pantau kondisi radiasi terkini", "Cari stasiun, tinjau status", "Lihat kondisi terkini",
    "Jelajahi tren dan rekaman pengukuran", "Temukan arsip pengukuran",
    "Buat dan pratinjau laporan PDF", "Tinjau alarm aktif", "Kelola akun, peran",
    "Periksa koneksi sumber data",
  ]) {
    assert.ok(source.includes(copy), `Copy ramah pengguna belum ditemukan: ${copy}`);
  }
});
