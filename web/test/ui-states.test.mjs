import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

const read = (path) => readFile(new URL(path, import.meta.url), "utf8");

test("initial request errors do not leave pages presenting a loading state", async () => {
  const pages = await Promise.all([
    read("../src/pages/ArchivesPage.tsx"),
    read("../src/pages/ReportsPage.tsx"),
    read("../src/pages/SystemPage.tsx"),
    read("../src/pages/UsersPage.tsx"),
  ]);

  for (const page of pages) {
    assert.match(page, /!\w+ && !error \? <LoadingCard \/>/);
  }
});

test("error and feedback surfaces are announced and unavailable alarm history is not shown as zero", async () => {
  const [ui, actions, alarms, reports, history, css] = await Promise.all([
    read("../src/ui.tsx"),
    read("../src/components/ActionFeedback.tsx"),
    read("../src/pages/AlarmsPage.tsx"),
    read("../src/pages/ReportsPage.tsx"),
    read("../src/pages/HistoryPage.tsx"),
    read("../src/radmon.css"),
  ]);

  assert.match(ui, /className="error-card" role="alert"/);
  assert.match(actions, /role=\{state\.kind === "ok" \? "status" : "alert"\}/);
  assert.match(alarms, /value=\{items === null \? "—" : summary\.total\}/);
  assert.match(alarms, /items === null \? historyLoaded/);
  assert.doesNotMatch(reports, /!currentPreviewReady/);
  assert.match(history, /rowsStation/);
  assert.match(history, /currentRows = selected != null && rowsStation === selected \? rows : \[\]/);
  assert.match(css, /\.alarm-action-link \{[^}]*min-height: 44px/);
  assert.match(css, /\.alarm-notification-dismiss \{[^}]*min-width: 44px/);
});
