from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
main_window = ROOT / "radmon/admin/main_window.py"
source = main_window.read_text(encoding="utf-8")
marker = "\ndef refresh_current_page(self) -> None:\n"
if source.count(marker) != 1:
    raise RuntimeError(f"expected one top-level refresh_current_page, found {source.count(marker)}")
head, tail = source.split(marker, 1)
method = "def refresh_current_page(self) -> None:\n" + tail
indented = "\n".join(("    " + line) if line else "" for line in method.splitlines())
main_window.write_text(head + "\n" + indented + "\n", encoding="utf-8")

gate = ROOT / "tests/test_no_revision_dispatch.py"
gate_source = gate.read_text(encoding="utf-8")
needle = '        ".github/workflows/repair-task10.yml",\n'
addition = (
    '        ".github/workflows/repair-task10.yml",\n'
    '        "scripts/repair_task10_indent.py",\n'
    '        ".github/workflows/repair-task10-indent.yml",\n'
)
if "scripts/repair_task10_indent.py" not in gate_source:
    if needle not in gate_source:
        raise RuntimeError("cleanup gate insertion point not found")
    gate.write_text(gate_source.replace(needle, addition, 1), encoding="utf-8")

for relative in (
    "scripts/repair_task10_indent.py",
    ".github/workflows/repair-task10-indent.yml",
):
    path = ROOT / relative
    if path.exists():
        path.unlink()
