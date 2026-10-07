import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const source = await readFile(new URL("../src/alarmNotifications.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2021 },
}).outputText;
const { freshUndeliveredEvents, playAlarmSignal, notificationStateLabel } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);

test("resolved transient toast labels completion; recorded toast never claims current activity", () => {
  assert.match(notificationStateLabel({ status: "AUTO_RESOLVED_NORMAL" }), /Pulih otomatis.*selesai/);
  assert.match(notificationStateLabel({ status: "ACTIVE" }), /lihat Alarm.*terkini/);
});

test("fresh LOW/HIGH policy alarms notify once, including short-lived resolved events", () => {
  const delivered = new Set();
  const alarms = [
    { event_id: "low", kind: "ALARM", status: "AUTO_RESOLVED_NORMAL", reason: "LOW_THRESHOLD" },
    { event_id: "high", kind: "ALARM", status: "ACTIVE", reason: "HIGH_THRESHOLD" },
  ];
  assert.deepEqual(freshUndeliveredEvents(alarms, delivered).map((event) => event.event_id), ["low", "high"]);
  assert.deepEqual(freshUndeliveredEvents(alarms, delivered), []);
});

test("offline or stale policy event does not fire", () => {
  const delivered = new Set();
  assert.deepEqual(freshUndeliveredEvents([
    { event_id: "stale", kind: "ALARM", reason: "HIGH_THRESHOLD", fresh: false },
    { event_id: "offline", kind: "ALARM", reason: "LOW_THRESHOLD", offline: true },
  ], delivered), []);
});

test("audio is only constructed after the explicit sound toggle is enabled", () => {
  let constructed = 0;
  globalThis.window = { AudioContext: class {
    currentTime = 0;
    destination = {};
    constructor() { constructed += 1; }
    createOscillator() { return { connect() {}, start() {}, stop() {}, frequency: {}, type: "", onended: null }; }
    createGain() { return { connect() {}, gain: { setValueAtTime() {}, exponentialRampToValueAtTime() {} } }; }
    close() { return Promise.resolve(); }
  } };
  playAlarmSignal(false);
  assert.equal(constructed, 0);
  playAlarmSignal(true);
  assert.equal(constructed, 1);
});
