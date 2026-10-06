import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const source = await readFile(new URL("../src/format.ts", import.meta.url), "utf8");
const javascript = ts.transpile(source, { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 });
const moduleUrl = `data:text/javascript;base64,${Buffer.from(javascript).toString("base64")}`;
const { formatDoseValue } = await import(moduleUrl);

test("dose formatter always renders exactly two decimal places", () => {
  assert.equal(formatDoseValue("0.3"), "0.30");
  assert.equal(formatDoseValue("0.120"), "0.12");
  assert.equal(formatDoseValue("0.833333"), "0.83");
  assert.equal(formatDoseValue("1.2"), "1.20");
  assert.equal(formatDoseValue("1.005"), "1.01");
  assert.equal(formatDoseValue("0"), "0.00");
  assert.equal(formatDoseValue(12), "12.00");
});
