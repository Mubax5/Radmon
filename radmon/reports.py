from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from html import escape
from pathlib import Path
from statistics import fmean
from typing import Any, Protocol

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .config import Settings


class ReportRepository(Protocol):
    def station_config(self, serid: int | None = None): ...

    def measurement_history(
        self,
        start: datetime,
        end: datetime,
        *,
        serid: int | None = None,
        limit: int = 5000,
    ) -> list[dict[str, Any]]: ...

    def alarm_history(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
        *,
        serid: int | None = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]: ...


@dataclass(frozen=True, slots=True)
class ReportSummary:
    first_measurement: datetime | None
    last_measurement: datetime | None
    minimum: float | None
    average: float | None
    maximum: float | None
    sample_count: int
    approximate_dose: float


def approximate_dose(rows: list[dict[str, Any]]) -> float:
    points = [
        (row.get("dtom"), row.get("doserate"))
        for row in rows
        if isinstance(row.get("dtom"), datetime) and row.get("doserate") is not None
    ]
    points.sort(key=lambda item: item[0])
    total = 0.0
    for (time_a, rate_a), (time_b, rate_b) in zip(points, points[1:]):
        hours = max(0.0, (time_b - time_a).total_seconds() / 3600.0)
        total += ((float(rate_a) + float(rate_b)) / 2.0) * hours
    return total


def _summary_from_rows(rows: list[dict[str, Any]]) -> ReportSummary:
    usable = [row for row in rows if row.get("doserate") is not None]
    values = [float(row["doserate"]) for row in usable]
    times = [
        row["dtom"]
        for row in usable
        if isinstance(row.get("dtom"), datetime)
    ]
    return ReportSummary(
        first_measurement=min(times) if times else None,
        last_measurement=max(times) if times else None,
        minimum=min(values) if values else None,
        average=fmean(values) if values else None,
        maximum=max(values) if values else None,
        sample_count=len(values),
        approximate_dose=approximate_dose(usable),
    )


class ReportService:
    def __init__(self, repository: ReportRepository, settings: Settings) -> None:
        self.repository = repository
        self.settings = settings

    def rows(
        self,
        start: datetime,
        end: datetime,
        limit: int = 200_000,
    ) -> list[dict[str, Any]]:
        if end <= start:
            raise ValueError("report end must be after start")
        return self.repository.measurement_history(
            start,
            end,
            serid=self.settings.serid,
            limit=limit,
        )

    def summary(self, start: datetime, end: datetime) -> ReportSummary:
        return _summary_from_rows(self.rows(start, end))

    @staticmethod
    def _dt(value: datetime | None) -> str:
        return "-" if value is None else value.strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def _fmt(value: float | None, decimals: int = 4) -> str:
        return "-" if value is None else f"{value:.{decimals}f}"

    def preview_html(
        self,
        start: datetime,
        end: datetime,
        *,
        limit: int = 1000,
    ) -> str:
        station = self.repository.station_config(self.settings.serid)
        rows = self.rows(start, end, limit=limit)
        summary = _summary_from_rows(rows)
        detail_rows: list[str] = []
        running_dose = 0.0
        previous: tuple[datetime, float] | None = None

        for index, row in enumerate(rows, start=1):
            measured_at = row.get("dtom")
            raw_rate = row.get("doserate")
            rate = float(raw_rate) if raw_rate is not None else None

            if previous and isinstance(measured_at, datetime) and rate is not None:
                previous_time, previous_rate = previous
                hours = max(
                    0.0,
                    (measured_at - previous_time).total_seconds() / 3600.0,
                )
                running_dose += ((previous_rate + rate) / 2.0) * hours
            if isinstance(measured_at, datetime) and rate is not None:
                previous = (measured_at, rate)

            detail_rows.append(
                "<tr>"
                f"<td>{index}</td>"
                f"<td>{station.serid}</td>"
                f"<td>{escape(station.room)}</td>"
                f"<td>{escape(station.location)}</td>"
                f"<td>{escape(self._dt(measured_at))}</td>"
                f"<td>{self._fmt(rate)}</td>"
                f"<td>{running_dose:.6f}</td>"
                "</tr>"
            )

        if not detail_rows:
            detail_rows.append(
                "<tr><td colspan='7'>No measurement data in selected range</td></tr>"
            )

        description = (
            f"Alert {station.warnlevel:g} µSv/h, Alarm {station.alarmlevel:g} µSv/h"
        )
        return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<style>
