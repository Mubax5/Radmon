import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { createRequire } from "node:module";
const ts = createRequire(import.meta.url)("typescript");
const source = await readFile(new URL("../src/activeAlarms.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext } }).outputText;
const { alarmResponseRequest, confirmAlarmResponse } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);
const fields = { pin: "1357", action: "Konfirmasi", pic: "Operator", reason: "checked" };
test("source-only response dispatch preserves source identity/time and real PIN", () => {
  const event = { event_id: "source:gd52:5702:time", event_type: "source_alarm", status: "ACTIVE", source_id: "gd52", serid: 5702, remote_serid: 52, event_time: "2026-10-07T11:27:10" };
  const request = alarmResponseRequest(event, fields);
  assert.equal(request.route, "/api/v1/control/alarms/gd52/5702/ack");
  assert.deepEqual(request.body, { pin: "1357", action: "Konfirmasi", pic: "Operator", note: "checked", event_time: event.event_time });
  assert.throws(() => confirmAlarmResponse(event, { is_active: true, source_i_flag: 0 }));
  assert.doesNotThrow(() => confirmAlarmResponse(event, { is_active: false, source_i_flag: 1, acknowledged_at: "time" }));
});
test("policy response uses event route and requires confirmed response", () => {
  const event = { event_id: "policy-1", event_type: "policy_lifecycle", status: "ACTIVE", serid: 5702 };
  assert.deepEqual(alarmResponseRequest(event, fields), { route: "/api/v1/control/alarm-events/policy-1/response", body: fields });
  assert.throws(() => confirmAlarmResponse(event, { status: "ACTIVE" }));
  assert.doesNotThrow(() => confirmAlarmResponse(event, { status: "RESPONDED" }));
  assert.throws(() => alarmResponseRequest({ ...event, status: "AUTO_RESOLVED_NORMAL" }, fields));
});
