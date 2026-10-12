import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { createRequire } from "node:module";

const ts = createRequire(import.meta.url)("typescript");
const source = await readFile(new URL("../src/pages/alarmHistory.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2021 },
}).outputText;
const history = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);

test("correlated policy resolution does not replace the source alarm row", () => {
  const sourceRow = {
    event_type: "source_alarm",
    source_id: "gd52",
    serid: 5702,
    remote_serid: 5702,
    event_time: "2026-10-07T11:27:10",
    surfaced_at: "2026-10-07T11:27:10",
    measured_value: 76.82,
    threshold: 25,
    status: "ACKNOWLEDGED",
    is_active: false,
    source_i_flag: 1,
    policy_event: {
      event_id: "policy-5702",
      serid: 5702,
      kind: "ALARM",
      status: "AUTO_RESOLVED_NORMAL",
      surfaced_at: "2026-10-07T11:26:22.808683",
    },
  };

  const [normalized] = history.normalizeHistory([sourceRow]);
  assert.equal(normalized.event_type, "source_alarm");
  assert.equal(normalized.status, "ACKNOWLEDGED");
  assert.equal(normalized.source_i_flag, 1);
  assert.equal(normalized.surfaced_at, "2026-10-07T11:27:10");
  assert.equal(normalized.measured_value, 76.82);
  assert.equal(normalized.policy_event.status, "AUTO_RESOLVED_NORMAL");
});

test("a policy-only event remains a central event", () => {
  const [normalized] = history.normalizeHistory([{
    event_type: "policy_lifecycle",
    source_id: "gd52",
    serid: 5702,
    kind: "ALARM",
    status: "AUTO_RESOLVED_NORMAL",
    surfaced_at: "2026-10-07T11:26:22.808683",
  }]);
  assert.equal(normalized.event_type, "policy_lifecycle");
  assert.equal(normalized.status, "AUTO_RESOLVED_NORMAL");
  assert.equal(normalized.source_id, "gd52");
});
