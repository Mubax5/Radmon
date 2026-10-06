import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

const read = (path) => readFile(new URL(path, import.meta.url), "utf8");

test("station create is permission gated in a dialog and sample values never submit", async () => {
  const page = await read("../src/pages/StationsPage.tsx");
  assert.match(page, /user\.role !== "Viewer"[\s\S]*?Tambah station/);
  assert.match(page, /data-testid="station-create-dialog"/);
  assert.match(page, /createDialog\.current\?\.showModal\(\)/);
  assert.match(page, /onClick=\{fillExample\}/);
  assert.match(page, /setNewSerid\("12345"\)/);
  assert.match(page, /tanpa menyimpan/i);
  assert.doesNotMatch(page.match(/function fillExample\(\) \{([\s\S]*?)\n  \}/)?.[1] ?? "", /api\(/);
  assert.match(page, /\{ pin: newPin, serid, values:/);
});

test("user create, edit, and destructive delete confirmation use separate dialogs with native role selects", async () => {
  const [page, actions] = await Promise.all([read("../src/pages/UsersPage.tsx"), read("../src/Actions.tsx")]);
  assert.match(page, /data-testid="user-create-dialog"/);
  assert.match(page, /data-testid="user-edit-dialog"/);
  assert.match(page, /data-testid="user-delete-dialog"/);
  assert.match(page, /className="native-select" value=\{role\}/);
  assert.match(page, /PIN Administrator saat ini/);
  assert.match(page, /onClick=\{\(\) => deleteDialog\.current\?\.showModal\(\)\}/);
  assert.match(actions, /testId="user-role-select"/);
  assert.match(actions, /role,\s*password,/);
  assert.match(page, /display_name: displayName, role \}\)/);
  assert.match(page, /method: "PATCH"/);
});

test("page routes for alarms, stations, and users remain wired to their UI", async () => {
  const app = await read("../src/App.tsx");
  assert.match(app, /route === "stations" && <StationsPage \/>/);
  assert.match(app, /route === "alarms" && <AlarmsPage \/>/);
  assert.match(app, /route === "users" && <UsersPage \/>/);
});
