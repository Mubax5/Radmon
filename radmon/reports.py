from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
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
    def measurement_history(self, start: datetime, end: datetime, *, serid: int | None = None, limit: int = 5000) -> list[dict[str, Any]]: ...
    def alarm_history(self, start: datetime | None = None, end: datetime | None = None, *, serid: int | None = None, limit: int = 1000) -> list[dict[str, Any]]: ...


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
    points = [(row.get("dtom"), row.get("doserate")) for row in rows if isinstance(row.get("dtom"), datetime) and row.get("doserate") is not None]
    points.sort(key=lambda item: item[0])
    total = 0.0
    for (time_a, rate_a), (time_b, rate_b) in zip(points, points[1:]):
        hours = max(0.0, (time_b - time_a).total_seconds() / 3600.0)
        total += ((float(rate_a) + float(rate_b)) / 2.0) * hours
    return total


class ReportService:
    def __init__(self, repository: ReportRepository, settings: Settings) -> None:
        self.repository = repository
        self.settings = settings

    def rows(self, start: datetime, end: datetime, limit: int = 200_000) -> list[dict[str, Any]]:
        if end <= start:
            raise ValueError("report end must be after start")
        return self.repository.measurement_history(start, end, serid=self.settings.serid, limit=limit)

    def summary(self, start: datetime, end: datetime) -> ReportSummary:
        rows = self.rows(start, end)
        usable = [row for row in rows if row.get("doserate") is not None]
        values = [float(row["doserate"]) for row in usable]
        times = [row["dtom"] for row in usable if isinstance(row.get("dtom"), datetime)]
        return ReportSummary(min(times) if times else None, max(times) if times else None, min(values) if values else None, fmean(values) if values else None, max(values) if values else None, len(values), approximate_dose(usable))

    def export_csv(self, start: datetime, end: datetime, destination: Path | str) -> Path:
        path = Path(destination); path.parent.mkdir(parents=True, exist_ok=True); rows = self.rows(start, end)
        columns = ("serid", "dtom", "doserate", "dose", "previnterval", "stat")
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore"); writer.writeheader()
            for row in rows:
                serializable = dict(row)
                if isinstance(serializable.get("dtom"), datetime): serializable["dtom"] = serializable["dtom"].strftime("%Y-%m-%d %H:%M:%S")
                writer.writerow(serializable)
        return path

    @staticmethod
    def _fmt(value: float | None, decimals: int = 4) -> str: return "-" if value is None else f"{value:.{decimals}f}"
    @staticmethod
    def _dt(value: datetime | None) -> str: return "-" if value is None else value.strftime("%Y-%m-%d %H:%M:%S")

    def export_pdf(self, start: datetime, end: datetime, destination: Path | str) -> Path:
        path = Path(destination); path.parent.mkdir(parents=True, exist_ok=True)
        station = self.repository.station_config(self.settings.serid); rows = self.rows(start, end); summary = self.summary(start, end); alarms = self.repository.alarm_history(start, end, serid=self.settings.serid, limit=5000)
        styles = getSampleStyleSheet(); doc = SimpleDocTemplate(str(path), pagesize=landscape(A4), leftMargin=12 * mm, rightMargin=12 * mm, topMargin=12 * mm, bottomMargin=12 * mm, title=f"Radmon Report - {station.room}", author="Radmon DPFK Python")
        story: list[Any] = [Paragraph("LAPORAN PEMANTAUAN RADIASI", styles["Title"]), Paragraph(f"{station.room} · {station.location} · ID {station.serid}", styles["Heading2"]), Paragraph(f"Periode: {start:%Y-%m-%d %H:%M:%S} s/d {end:%Y-%m-%d %H:%M:%S}", styles["BodyText"]), Paragraph(f"Threshold: Alert {station.warnlevel:g} µSv/h · Alarm {station.alarmlevel:g} µSv/h", styles["BodyText"]), Spacer(1, 6 * mm)]
        summary_data = [["First", "Last", "Min (µSv/h)", "Average (µSv/h)", "Max (µSv/h)", "Samples", "Approx. Dose (µSv)"], [self._dt(summary.first_measurement), self._dt(summary.last_measurement), self._fmt(summary.minimum), self._fmt(summary.average), self._fmt(summary.maximum), str(summary.sample_count), self._fmt(summary.approximate_dose, 6)]]
        summary_table = Table(summary_data, repeatRows=1); summary_table.setStyle(self._table_style()); story.extend([Paragraph("Summary", styles["Heading2"]), summary_table, Spacer(1, 6 * mm)])
        measurement_data = [["No", "Time", "Dose rate (µSv/h)", "Prev interval", "Stat"]]
        for index, row in enumerate(rows[:1000], start=1): measurement_data.append([str(index), self._dt(row.get("dtom")), self._fmt(float(row["doserate"])) if row.get("doserate") is not None else "-", str(row.get("previnterval", "-")), str(row.get("stat", "-"))])
        if len(measurement_data) == 1: measurement_data.append(["-", "No data", "-", "-", "-"])
        measurements = Table(measurement_data, repeatRows=1, colWidths=[12*mm, 50*mm, 42*mm, 30*mm, 20*mm]); measurements.setStyle(self._table_style()); story.extend([Paragraph("Measurement data (maks. 1000 row pada PDF)", styles["Heading2"]), measurements, Spacer(1, 6 * mm)])
        alarm_data = [["State", "Start", "End", "Value", "Threshold", "ACK by", "Note"]]
        for row in alarms[:500]: alarm_data.append([str(row.get("state", "-")), self._dt(row.get("started_at")), self._dt(row.get("ended_at")), self._fmt(row.get("last_value")), self._fmt(row.get("threshold_value")), str(row.get("acknowledged_by") or "-"), str(row.get("acknowledgement_note") or "-")])
        if len(alarm_data) == 1: alarm_data.append(["-", "-", "-", "-", "-", "No alarms", "-"])
        alarm_table = Table(alarm_data, repeatRows=1); alarm_table.setStyle(self._table_style()); story.extend([Paragraph("Alarm history", styles["Heading2"]), alarm_table, Spacer(1, 4 * mm), Paragraph(f"Generated: {datetime.now():%Y-%m-%d %H:%M:%S}", styles["BodyText"])]); doc.build(story); return path

    @staticmethod
    def _table_style() -> TableStyle:
        return TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2b3035")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#8e949a")), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f2f4f5")]), ("FONTSIZE", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)])
