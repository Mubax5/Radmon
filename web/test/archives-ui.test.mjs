import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

const read = (path) => readFile(new URL(path, import.meta.url), "utf8");

test("archive year and quarter exports remain unboxed, responsive, and show async status inline", async () => {
  const [page, css, history] = await Promise.all([
    read("../src/pages/ArchivesPage.tsx"),
    read("../src/radmon.css"),
    read("../src/pages/HistoryPage.tsx"),
  ]);

  assert.match(page, /<div className="archive-filter">[\s\S]*?<Select[\s\S]*?label="Tahun arsip"/);
  assert.doesNotMatch(page, /LayerCard className="filter-card archive-filter"/);
  assert.match(page, /year === "all" \? "all" : "year"/);
  assert.match(page, /startExport\("single", String\(item\.quarter_id\)\)/);
  assert.match(page, /function exportStatus\(job: ArchiveExportJob\)/);
  assert.match(page, /role="status"/);
  assert.match(page, /<progress[\s\S]*?aria-label="Progres bundle"/);
  assert.match(page, /archiveExportDownloadUrl\(job\.job_id\)/);
  assert.match(css, /\.archive-filter\s*\{[^}]*display:\s*grid/);
  assert.match(css, /\.archive-export-inline\s*\{[^}]*flex-wrap:\s*wrap/);
  assert.match(css, /@media \(min-width: 768px\)[\s\S]*?\.archive-filter\s*\{/);
  assert.match(history, /className="filter-card history-filter"/);
});
