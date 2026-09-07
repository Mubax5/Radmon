from __future__ import annotations

from pathlib import Path
from PySide6.QtWidgets import QTextEdit, QVBoxLayout, QWidget


class LogsPage(QWidget):
    def __init__(self, log_path: Path, parent=None):
        super().__init__(parent)
        self.log_path = Path(log_path)
        self.last_error: str | None = None
        self.text = QTextEdit()
        self.text.setReadOnly(True)
        layout = QVBoxLayout(self)
        layout.addWidget(self.text, 1)
        self.refresh_live()

    def refresh_live(self) -> None:
        if not self.log_path.is_file():
            self.text.setPlainText(f"Log file belum ada: {self.log_path}")
            self.last_error = None
            return
        try:
            lines = self.log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-1000:]
            self.text.setPlainText("\n".join(lines))
            self.text.verticalScrollBar().setValue(self.text.verticalScrollBar().maximum())
            self.last_error = None
        except Exception as exc:
            self.last_error = f"Log read error: {exc}"
