from __future__ import annotations

from pathlib import Path
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QTextEdit, QVBoxLayout, QWidget


class LogsPage(QWidget):
    def __init__(self, log_path: Path, parent=None):
        super().__init__(parent); self.log_path=Path(log_path); self.text=QTextEdit(); self.text.setReadOnly(True)
        refresh=QPushButton("Refresh logs"); refresh.clicked.connect(self.refresh)
        layout=QVBoxLayout(self); layout.addWidget(refresh); layout.addWidget(self.text,1)
        self.timer=QTimer(self); self.timer.timeout.connect(self.refresh); self.timer.start(5000); self.refresh()

    def refresh(self):
        if not self.log_path.is_file(): self.text.setPlainText(f"Log file belum ada: {self.log_path}"); return
        try:
            lines=self.log_path.read_text(encoding="utf-8",errors="replace").splitlines()[-1000:]; self.text.setPlainText("\n".join(lines)); self.text.verticalScrollBar().setValue(self.text.verticalScrollBar().maximum())
        except Exception as exc: self.text.setPlainText(str(exc))
