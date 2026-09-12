from __future__ import annotations

import ast
from pathlib import Path
import textwrap

ROOT = Path(__file__).resolve().parents[1]


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write(path: Path, text: str) -> None:
    path.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")


def class_method_span(source: str, class_name: str, method_name: str) -> tuple[int, int]:
    tree = ast.parse(source)
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name)
    method = next(
        node for node in cls.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == method_name
    )
    start = min([method.lineno] + [decorator.lineno for decorator in method.decorator_list]) - 1
    return start, method.end_lineno


# 1) Fix the canonical Grafana helper reference introduced by the AST move.
grafana = ROOT / "radmon/grafana_tv.py"
grafana_source = read(grafana)
old = "    relation = status_relation(stations)"
new = "    relation = _status_relation(stations)"
if grafana_source.count(old) != 1:
    raise RuntimeError(f"expected exactly one legacy status_relation call, found {grafana_source.count(old)}")
write(grafana, grafana_source.replace(old, new, 1))


# 2) Fold the refresh wrapper into the canonical public method.  The old base
# returned early while the outer wrapper still refreshed source health/beeps;
# the combined method therefore uses an if/else instead of returning early.
main_window = ROOT / "radmon/admin/main_window.py"
source = read(main_window)
lines = source.splitlines()
base_start, base_end = class_method_span(source, "MainWindow", "_refresh_current_page_base")
public_start, public_end = class_method_span(source, "MainWindow", "refresh_current_page")
replacement = textwrap.dedent('''
    def refresh_current_page(self) -> None:
        page = self.tabs.currentWidget()
        if page is not None and hasattr(page, "refresh_live"):
            page.refresh_live()

        self._open_monitoring_if_ready()
        if self._monitoring_open_pending:
            self.statusBar().showMessage("Grafana sedang disiapkan dan diverifikasi...")
        else:
            error = getattr(page, "last_error", None) if page is not None else None
            mode = {"dummy": "DEMO", "detector": "DETECTOR", "lan": "LAN"}.get(
                self.source, self.source.upper()
            )
            if error:
                self.statusBar().showMessage(f"{mode} · {error}")
            else:
                self.statusBar().showMessage(
                    f"{mode} · {self.settings.station_label} · "
                    f"refresh {self.preferences.refresh_interval:g}s"
                )

        self._refresh_source_parent_states()
        context = get_context()
        if context is None:
            return
        try:
            active = context.alarm_mirror.list_alarms(active_only=True, limit=1)
        except Exception:
            active = []
        if active:
            now = time.monotonic()
            last = float(getattr(self, "_last_alarm_beep", 0.0))
            if now - last >= 1.5:
                QApplication.beep()
                self._last_alarm_beep = now
''').strip("\n").splitlines()

edits = [
    (base_start, base_end, []),
    (public_start, public_end, replacement),
]
for start, end, rendered in sorted(edits, key=lambda item: item[0], reverse=True):
    lines[start:end] = rendered
write(main_window, "\n".join(lines))


# 3) Keep the cleanup gate aware of this one-shot repair tooling.
gate = ROOT / "tests/test_no_revision_dispatch.py"
gate_source = read(gate)
needle = '        ".github/workflows/refactor-task10.yml",\n'
addition = (
    '        ".github/workflows/refactor-task10.yml",\n'
    '        "scripts/repair_task10.py",\n'
    '        ".github/workflows/repair-task10.yml",\n'
)
if "scripts/repair_task10.py" not in gate_source:
    if needle not in gate_source:
        raise RuntimeError("cleanup gate insertion point not found")
    gate_source = gate_source.replace(needle, addition, 1)
    write(gate, gate_source)


# 4) One-shot repair artifacts must not survive in the release branch.
for relative in (
    "scripts/repair_task10.py",
    ".github/workflows/repair-task10.yml",
):
    path = ROOT / relative
    if path.exists():
        path.unlink()
