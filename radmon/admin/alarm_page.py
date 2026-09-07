from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget


class AlarmPage(QWidget):
    def __init__(self, repository, alarm_service, settings, parent=None):
        super().__init__(parent); self.repository=repository; self.alarm_service=alarm_service; self.settings=settings
        self.table = QTableWidget(0, 8); self.table.setHorizontalHeaderLabels(["Event ID", "State", "Start", "End", "Value", "Threshold", "ACK", "Note"]); self.table.horizontalHeader().setStretchLastSection(True)
        self.operator = QLineEdit(); self.operator.setPlaceholderText("operator name")
        self.note = QLineEdit(); self.note.setPlaceholderText("acknowledgement note")
        ack = QPushButton("Acknowledge selected"); ack.clicked.connect(self.acknowledge)
        controls = QHBoxLayout(); controls.addWidget(QLabel("Operator")); controls.addWidget(self.operator); controls.addWidget(QLabel("Note")); controls.addWidget(self.note,1); controls.addWidget(ack)
        layout=QVBoxLayout(self); layout.addLayout(controls); layout.addWidget(self.table,1)
        self.timer=QTimer(self); self.timer.timeout.connect(self.refresh); self.timer.start(3000); self.refresh()

    def refresh(self):
        try: rows=self.repository.alarm_history(serid=self.settings.serid, limit=500)
        except Exception as exc: QMessageBox.warning(self,"Alarm read error",str(exc)); return
        self.table.setRowCount(len(rows))
        for r,row in enumerate(rows):
            vals=[row.get("eventid"),row.get("state"),row.get("started_at"),row.get("ended_at"),row.get("last_value"),row.get("threshold_value"),row.get("acknowledged_by"),row.get("acknowledgement_note")]
            for c,value in enumerate(vals):
                text=value.strftime("%Y-%m-%d %H:%M:%S") if hasattr(value,"strftime") else ("" if value is None else str(value)); self.table.setItem(r,c,QTableWidgetItem(text))

    def acknowledge(self):
        row=self.table.currentRow()
        if row<0: QMessageBox.information(self,"Alarm","Pilih event yang akan di-acknowledge."); return
        event_item=self.table.item(row,0); operator=self.operator.text().strip()
        if not event_item or not operator: QMessageBox.warning(self,"Alarm","Event dan operator wajib diisi."); return
        try: self.alarm_service.acknowledge(int(event_item.text()),operator,self.note.text()); self.refresh()
        except Exception as exc: QMessageBox.critical(self,"Acknowledge error",str(exc))
