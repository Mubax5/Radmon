from __future__ import annotations

from PySide6.QtCharts import QChart, QChartView, QDateTimeAxis, QLineSeries, QValueAxis
from PySide6.QtCore import QDateTime, Qt
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import QDateTimeEdit, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget


class ChartPage(QWidget):
    def __init__(self, repository, settings, parent=None):
        super().__init__(parent)
        self.repository = repository; self.settings = settings
        self.start = QDateTimeEdit(QDateTime.currentDateTime().addSecs(-3*3600)); self.end = QDateTimeEdit(QDateTime.currentDateTime())
        for w in (self.start, self.end): w.setCalendarPopup(True); w.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        refresh = QPushButton("Refresh chart"); refresh.clicked.connect(self.refresh)
        controls = QHBoxLayout(); controls.addWidget(QLabel("From")); controls.addWidget(self.start); controls.addWidget(QLabel("To")); controls.addWidget(self.end); controls.addWidget(refresh); controls.addStretch(1)
        self.chart = QChart(); self.chart.setTitle("Dose rate and Approx. Dose")
        self.view = QChartView(self.chart); self.view.setRenderHint(QPainter.Antialiasing)
        layout = QVBoxLayout(self); layout.addLayout(controls); layout.addWidget(self.view, 1)
        self.refresh()

    def refresh(self):
        start = self.start.dateTime().toPython(); end = self.end.dateTime().toPython()
        try: rows = self.repository.measurement_history(start, end, serid=self.settings.serid, limit=100000)
        except Exception: rows = []
        self.chart.removeAllSeries()
        for axis in list(self.chart.axes()): self.chart.removeAxis(axis)
        dose_series = QLineSeries(); dose_series.setName("Dose rate")
        dose_series.setPen(QPen(Qt.red, 2))
        cumulative_series = QLineSeries(); cumulative_series.setName("Approx. Dose")
        cumulative_series.setPen(QPen(Qt.blue, 2))
        cumulative = 0.0; previous = None
        max_y = self.settings.alarmlevel * 1.15
        for row in rows:
            dt = row.get("dtom"); value = row.get("doserate")
            if dt is None or value is None: continue
            timestamp = int(dt.timestamp() * 1000); value = float(value)
            dose_series.append(timestamp, value); max_y = max(max_y, value * 1.1)
            if previous is not None:
                pdt, pvalue = previous; hours = max(0, (dt-pdt).total_seconds()/3600); cumulative += ((pvalue+value)/2)*hours
            cumulative_series.append(timestamp, cumulative); previous = (dt, value)
        self.chart.addSeries(dose_series); self.chart.addSeries(cumulative_series)
        axis_x = QDateTimeAxis(); axis_x.setFormat("HH:mm:ss"); axis_x.setTitleText("Time")
        axis_y = QValueAxis(); axis_y.setTitleText("Dose rate [µSv/h]"); axis_y.setRange(0, max(1.0, max_y))
        axis_dose = QValueAxis(); axis_dose.setTitleText("Approx. Dose [µSv]"); axis_dose.setRange(0, max(0.1, cumulative*1.2))
        self.chart.addAxis(axis_x, Qt.AlignBottom); self.chart.addAxis(axis_y, Qt.AlignLeft); self.chart.addAxis(axis_dose, Qt.AlignRight)
        dose_series.attachAxis(axis_x); dose_series.attachAxis(axis_y); cumulative_series.attachAxis(axis_x); cumulative_series.attachAxis(axis_dose)
        if rows:
            x1 = int(rows[0]["dtom"].timestamp()*1000); x2 = int(rows[-1]["dtom"].timestamp()*1000)
            for name, level, color in (("Alert threshold", self.settings.warnlevel, Qt.darkYellow), ("Alarm threshold", self.settings.alarmlevel, Qt.darkRed)):
                series = QLineSeries(); series.setName(name); series.append(x1, level); series.append(x2, level); pen = QPen(color, 1, Qt.DashLine); series.setPen(pen); self.chart.addSeries(series); series.attachAxis(axis_x); series.attachAxis(axis_y)
        self.chart.legend().setVisible(True)
