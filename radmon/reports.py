from __future__ import annotations

import csv
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from html import escape
from io import BytesIO
from pathlib import Path
from statistics import fmean
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas
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
    dose_values = [row.get("dose") for row in rows]
    if any(value is not None for value in dose_values):
        return sum(float(value or 0.0) for value in dose_values)
    points = [
        (row.get("dtom"), row.get("doserate"))
        for row in rows
        if isinstance(row.get("dtom"), datetime) and row.get("doserate") is not None
    ]
    points.sort(key=lambda item: _time_key(item[0]))
    total = 0.0
    for (time_a, rate_a), (time_b, rate_b) in zip(points, points[1:]):
        hours = max(0.0, (_time_key(time_b) - _time_key(time_a)).total_seconds() / 3600.0)
        total += ((float(rate_a) + float(rate_b)) / 2.0) * hours
    return total


def _time_key(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _summary_from_rows(rows: list[dict[str, Any]]) -> ReportSummary:
    usable = [row for row in rows if row.get("doserate") is not None]
    values = [float(row["doserate"]) for row in usable]
    times = [
        row["dtom"]
        for row in usable
        if isinstance(row.get("dtom"), datetime)
    ]
    return ReportSummary(
        first_measurement=min(times, key=_time_key) if times else None,
        last_measurement=max(times, key=_time_key) if times else None,
        minimum=min(values) if values else None,
        average=fmean(values) if values else None,
        maximum=max(values) if values else None,
        sample_count=len(values),
        approximate_dose=approximate_dose(usable),
    )


def _summary_from_mapping(row: dict[str, Any]) -> ReportSummary:
    return ReportSummary(
        first_measurement=row.get("first_measurement"),
        last_measurement=row.get("last_measurement"),
        minimum=float(row["minimum"]) if row.get("minimum") is not None else None,
        average=float(row["average"]) if row.get("average") is not None else None,
        maximum=float(row["maximum"]) if row.get("maximum") is not None else None,
        sample_count=int(row.get("sample_count") or 0),
        approximate_dose=float(row.get("approximate_dose") or 0.0),
    )


def _micro_unit(unit: str | None) -> str:
    text = str(unit or "µSv/h").strip().replace("μ", "µ")
    return "µSv/h" if text.lower() == "usv/h" else text


class ReportService:
    PREVIEW_ROW_LIMIT = 250
    MAX_MEASUREMENT_ROWS = 50_000
    MAX_ALARM_ROWS = 10_000
    MAX_RANGE = timedelta(hours=24)
    REPORT_TIMEZONE = ZoneInfo("Asia/Jakarta")

    def __init__(
        self,
        repository: ReportRepository,
        settings: Settings,
        *,
        summary_reader: Any | None = None,
    ) -> None:
        self.repository = repository
        self.settings = settings
        self.summary_reader = summary_reader

    @classmethod
    def validate_range(cls, start: datetime, end: datetime) -> timedelta:
        """Validate the report contract using elapsed time, not wall-clock time.

        Web requests arrive as UTC-aware values while the desktop client normally
        supplies WIB wall time.  Converting aware values to UTC before comparing
        them also keeps the limit correct across DST transitions in clients that
        are not running in WIB.
        """
        if not isinstance(start, datetime) or not isinstance(end, datetime):
            raise ValueError("waktu report tidak valid")
        try:
            elapsed = _time_key(end) - _time_key(start)
        except (TypeError, ValueError, OverflowError):
            raise ValueError("waktu report tidak valid") from None
        if elapsed <= timedelta(0):
            raise ValueError(
                "report end must be after start; waktu selesai harus setelah mulai"
            )
        if elapsed > cls.MAX_RANGE:
            raise ValueError(
                "rentang report terlalu panjang; maksimal 24 jam "
                "(tepat 24 jam diperbolehkan)"
            )
        return elapsed

    @staticmethod
    def _row_sort_key(row: dict[str, Any]) -> tuple[Any, ...]:
        measured_at = row.get("dtom") or row.get("dtoa")
        time_key = _time_key(measured_at) if isinstance(measured_at, datetime) else datetime.min.replace(tzinfo=timezone.utc)
        # dtom is not necessarily unique for all source imports.  Keep a stable
        # secondary identity when repositories expose one instead of relying on
        # the database's unspecified order for equal timestamps.
        identity = tuple(
            str(row.get(name, ""))
            for name in ("measurement_id", "id", "source_id", "serid", "alarmid")
        )
        return (time_key, identity)

    def _measurement_rows(
        self,
        start: datetime,
        end: datetime,
        *,
        limit: int,
    ) -> list[dict[str, Any]]:
        database_start = self._database_time(start)
        database_end = self._database_time(end)
        report_reader = getattr(self.summary_reader, "measurement_rows", None)
        if not callable(report_reader):
            report_reader = getattr(self.repository, "report_measurement_history", None)
        if callable(report_reader):
            rows = report_reader(
                database_start,
                database_end,
                serid=self.settings.serid,
                limit=max(1, int(limit)),
            )
        else:
            # The report path deliberately requests its own bounded limit.  It
            # must not inherit the 1,000/5,000 row limits used by history views.
            rows = self.repository.measurement_history(
                database_start,
                database_end,
                serid=self.settings.serid,
                limit=max(1, int(limit)),
            )
        bounded_rows: list[dict[str, Any]] = []
        for row in rows:
            bounded_rows.append(row)
            if len(bounded_rows) > max(1, int(limit)):
                raise ValueError(
                    f"jumlah pengukuran melebihi batas {self.MAX_MEASUREMENT_ROWS:,}; pilih rentang waktu lebih sempit"
                )
        return sorted(bounded_rows, key=self._row_sort_key)

    def rows(
        self,
        start: datetime,
        end: datetime,
        limit: int = 2_147_483_647,
    ) -> list[dict[str, Any]]:
        self.validate_range(start, end)
        database_start = self._database_time(start)
        database_end = self._database_time(end)
        count = self._count("measurement_count", database_start, database_end)
        if count is not None and count > self.MAX_MEASUREMENT_ROWS:
            raise ValueError(f"jumlah pengukuran melebihi batas {self.MAX_MEASUREMENT_ROWS:,}; pilih rentang waktu lebih sempit")
        requested_limit = max(1, int(limit))
        rows = self._measurement_rows(
            start,
            end,
            limit=min(requested_limit, self.MAX_MEASUREMENT_ROWS + 1),
        )
        if len(rows) > self.MAX_MEASUREMENT_ROWS:
            raise ValueError(f"jumlah pengukuran melebihi batas {self.MAX_MEASUREMENT_ROWS:,}; pilih rentang waktu lebih sempit")
        # A count is a preflight contract, not permission to silently emit a
        # partial PDF if an adapter applies its own history-page cap.
        if count is not None and requested_limit > count and len(rows) < count:
            raise ValueError(
                f"data report tidak lengkap: diterima {len(rows):,} dari {count:,} pengukuran"
            )
        return rows

    def _count(self, method_name: str, start: datetime, end: datetime) -> int | None:
        method = getattr(self.repository, method_name, None)
        if callable(method):
            return int(method(start, end, serid=self.settings.serid))
        return None

    @classmethod
    def _database_time(cls, value: datetime) -> datetime:
        """Measurement and alarm DATETIME columns store Asia/Jakarta wall time."""
        if value.tzinfo is None or value.utcoffset() is None:
            return value
        return value.astimezone(cls.REPORT_TIMEZONE).replace(tzinfo=None)

    def _checked_alarms(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        database_start = self._database_time(start)
        database_end = self._database_time(end)
        count = self._count("alarm_count", database_start, database_end)
        if count is not None and count > self.MAX_ALARM_ROWS:
            raise ValueError(f"jumlah alarm melebihi batas {self.MAX_ALARM_ROWS:,}; pilih rentang waktu lebih sempit")
        raw_rows = self.repository.alarm_history(database_start, database_end, serid=self.settings.serid, limit=self.MAX_ALARM_ROWS + 1)
        rows: list[dict[str, Any]] = []
        for row in raw_rows:
            rows.append(row)
            if len(rows) > self.MAX_ALARM_ROWS:
                break
        if len(rows) > self.MAX_ALARM_ROWS:
            raise ValueError(f"jumlah alarm melebihi batas {self.MAX_ALARM_ROWS:,}; pilih rentang waktu lebih sempit")
        return rows

    def preflight(self, start: datetime, end: datetime) -> None:
        self.validate_range(start, end)
        database_start = self._database_time(start)
        database_end = self._database_time(end)
        measurements = self._count("measurement_count", database_start, database_end)
        if measurements is not None and measurements > self.MAX_MEASUREMENT_ROWS:
            raise ValueError(f"jumlah pengukuran melebihi batas {self.MAX_MEASUREMENT_ROWS:,}; pilih rentang waktu lebih sempit")
        alarms = self._count("alarm_count", database_start, database_end)
        if alarms is not None and alarms > self.MAX_ALARM_ROWS:
            raise ValueError(f"jumlah alarm melebihi batas {self.MAX_ALARM_ROWS:,}; pilih rentang waktu lebih sempit")

    def _summary_for_range(
        self,
        start: datetime,
        end: datetime,
        *,
        fallback_rows: list[dict[str, Any]] | None = None,
    ) -> ReportSummary:
        self.validate_range(start, end)
        if self.summary_reader is not None:
            row = self.summary_reader.summary(
                self._database_time(start),
                self._database_time(end),
                serid=self.settings.serid,
            )
            if row:
                return _summary_from_mapping(row)
        aggregate = getattr(self.repository, "measurement_summary", None)
        if callable(aggregate):
            row = aggregate(self._database_time(start), self._database_time(end), serid=self.settings.serid)
            if row:
                return _summary_from_mapping(row)
        rows = fallback_rows if fallback_rows is not None else self.rows(start, end)
        summary = _summary_from_rows(rows)
        # A bounded preview still needs to say how many records exist when the
        # repository exposes the cheap indexed count but not an aggregate reader.
        count = self._count(
            "measurement_count",
            self._database_time(start),
            self._database_time(end),
        )
        if count is not None and count > summary.sample_count:
            summary = replace(summary, sample_count=count)
        return summary

    def summary(self, start: datetime, end: datetime) -> ReportSummary:
        return self._summary_for_range(start, end)

    @classmethod
    def _dt(cls, value: datetime | None) -> str:
        if value is None:
            return "-"
        if value.tzinfo is None or value.utcoffset() is None:
            value = value.replace(tzinfo=cls.REPORT_TIMEZONE)
        else:
            value = value.astimezone(cls.REPORT_TIMEZONE)
        return value.strftime("%Y-%m-%d %H:%M:%S WIB")

    @staticmethod
    def _fmt(value: float | None, decimals: int = 2) -> str:
        return "-" if value is None else f"{value:.{decimals}f}"

    def preview_html(
        self,
        start: datetime,
        end: datetime,
        *,
        limit: int = PREVIEW_ROW_LIMIT,
    ) -> str:
        self.validate_range(start, end)
        station = self.repository.station_config(self.settings.serid)
        rows = self._measurement_rows(start, end, limit=min(max(1, int(limit)), self.PREVIEW_ROW_LIMIT))
        summary = self._summary_for_range(start, end, fallback_rows=rows)
        detail_rows: list[str] = []
        running_dose = 0.0
        previous: tuple[datetime, float] | None = None

        for index, row in enumerate(rows, start=1):
            measured_at = row.get("dtom")
            raw_rate = row.get("doserate")
            rate = float(raw_rate) if raw_rate is not None else None
            if row.get("dose") is not None:
                running_dose += float(row["dose"])
            elif previous and isinstance(measured_at, datetime) and rate is not None:
                previous_time, previous_rate = previous
                hours = max(
                    0.0,
                    (_time_key(measured_at) - _time_key(previous_time)).total_seconds() / 3600.0,
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

        unit = _micro_unit(getattr(station, "unit", None))
        description = (
            f"Alert {station.warnlevel:g} {unit}, Alarm {station.alarmlevel:g} {unit}"
        )
        preview_note = ""
        if summary.sample_count > len(rows):
            preview_note = (
                f'<div class="note">Preview menampilkan {len(rows):,} dari '
                f'{summary.sample_count:,} pengukuran. Summary tetap dihitung dari seluruh range.</div>'
            )

        return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<style>
body {{ font-family: Arial, sans-serif; color: #222; font-size: 10pt; margin: 2px; padding: 0; }}
h1, h2 {{ text-align: center; margin: 4px 0; }}
hr {{ margin: 8px 0 10px; }}
table {{ width: 100%; table-layout: fixed; border-collapse: collapse; margin: 8px auto 16px; }}
th, td {{ border: 1px solid #777; padding: 5px 4px; text-align: center; overflow-wrap: anywhere; word-break: break-word; }}
th {{ background: #efefef; font-weight: bold; }}
.range {{ text-align: center; font-weight: bold; margin: 4px 0 8px; }}
.note {{ text-align: center; color: #555; font-size: 9pt; margin: 2px 0 8px; }}
</style>
</head>
<body>
<h1>Instalasi Pengelolaan Limbah Radioaktif</h1>
<h2>Direktorat Pengelolaan Fasilitas Ketenaganukliran</h2>
<hr>
<h2>Summary</h2>
<table width="100%" align="center" cellspacing="0" cellpadding="0">
<tr><th>No.</th><th>Name</th><th>Location</th><th>Description</th><th>First Measurement</th><th>Last Measurement</th><th>Dose rate (Average/Max)</th></tr>
<tr><td>1</td><td>{escape(station.room)}</td><td>{escape(station.location)}</td><td>{escape(description)}</td><td>{self._dt(summary.first_measurement)}</td><td>{self._dt(summary.last_measurement)}</td><td>{self._fmt(summary.average)} / {self._fmt(summary.maximum)}</td></tr>
</table>
<h2>Dose rate and Approx. Dose</h2>
<div class="range">From {self._dt(start)} to {self._dt(end)}</div>
{preview_note}
<table width="100%" align="center" cellspacing="0" cellpadding="0">
<tr><th>No.</th><th>Tag</th><th>Name</th><th>Location</th><th>Measurement</th><th>Dose rate (µSv/h)</th><th>Approx. Dose (µSv)</th></tr>
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
            writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
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
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self.pdf_bytes(start, end))
        return path

    def pdf_bytes(self, start: datetime, end: datetime, *, preview: bool = False) -> bytes:
        """Generate a complete report PDF, or a bounded draft PDF preview."""
        self.validate_range(start, end)
        if not preview:
            self.preflight(start, end)
        station = self.repository.station_config(self.settings.serid)
        if preview:
            rows = self._measurement_rows(start, end, limit=self.PREVIEW_ROW_LIMIT)
        else:
            rows = self.rows(start, end)
        summary = self._summary_for_range(start, end, fallback_rows=rows)
        alarms = (
            self.repository.alarm_history(
                self._database_time(start),
                self._database_time(end),
                serid=self.settings.serid,
                limit=250,
            )
            if preview
            else self._checked_alarms(start, end)
        )

        styles = getSampleStyleSheet()
        styles["Title"].fontSize = 12
        styles["Title"].leading = 14
        styles["Heading2"].fontSize = 11
        styles["Heading2"].leading = 13
        styles["BodyText"].fontSize = 8
        styles["Title"].alignment = 1
        styles["Heading2"].alignment = 1
        cell_body = ParagraphStyle(
            "ReportCell", parent=styles["BodyText"], fontSize=6.5,
            leading=8, alignment=1, splitLongWords=1,
        )
        cell_header = ParagraphStyle("ReportHeader", parent=cell_body, fontName="Helvetica-Bold", textColor=colors.white)

        def wrapped(data):
            return [
                [Paragraph(escape(str(value)), cell_header if row_index == 0 else cell_body) for value in row]
                for row_index, row in enumerate(data)
            ]
        output = BytesIO()
        document = SimpleDocTemplate(
            output,
            pagesize=A4,
            leftMargin=10 * mm,
            rightMargin=10 * mm,
            topMargin=10 * mm,
            bottomMargin=10 * mm,
            title=f"Radmon Report - {station.room}",
            pageCompression=0,
        )

        def column_widths(proportions: tuple[float, ...]) -> list[float]:
            """Allocate each table within the document's usable portrait width."""
            if not proportions or any(value <= 0 for value in proportions):
                raise ValueError("table column proportions must be positive")
            total = sum(proportions)
            widths = [document.width * value / total for value in proportions]
            # Avoid cumulative floating point error making the last column spill.
            widths[-1] = document.width - sum(widths[:-1])
            return widths

        def draw_page_number(canvas: Canvas, _document) -> None:
            canvas.saveState()
            canvas.setFont("Helvetica", 8)
            canvas.setFillColor(colors.HexColor("#555555"))
            canvas.drawCentredString(A4[0] / 2, 5 * mm, f"Page {canvas.getPageNumber()}")
            canvas.restoreState()

        unit = _micro_unit(getattr(station, "unit", None))
        description = f"Alert {station.warnlevel:g} {unit}, Alarm {station.alarmlevel:g} {unit}"
        story: list[Any] = [
            Paragraph("Instalasi Pengelolaan Limbah Radioaktif", styles["Title"]),
            Paragraph("Direktorat Pengelolaan Fasilitas Ketenaganukliran", styles["Heading2"]),
            Spacer(1, 2 * mm),
            Table([[""]], colWidths=[document.width], rowHeights=[0.5], style=TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.7, colors.black)])),
            Spacer(1, 3 * mm),
            Paragraph("Summary", styles["Heading2"]),
        ]
        summary_data = [
            ["No.", "Name", "Location", "Description", "First", "Last", "Dose Average", "Max"],
            [
                "1",
                str(station.room),
                str(station.location),
                description,
                self._dt(summary.first_measurement),
                self._dt(summary.last_measurement),
                self._fmt(summary.average),
                self._fmt(summary.maximum),
            ],
        ]
        summary_table = Table(
            wrapped(summary_data),
            colWidths=column_widths((5, 12, 12, 18, 16, 16, 13, 8)),
            repeatRows=1,
            hAlign="CENTER",
        )
        summary_table.setStyle(self._table_style())
        story.extend([
            summary_table,
            Paragraph(f"Sample count: {summary.sample_count:,}", styles["BodyText"]),
            Spacer(1, 5 * mm),
            Paragraph("Dose rate and Approx. Dose", styles["Heading2"]),
            Paragraph(f"From {self._dt(start)} to {self._dt(end)}", styles["BodyText"]),
            Spacer(1, 2 * mm),
        ])

        measurement_data = [["No.", "Tag", "Name", "Location", "Measurement", "Dose rate (µSv/h)", "Approx. Dose (µSv)"]]
        cumulative_dose = 0.0
        previous: tuple[datetime, float] | None = None
        for index, row in enumerate(rows, start=1):
            measured_at = row.get("dtom")
            rate = float(row["doserate"]) if row.get("doserate") is not None else None
            if row.get("dose") is not None:
                cumulative_dose += float(row["dose"])
            elif previous is not None and rate is not None and isinstance(measured_at, datetime):
                hours = max(0.0, (_time_key(measured_at) - _time_key(previous[0])).total_seconds() / 3600.0)
                cumulative_dose += ((previous[1] + rate) / 2.0) * hours
            if rate is not None and isinstance(measured_at, datetime):
                previous = (measured_at, rate)
            measurement_data.append(
                [
                    str(index),
                    str(row.get("serid", station.serid)),
                    str(station.room),
                    str(station.location),
                    self._dt(measured_at),
                    self._fmt(rate),
                    self._fmt(cumulative_dose),
                ]
            )
        if len(measurement_data) == 1:
            measurement_data.append(["-", "-", "-", "-", "No data", "-", "-"])
        measurements = Table(
            wrapped(measurement_data),
            colWidths=column_widths((7, 9, 16, 16, 21, 15, 16)),
            repeatRows=1,
            hAlign="CENTER",
        )
        measurements.setStyle(self._table_style())
        story.extend([measurements, Spacer(1, 2 * mm)])
        if preview and summary.sample_count > len(rows):
            story.append(Paragraph(
                f"Pratinjau: menampilkan {len(rows):,} dari {summary.sample_count:,} pengukuran dalam rentang pilihan.",
                styles["BodyText"],
            ))
        story.append(Spacer(1, 6 * mm))

        alarm_data = [["Alarm ID", "Time", "Type", "Message"]]
        for row in alarms:
            alarm_data.append(
                [
                    str(row.get("alarmid", "-")),
                    self._dt(row.get("dtom") or row.get("dtoa")),
                    str(row.get("type", "-")),
                    str(row.get("msg") or "-"),
                ]
            )
        if len(alarm_data) == 1:
            alarm_data.append(["-", "-", "-", "No alarms"])
        alarm_table = Table(
            wrapped(alarm_data),
            colWidths=column_widths((12, 20, 14, 54)),
            repeatRows=1,
            hAlign="CENTER",
        )
        alarm_table.setStyle(self._table_style())
        if alarms:
            story.extend([Paragraph("Alarm history", styles["Heading2"]), alarm_table])
        def stable_canvas(*args, **kwargs):
            kwargs["invariant"] = 1
            return Canvas(*args, **kwargs)

        document.build(story, onFirstPage=draw_page_number, onLaterPages=draw_page_number, canvasmaker=stable_canvas)
        return output.getvalue()

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
