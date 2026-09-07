from __future__ import annotations

from bisect import bisect_left
from datetime import datetime

import pyqtgraph as pg
from PySide6.QtCore import QDateTime, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateTimeEdit,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .chart_metrics import status_breakdown, threshold_progress
from .chart_state import ChartViewport


VISUAL_TREND = "Trend"
VISUAL_STATUS = "Status Pie"
VISUAL_PROGRESS = "Threshold Progress"


def chart_series_from_rows(rows):
    """Return the exact values stored in measurement, ordered by measurement time."""
    normalized = []
    for row in rows:
        measured_at = row.get("dtom")
        rate = row.get("doserate")
        if not isinstance(measured_at, datetime) or rate is None:
            continue
        normalized.append(
            (
                measured_at,
                float(rate),
                float(row.get("dose") or 0.0),
                int(row.get("stat") or 0),
            )
        )
    normalized.sort(key=lambda item: item[0])
    return (
        [item[0].timestamp() for item in normalized],
        [item[1] for item in normalized],
        [item[2] for item in normalized],
        [item[3] for item in normalized],
    )


class StatusDonutWidget(QWidget):
    """Compact status pie that communicates sample health without bar-chart clutter."""

    COLORS = {
        "NORMAL": QColor("#2e7d32"),
        "ALERT": QColor("#f9a825"),
        "ALARM": QColor("#c62828"),
    }

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.counts = {"NORMAL": 0, "ALERT": 0, "ALARM": 0}
        self.setMinimumHeight(320)

    def set_counts(self, counts: dict[str, int]) -> None:
        self.counts = {key: int(counts.get(key, 0)) for key in self.COLORS}
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#ffffff"))

        total = sum(self.counts.values())
        side = min(self.height() - 64, int(self.width() * 0.48))
        side = max(180, side)
        left = max(24, int(self.width() * 0.12))
        top = max(28, (self.height() - side) // 2)
        pie_rect = QRectF(left, top, side, side)

        if total <= 0:
            painter.setPen(QPen(QColor("#c7c7c7"), 22))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(pie_rect.adjusted(12, 12, -12, -12))
        else:
            start_angle = 90 * 16
            for label in ("NORMAL", "ALERT", "ALARM"):
                count = self.counts[label]
                if count <= 0:
                    continue
                span = -int(round((count / total) * 360 * 16))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(self.COLORS[label])
                painter.drawPie(pie_rect, start_angle, span)
                start_angle += span

            inner = pie_rect.adjusted(side * 0.27, side * 0.27, -side * 0.27, -side * 0.27)
            painter.setBrush(QColor("#ffffff"))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(inner)

        painter.setPen(QColor("#222222"))
        center_font = painter.font()
        center_font.setPointSize(18)
        center_font.setBold(True)
        painter.setFont(center_font)
        painter.drawText(pie_rect, Qt.AlignmentFlag.AlignCenter, str(total) if total else "NO DATA")

        legend_x = left + side + 52
        legend_y = top + 48
        painter.setFont(self.font())
        for index, label in enumerate(("NORMAL", "ALERT", "ALARM")):
            y = legend_y + index * 62
            painter.setBrush(self.COLORS[label])
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(QRectF(legend_x, y, 22, 22), 4, 4)
            painter.setPen(QColor("#222222"))
            count = self.counts[label]
            percent = (count / total * 100.0) if total else 0.0
            painter.drawText(
                QRectF(legend_x + 34, y - 4, 240, 32),
                Qt.AlignmentFlag.AlignVCenter,
                f"{label}   {count} sample   {percent:.1f}%",
            )
        painter.end()


class ThresholdProgressWidget(QWidget):
    """Current/average/peak radiation level relative to the configured alarm limit."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.title = QLabel("Dose rate relative to alarm threshold")
        title_font = self.title.font()
        title_font.setPointSize(14)
        title_font.setBold(True)
        self.title.setFont(title_font)

        self.bars: dict[str, QProgressBar] = {}
        grid = QGridLayout()
        for row, key in enumerate(("Current", "Average", "Peak")):
            label = QLabel(key)
            bar = QProgressBar()
            bar.setRange(0, 1000)
            bar.setMinimumHeight(34)
            bar.setTextVisible(True)
            self.bars[key.lower()] = bar
            grid.addWidget(label, row, 0)
            grid.addWidget(bar, row, 1)
        grid.setColumnStretch(1, 1)

        self.thresholds = QLabel()
        self.thresholds.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(48, 52, 48, 52)
        layout.addWidget(self.title)
        layout.addSpacing(24)
        layout.addLayout(grid)
        layout.addSpacing(20)
        layout.addWidget(self.thresholds)
        layout.addStretch(1)

    @staticmethod
    def _color(value: float, warnlevel: float, alarmlevel: float) -> str:
        if value >= alarmlevel:
            return "#c62828"
        if value >= warnlevel:
            return "#f9a825"
        return "#2e7d32"

    def set_metrics(self, metrics: dict[str, float], *, warnlevel: float, alarmlevel: float) -> None:
        mapping = (
            ("current", "Current"),
            ("average", "Average"),
            ("peak", "Peak"),
        )
        for prefix, title in mapping:
            value = float(metrics[f"{prefix}_value"])
            percent = float(metrics[f"{prefix}_percent"])
            bar = self.bars[prefix]
            bar.setValue(int(round(percent * 10)))
            bar.setFormat(f"{title}: {value:.4f} µSv/h   ·   {percent:.1f}% of alarm")
            color = self._color(value, warnlevel, alarmlevel)
            bar.setStyleSheet(
                "QProgressBar { border: 1px solid #bdbdbd; border-radius: 4px; "
                "text-align: center; background: #f4f4f4; } "
                f"QProgressBar::chunk {{ background: {color}; border-radius: 3px; }}"
            )
        self.thresholds.setText(
            f"Alert {warnlevel:g} µSv/h     ·     Alarm {alarmlevel:g} µSv/h"
        )


class ChartPage(QWidget):
    """Interactive operator chart with trend, status pie and threshold progress views."""

    def __init__(self, repository, settings, parent=None) -> None:
        super().__init__(parent)
        self.repository = repository
        self.settings = settings
        self.last_error: str | None = None
        self.viewport = ChartViewport(live=True)
        self.points: list[tuple[float, float, float, int]] = []

        self.start = QDateTimeEdit(QDateTime.currentDateTime().addSecs(-3 * 3600))
        self.end = QDateTimeEdit(QDateTime.currentDateTime())
        for widget in (self.start, self.end):
            widget.setCalendarPopup(True)
            widget.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        self.live_window_seconds = max(2, self.start.dateTime().secsTo(self.end.dateTime()))

        self.live = QCheckBox("Live")
        self.live.setChecked(True)
        self.live.toggled.connect(self._live_changed)

        self.visual = QComboBox()
        self.visual.addItems([VISUAL_TREND, VISUAL_STATUS, VISUAL_PROGRESS])
        self.visual.currentTextChanged.connect(self._visual_changed)

        self.show_dose = QCheckBox("Approx. Dose")
        self.show_dose.setChecked(False)
        self.show_dose.toggled.connect(self._render_current_view)

        apply_range = QPushButton("Apply range")
        apply_range.clicked.connect(self.apply_range)
        reset = QPushButton("Reset view")
        reset.clicked.connect(self.reset_view)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("From"))
        controls.addWidget(self.start)
        controls.addWidget(QLabel("To"))
        controls.addWidget(self.end)
        controls.addWidget(self.live)
        controls.addWidget(QLabel("View"))
        controls.addWidget(self.visual)
        controls.addWidget(self.show_dose)
        controls.addWidget(apply_range)
        controls.addWidget(reset)
        controls.addStretch(1)

        self.plot = pg.PlotWidget(axisItems={"bottom": pg.DateAxisItem()})
        self.plot.setBackground("w")
        self.plot.showGrid(x=True, y=True, alpha=0.2)
        self.plot.setLabel("left", "Dose rate", units="µSv/h")
        self.plot.setLabel("bottom", "Time")
        self.plot.addLegend(offset=(10, 10))
        self.plot.getPlotItem().vb.sigRangeChangedManually.connect(self._manual_range_changed)

        self.plot.showAxis("right")
        self.plot.getAxis("right").setLabel("Approx. Dose", units="µSv")
        self.dose_view = pg.ViewBox()
        self.plot.scene().addItem(self.dose_view)
        self.plot.getAxis("right").linkToView(self.dose_view)
        self.dose_view.setXLink(self.plot.getPlotItem())
        self.plot.getPlotItem().vb.sigResized.connect(self._sync_right_view)

        self.rate_curve = self.plot.plot(
            [],
            [],
            pen=pg.mkPen("#c62828", width=2),
            symbol="o",
            symbolSize=3,
            symbolPen=pg.mkPen("#c62828"),
            symbolBrush=pg.mkBrush("#ffffff"),
            name="Dose rate",
        )
        self.dose_curve = pg.PlotCurveItem(
            [], [], pen=pg.mkPen("#1565c0", width=2), name="Approx. Dose"
        )
        self.dose_view.addItem(self.dose_curve)
        self.plot.getPlotItem().legend.addItem(self.dose_curve, "Approx. Dose")

        dash = Qt.PenStyle.DashLine
        self.alert_line = pg.InfiniteLine(
            angle=0,
            pos=settings.warnlevel,
            pen=pg.mkPen("#f9a825", width=1, style=dash),
            label="Alert threshold",
        )
        self.alarm_line = pg.InfiniteLine(
            angle=0,
            pos=settings.alarmlevel,
            pen=pg.mkPen("#b71c1c", width=1, style=dash),
            label="Alarm threshold",
        )
        self.plot.addItem(self.alert_line)
        self.plot.addItem(self.alarm_line)

        self.cross_x = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen("#666", width=1))
        self.cross_y = pg.InfiniteLine(angle=0, movable=False, pen=pg.mkPen("#666", width=1))
        self.plot.addItem(self.cross_x, ignoreBounds=True)
        self.plot.addItem(self.cross_y, ignoreBounds=True)
        self.hover = pg.TextItem(
            anchor=(0, 1),
            fill=pg.mkBrush(255, 255, 255, 230),
            border=pg.mkPen("#777"),
        )
        self.plot.addItem(self.hover)
        self.mouse_proxy = pg.SignalProxy(
            self.plot.scene().sigMouseMoved,
            rateLimit=30,
            slot=self._mouse_moved,
        )

        self.status_pie = StatusDonutWidget()
        self.threshold_progress = ThresholdProgressWidget()
        self.visual_stack = QStackedWidget()
        self.visual_stack.addWidget(self.plot)
        self.visual_stack.addWidget(self.status_pie)
        self.visual_stack.addWidget(self.threshold_progress)

        layout = QVBoxLayout(self)
        layout.addLayout(controls)
        layout.addWidget(self.visual_stack, 1)
        self._sync_right_view()
        self.refresh_live()

    def _sync_right_view(self) -> None:
        plot_view = self.plot.getPlotItem().vb
        self.dose_view.setGeometry(plot_view.sceneBoundingRect())
        self.dose_view.linkedViewChanged(plot_view, pg.ViewBox.XAxis)

    def _manual_range_changed(self, *_args) -> None:
        if self.visual.currentText() != VISUAL_TREND:
            return
        if self.live.isChecked():
            self.live.setChecked(False)
        self.viewport.capture(*self.plot.viewRange()[0])

    def _live_changed(self, checked: bool) -> None:
        self.viewport.live = checked
        if not checked:
            if self.visual.currentText() == VISUAL_TREND:
                self.viewport.capture(*self.plot.viewRange()[0])
            return
        self.live_window_seconds = max(2, self.start.dateTime().secsTo(self.end.dateTime()))
        if self.points and self.visual.currentText() == VISUAL_TREND:
            target = self.viewport.range_for_refresh(self.points[-1][0])
            if target is not None:
                self.plot.setXRange(*target, padding=0)

    def range(self) -> tuple[datetime, datetime]:
        return self.start.dateTime().toPython(), self.end.dateTime().toPython()

    def apply_range(self) -> None:
        start, end = self.range()
        if end <= start:
            self.last_error = "Chart range error: To must be after From"
            return
        self.live.setChecked(False)
        self.viewport.capture(start.timestamp(), end.timestamp())
        if self.visual.currentText() == VISUAL_TREND:
            self.plot.setXRange(start.timestamp(), end.timestamp(), padding=0)
        self.refresh_live()

    def reset_view(self) -> None:
        self.viewport.start_epoch = None
        self.viewport.end_epoch = None
        if self.visual.currentText() == VISUAL_TREND:
            start, end = self.range()
            self.viewport.capture(start.timestamp(), end.timestamp())
            self.plot.setXRange(start.timestamp(), end.timestamp(), padding=0)
            self.plot.enableAutoRange(axis=pg.ViewBox.YAxis, enable=True)
            self.dose_view.enableAutoRange(axis=pg.ViewBox.YAxis, enable=True)

    def _visual_changed(self, label: str) -> None:
        index = {
            VISUAL_TREND: 0,
            VISUAL_STATUS: 1,
            VISUAL_PROGRESS: 2,
        }.get(label, 0)
        self.visual_stack.setCurrentIndex(index)
        self.show_dose.setEnabled(label == VISUAL_TREND)
        self._render_current_view()
        if label == VISUAL_TREND:
            self.reset_view()

    def refresh_live(self) -> None:
        if self.live.isChecked():
            now = QDateTime.currentDateTime()
            self.end.setDateTime(now)
            self.start.setDateTime(now.addSecs(-self.live_window_seconds))
        start, end = self.range()
        try:
            rows = self.repository.measurement_history(
                start,
                end,
                serid=self.settings.serid,
                limit=100_000,
            )
            self.last_error = None
        except Exception as exc:
            rows = []
            self.last_error = f"Chart read error: {exc}"

        x, rates, doses, stats = chart_series_from_rows(rows)
        self.points = list(zip(x, rates, doses, stats))
        self._render_current_view()

        if not x or self.visual.currentText() != VISUAL_TREND:
            return
        if self.viewport.width is None:
            self.viewport.capture(start.timestamp(), end.timestamp())
            self.plot.setXRange(start.timestamp(), end.timestamp(), padding=0)
        elif self.live.isChecked():
            target = self.viewport.range_for_refresh(x[-1])
            if target is not None:
                self.plot.setXRange(*target, padding=0)

    def _set_trend_items_visible(self, visible: bool) -> None:
        dose_visible = visible and self.show_dose.isChecked()
        for item in (
            self.rate_curve,
            self.alert_line,
            self.alarm_line,
            self.cross_x,
            self.cross_y,
            self.hover,
        ):
            item.setVisible(visible)
        self.dose_curve.setVisible(dose_visible)
        self.plot.getAxis("right").setVisible(dose_visible)

    def _render_current_view(self, *_args) -> None:
        mode = self.visual.currentText()
        if mode == VISUAL_TREND:
            self._render_trend()
        elif mode == VISUAL_STATUS:
            self._render_status_pie()
        else:
            self._render_threshold_progress()

    def _render_trend(self) -> None:
        self._set_trend_items_visible(True)
        self.plot.setLabel("left", "Dose rate", units="µSv/h")
        self.plot.setLabel("bottom", "Time")
        self.plot.getAxis("bottom").setTicks(None)
        self.plot.getAxis("right").setLabel("Approx. Dose", units="µSv")
        x = [point[0] for point in self.points]
        rates = [point[1] for point in self.points]
        doses = [point[2] for point in self.points]
        self.rate_curve.setData(x, rates, connect="finite")
        self.dose_curve.setData(x, doses, connect="finite")
        self.alert_line.setValue(self.settings.warnlevel)
        self.alarm_line.setValue(self.settings.alarmlevel)

    def _render_status_pie(self) -> None:
        rates = [point[1] for point in self.points]
        self.status_pie.set_counts(
            status_breakdown(
                rates,
                warnlevel=self.settings.warnlevel,
                alarmlevel=self.settings.alarmlevel,
            )
        )

    def _render_threshold_progress(self) -> None:
        rates = [point[1] for point in self.points]
        self.threshold_progress.set_metrics(
            threshold_progress(rates, alarmlevel=self.settings.alarmlevel),
            warnlevel=self.settings.warnlevel,
            alarmlevel=self.settings.alarmlevel,
        )

    def _mouse_moved(self, event) -> None:
        if self.visual.currentText() != VISUAL_TREND or not self.points:
            return
        position = event[0]
        if not self.plot.sceneBoundingRect().contains(position):
            return
        mapped = self.plot.getPlotItem().vb.mapSceneToView(position)
        xs = [point[0] for point in self.points]
        index = min(max(bisect_left(xs, mapped.x()), 0), len(xs) - 1)
        x, rate, dose, _stat = self.points[index]
        self.cross_x.setPos(x)
        self.cross_y.setPos(rate)
        self.hover.setPos(x, rate)
        dose_text = f"\nApprox. Dose: {dose:.6f} µSv" if self.show_dose.isChecked() else ""
        self.hover.setText(
            f"{datetime.fromtimestamp(x):%Y-%m-%d %H:%M:%S}\n"
            f"Dose rate: {rate:.4f} µSv/h{dose_text}"
        )
