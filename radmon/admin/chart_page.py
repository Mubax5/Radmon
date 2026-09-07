from __future__ import annotations

from bisect import bisect_left
from datetime import datetime
from math import ceil

import pyqtgraph as pg
from PySide6.QtCore import QDateTime, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateTimeEdit,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .chart_state import ChartViewport


VISUAL_TREND = "Trend"
VISUAL_DISTRIBUTION = "Dose Rate Distribution"
VISUAL_STATUS = "Status Distribution"


def chart_series_from_rows(rows):
    """Return the exact operator values stored in measurement."""
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


class ChartPage(QWidget):
    """Interactive chart page with multiple operator-selectable views."""

    def __init__(self, repository, settings, parent=None) -> None:
        super().__init__(parent)
        self.repository = repository
        self.settings = settings
        self.last_error: str | None = None
        self.viewport = ChartViewport(live=True)
        self.points: list[tuple[float, float, float, int]] = []
        self.bar_item = None

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
        self.visual.addItems([VISUAL_TREND, VISUAL_DISTRIBUTION, VISUAL_STATUS])
        self.visual.currentTextChanged.connect(self._visual_changed)

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
            [], [], pen=pg.mkPen("#c62828", width=2), name="Dose rate"
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

        layout = QVBoxLayout(self)
        layout.addLayout(controls)
        layout.addWidget(self.plot, 1)
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
        else:
            self.plot.enableAutoRange()

    def _visual_changed(self, _label: str) -> None:
        self._render_current_view()
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

    def _remove_bar(self) -> None:
        if self.bar_item is not None:
            self.plot.removeItem(self.bar_item)
            self.bar_item = None

    def _set_trend_items_visible(self, visible: bool) -> None:
        for item in (
            self.rate_curve,
            self.dose_curve,
            self.alert_line,
            self.alarm_line,
            self.cross_x,
            self.cross_y,
            self.hover,
        ):
            item.setVisible(visible)
        self.plot.getAxis("right").setVisible(visible)

    def _render_current_view(self, *_args) -> None:
        self._remove_bar()
        mode = self.visual.currentText()
        if mode == VISUAL_TREND:
            self._render_trend()
        elif mode == VISUAL_DISTRIBUTION:
            self._render_distribution()
        else:
            self._render_status_distribution()

    def _render_trend(self) -> None:
        self._set_trend_items_visible(True)
        self.plot.setLabel("left", "Dose rate", units="µSv/h")
        self.plot.setLabel("bottom", "Time")
        self.plot.getAxis("bottom").setTicks(None)
        self.plot.getAxis("right").setLabel("Approx. Dose", units="µSv")
        x = [point[0] for point in self.points]
        rates = [point[1] for point in self.points]
        doses = [point[2] for point in self.points]
        self.rate_curve.setData(x, rates)
        self.dose_curve.setData(x, doses)
        self.alert_line.setValue(self.settings.warnlevel)
        self.alarm_line.setValue(self.settings.alarmlevel)

    def _render_distribution(self) -> None:
        self._set_trend_items_visible(False)
        rates = [point[1] for point in self.points]
        self.plot.setLabel("left", "Samples")
        self.plot.setLabel("bottom", "Dose rate", units="µSv/h")
        self.plot.getAxis("bottom").setTicks(None)
        if not rates:
            return
        low, high = min(rates), max(rates)
        if high <= low:
            centers = [low]
            counts = [len(rates)]
            width = max(abs(low) * 0.05, 0.01)
        else:
            bucket_count = min(20, max(5, int(ceil(len(rates) ** 0.5))))
            width = (high - low) / bucket_count
            counts = [0] * bucket_count
            for rate in rates:
                index = min(bucket_count - 1, int((rate - low) / width))
                counts[index] += 1
            centers = [low + (index + 0.5) * width for index in range(bucket_count)]
        self.bar_item = pg.BarGraphItem(
            x=centers,
            height=counts,
            width=width * 0.9,
            brush="#607d8b",
        )
        self.plot.addItem(self.bar_item)

    def _render_status_distribution(self) -> None:
        self._set_trend_items_visible(False)
        rates = [point[1] for point in self.points]
        normal = sum(rate < self.settings.warnlevel for rate in rates)
        alert = sum(self.settings.warnlevel <= rate < self.settings.alarmlevel for rate in rates)
        alarm = sum(rate >= self.settings.alarmlevel for rate in rates)
        x = [0, 1, 2]
        heights = [normal, alert, alarm]
        self.bar_item = pg.BarGraphItem(
            x=x,
            height=heights,
            width=0.6,
            brushes=["#2e7d32", "#f9a825", "#c62828"],
        )
        self.plot.addItem(self.bar_item)
        self.plot.setLabel("left", "Samples")
        self.plot.setLabel("bottom", "Status")
        self.plot.getAxis("bottom").setTicks(
            [[(0, "NORMAL"), (1, "ALERT"), (2, "ALARM")]]
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
        self.hover.setText(
            f"{datetime.fromtimestamp(x):%Y-%m-%d %H:%M:%S}\n"
            f"Dose rate: {rate:.4f} µSv/h\n"
            f"Approx. Dose: {dose:.6f} µSv"
        )
