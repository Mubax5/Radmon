import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const source = await readFile(new URL("../src/format.ts", import.meta.url), "utf8");
const javascript = ts.transpile(source, { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 });
const moduleUrl = `data:text/javascript;base64,${Buffer.from(javascript).toString("base64")}`;
const { formatDoseValue } = await import(moduleUrl);

test("dose formatter strips only insignificant trailing zeros", () => {
  assert.equal(formatDoseValue("1.340"), "1.34");
  assert.equal(formatDoseValue("11.230"), "11.23");
  assert.equal(formatDoseValue("0.833333333"), "0.833333333");
  assert.equal(formatDoseValue("0"), "0");
  assert.equal(formatDoseValue(12), "12");
});