body {{ font-family: Arial, sans-serif; color: #222; font-size: 10pt; margin: 18px; }}
h1, h2 {{ text-align: center; margin: 4px; }}
table {{ width: 100%; border-collapse: collapse; margin: 10px 0 18px; }}
th, td {{ border: 1px solid #777; padding: 5px; text-align: center; }}
th {{ background: #efefef; }}
.range {{ text-align: center; font-weight: bold; margin: 4px 0 10px; }}
</style>
</head>
<body>
<h1>Instalasi Pengelolaan Limbah Radioaktif</h1>
<h2>Direktorat Pengelolaan Fasilitas Ketenaganukliran</h2>
<hr>
<h2>Summary</h2>
<table>
<tr><th>No.</th><th>Name</th><th>Location</th><th>Description</th><th>First Measurement</th><th>Last Measurement</th><th>Dose rate (Average/Max)</th></tr>
<tr><td>1</td><td>{escape(station.room)}</td><td>{escape(station.location)}</td><td>{escape(description)}</td><td>{self._dt(summary.first_measurement)}</td><td>{self._dt(summary.last_measurement)}</td><td>{self._fmt(summary.average)} / {self._fmt(summary.maximum)}</td></tr>
</table>
<h2>Dose rate and Approx. Dose</h2>
<div class="range">From {start:%Y-%m-%d %H:%M:%S} to {end:%Y-%m-%d %H:%M:%S}</div>
<table>
<tr><th>No.</th><th>Tag</th><th>Name</th><th>Location</th><th>Measurement</th><th>Dose rate</th><th>Approx. Dose</th></tr>
{''.join(detail_rows)}
</table>
</body>
</html>"""

    def export_csv(
        self,
        start: datetime,
        end: datetime,
        destination: Path | str,
    ) -> Path:
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = self.rows(start, end)
        columns = ("serid", "dtom", "doserate", "dose", "previnterval", "stat")
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=columns,
                extrasaction="ignore",
            )
            writer.writeheader()
            for row in rows:
                item = dict(row)
                if isinstance(item.get("dtom"), datetime):
                    item["dtom"] = item["dtom"].strftime("%Y-%m-%d %H:%M:%S")
                writer.writerow(item)
        return path

    def export_pdf(
        self,
        start: datetime,
        end: datetime,
        destination: Path | str,
    ) -> Path:
        """Programmatic PDF export retained for non-GUI callers and tests."""
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        station = self.repository.station_config(self.settings.serid)
        rows = self.rows(start, end)
        summary = _summary_from_rows(rows)
        alarms = self.repository.alarm_history(
            start,
            end,
            serid=self.settings.serid,
            limit=5000,
        )

        styles = getSampleStyleSheet()
        document = SimpleDocTemplate(
            str(path),
            pagesize=landscape(A4),
            leftMargin=12 * mm,
            rightMargin=12 * mm,
            topMargin=12 * mm,
            bottomMargin=12 * mm,
            title=f"Radmon Report - {station.room}",
        )
        story: list[Any] = [
            Paragraph("LAPORAN PEMANTAUAN RADIASI", styles["Title"]),
            Paragraph(
                f"{station.room} · {station.location} · ID {station.serid}",
                styles["Heading2"],
            ),
            Paragraph(
                f"Periode: {start:%Y-%m-%d %H:%M:%S} s/d {end:%Y-%m-%d %H:%M:%S}",
                styles["BodyText"],
            ),
            Spacer(1, 6 * mm),
        ]

        summary_data = [
            ["First", "Last", "Min", "Average", "Max", "Samples", "Approx. Dose"],
            [
                self._dt(summary.first_measurement),
                self._dt(summary.last_measurement),
                self._fmt(summary.minimum),
                self._fmt(summary.average),
                self._fmt(summary.maximum),
                str(summary.sample_count),
                self._fmt(summary.approximate_dose, 6),
            ],
        ]
        summary_table = Table(summary_data, repeatRows=1)
        summary_table.setStyle(self._table_style())
        story.extend([summary_table, Spacer(1, 6 * mm)])

        measurement_data = [["No", "Time", "Dose rate", "Prev interval", "Stat"]]
        for index, row in enumerate(rows[:1000], start=1):
            measurement_data.append(
                [
                    str(index),
                    self._dt(row.get("dtom")),
                    self._fmt(float(row["doserate"]))
                    if row.get("doserate") is not None
                    else "-",
                    str(row.get("previnterval", "-")),
                    str(row.get("stat", "-")),
                ]
            )
        if len(measurement_data) == 1:
            measurement_data.append(["-", "No data", "-", "-", "-"])
        measurements = Table(measurement_data, repeatRows=1)
        measurements.setStyle(self._table_style())
        story.extend([measurements, Spacer(1, 6 * mm)])

        alarm_data = [["Alarm ID", "Time", "Type", "Message"]]
        for row in alarms[:500]:
            alarm_data.append(
                [
                    str(row.get("alarmid", "-")),
                    self._dt(row.get("dtom")),
                    str(row.get("type", "-")),
                    str(row.get("msg") or "-"),
                ]
            )
        if len(alarm_data) == 1:
            alarm_data.append(["-", "-", "-", "No alarms"])
        alarm_table = Table(alarm_data, repeatRows=1)
        alarm_table.setStyle(self._table_style())
        story.append(alarm_table)

        document.build(story)
        return path

    @staticmethod
    def _table_style() -> TableStyle:
        return TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2b3035")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#8e949a")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f2f4f5")]),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
