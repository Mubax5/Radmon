import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const source = await readFile(new URL("../src/pages/alarmLifecycle.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2021 },
}).outputText;
const lifecycleUrl = `data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`;
const lifecycle = await import(lifecycleUrl);

test("maps lifecycle statuses, reconciliation reasons, and suppression endings to Indonesian", () => {
  const statuses = {
    ACTIVE: "Aktif — perlu tindakan",
    RESPONDED: "Ditanggapi operator",
    AUTO_RESOLVED_NORMAL: "Pulih otomatis — bacaan kembali normal",
    SOURCE_HANDLED: "Ditangani pada alat sumber",
    RESOLVED: "Selesai",
    NORMAL: "Normal",
    ENDED: "Berakhir",
    SUPPRESSED: "Dalam supresi",
    AUTO_SILENCED: "Diredam otomatis",
    RETRIGGER_LOCKED: "Pengulangan alarm ditahan",
    PENDING: "Menunggu konfirmasi",
    AMBIGUOUS: "Perlu pemeriksaan operator",
    CONFIRMED: "Terkonfirmasi",
  };
  for (const [code, label] of Object.entries(statuses)) assert.equal(lifecycle.statusLabel(code), label);

  const reasons = {
    EXACT_SOURCE_ALARM_NOT_OBSERVED: "Menunggu konfirmasi alarm dari alat",
    AMBIGUOUS_SOURCE_CORRELATION: "Bukti alarm sumber belum cukup",
    SOURCE_EVENT_LINK_CONFLICT: "Tautan alarm sumber perlu diperiksa",
    SOURCE_ID_MISSING: "Identitas alat sumber belum tersedia",
    SOURCE_ALARM_STILL_ACTIVE: "Alarm pada alat sumber masih aktif",
    SOURCE_HANDLED_TIME_MISSING: "Waktu penanganan alat sumber belum tersedia",
    SOURCE_HANDLED_TIME_BEFORE_OCCURRENCE: "Waktu penanganan alat sumber perlu diperiksa",
    EXACT_SOURCE_I_FLAG_CONFIRMED: "Penanganan pada alat sumber terkonfirmasi",
    POLICY_EVENT_NOT_ACTIVE: "Event tidak lagi aktif untuk dikonfirmasi",
    POLICY_STATE_NOT_LINKED: "Menunggu sinkronisasi status alarm",
    SOURCE_EVENT_LINK_NOT_WRITTEN: "Menunggu sinkronisasi tautan alarm sumber",
  };
  for (const [reason, label] of Object.entries(reasons)) {
    assert.equal(lifecycle.describeLifecycle({ source_reconciliation: { status: "PENDING", reason } }).label, label);
  }
  assert.equal(lifecycle.describeLifecycle({ source_reconciliation: { status: "AMBIGUOUS", reason: "AMBIGUOUS_SOURCE_CORRELATION" } }).label, "Bukti alarm sumber belum cukup");
  assert.equal(lifecycle.describeLifecycle({ kind: "SUPPRESSION_END", action: "EXPIRED", reason: "EXPIRED" }).label, "Supresi berakhir: kedaluwarsa");
  assert.equal(lifecycle.describeLifecycle({ kind: "SUPPRESSION_END", action: "AUTO_NORMAL", reason: "AUTO_NORMAL" }).label, "Supresi berakhir: bacaan kembali normal");
  assert.equal(lifecycle.describeLifecycle({ kind: "SUPPRESSION_END", action: "CANCELLED", reason: "CANCELLED: operator stop" }).label, "Supresi berakhir: dihentikan operator");
});

test("unknown codes use a human fallback and raw lifecycle values remain available to disclosure", async () => {
  assert.equal(lifecycle.statusLabel("NEW_UNKNOWN_STATE"), "New Unknown State");
  assert.equal(lifecycle.kindLabel("NEW_EVENT_KIND"), "New Event Kind");
  const event = {
    source_reconciliation: { status: "PENDING", reason: "EXACT_SOURCE_ALARM_NOT_OBSERVED" },
  };
  assert.deepEqual(lifecycle.describeLifecycle(event).raw, [
    "kind: (kosong)",
    "status: (kosong)",
    "source_reconciliation.status: PENDING",
    "source_reconciliation.reason: EXACT_SOURCE_ALARM_NOT_OBSERVED",
  ]);
  const page = await readFile(new URL("../src/pages/AlarmsPage.tsx", import.meta.url), "utf8");
  assert.match(page, /<details>/);
  assert.match(page, /<summary>Rincian teknis<\/summary>/);
  assert.match(page, /lifecycle\.raw\.map/);
});
