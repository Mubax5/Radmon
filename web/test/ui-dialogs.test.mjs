import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

const read = (path) => readFile(new URL(path, import.meta.url), "utf8");

test("station create is permission gated in a dialog and sample values never submit", async () => {
  const page = await read("../src/pages/StationsPage.tsx");
  assert.match(page, /user\.role !== "Viewer"[\s\S]*?Tambah stasiun/);
  assert.match(page, /data-testid="station-create-dialog"/);
  assert.match(page, /createDialog\.current\?\.showModal\(\)/);
  assert.match(page, /onClick=\{fillExample\}/);
  assert.match(page, /setNewSerid\("12345"\)/);
  assert.match(page, /tanpa menyimpan/i);
  assert.doesNotMatch(page.match(/function fillExample\(\) \{([\s\S]*?)\n  \}/)?.[1] ?? "", /api\(/);
  assert.match(page, /\{ pin: newPin, serid, values:/);
});

test("user create, edit, and destructive delete confirmation use separate dialogs with native role selects", async () => {
  const [page, actions] = await Promise.all([read("../src/pages/UsersPage.tsx"), read("../src/components/UserActions.tsx")]);
  assert.match(page, /data-testid="user-create-dialog"/);
  assert.match(page, /data-testid="user-edit-dialog"/);
  assert.match(page, /data-testid="user-delete-dialog"/);
  assert.match(actions, /testId="user-role-select"/);
  assert.match(page, /PIN Administrator saat ini/);
  assert.match(page, /onClick=\{\(\) => deleteDialog\.current\?\.showModal\(\)\}/);
  assert.match(actions, /role,\s*password,/);
  assert.match(page, /display_name: displayName, role \}\)/);
  assert.match(page, /method: "PATCH"/);
  assert.match(page, /<Table.Head>Aksi<\/Table.Head>/);
  assert.doesNotMatch(page, /PageSection title="Administrasi pengguna"/);
  assert.match(page, /<Button type="button" variant="secondary" onClick=\{\(\) => dialog\.current\?\.showModal\(\)\}>Edit<\/Button>/);
  assert.match(page, /users\.some\(\(item\) => item\.enabled && item\.role === "Administrator"/);
  assert.match(actions, /administratorExists && role === "Administrator"/);
});

test("stations header owns the create dialog and history uses one fixed searchable station selector", async () => {
  const [stations, history] = await Promise.all([read("../src/pages/StationsPage.tsx"), read("../src/pages/HistoryPage.tsx")]);
  assert.match(stations, /title="Detail stasiun"[\s\S]*?action=\{user && user\.role !== "Viewer" \? <Button[\s\S]*?Tambah stasiun/);
  assert.doesNotMatch(stations, /Stasiun pusat/);
  assert.match(stations, /data-testid="station-create-dialog"/);
  assert.doesNotMatch(history, /Rentang|history-range-select|<Select/);
  assert.match(history, /const HISTORY_LIMIT = 240/);
  assert.match(history, /history-station-combobox/);
  assert.match(history, /history-prev[\s\S]*?history-next/);
});

test("operator PIC is display-name based and read-only while Administrator can edit", async () => {
  const [actions, alarms, api] = await Promise.all([
    read("../src/components/AlarmActions.tsx"),
    read("../src/components/AlarmActions.tsx"),
    read("../../radmon/secure_api.py"),
  ]);
  assert.match(actions, /useSession\(\)/);
  assert.match(actions, /readOnly=\{!canEditPic\}/);
  assert.match(alarms, /readOnly=\{!canEditPic\}/);
  assert.match(api, /payload\.pic or ""\)\.strip\(\) or identity\.display_name/);
});

test("page routes for alarms, stations, and users remain wired to their UI", async () => {
  const app = await read("../src/App.tsx");
  assert.match(app, /route === "stations" && <StationsPage \/>/);
  assert.match(app, /route === "alarms" && <AlarmsPage \/>/);
  assert.match(app, /route === "users" && <UsersPage \/>/);
});
