from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QSettings


_ORGANIZATION = "RadMon"
_APPLICATION = "Radiation Monitoring"


@dataclass(slots=True)
class DesktopPreferences:
    """Non-sensitive desktop presentation/report preferences."""

    refresh_interval: float = 2.0
    date_format: str = "yyyy-MM-dd"
    datetime_format: str = "yyyy-MM-dd HH:mm:ss"
    dose_rate_format: str = "0.00"
    dose_format: str = "0.0000000"
    threshold_format: str = "0.##"
    warning_color: str = "#fff3a6"
    alarm_color: str = "#ffc4c4"
    csv_delimiter: str = ";"
    report_dir: str = "!REPORT!"
    institution: str = "Instalasi Pengelolaan Limbah Radioaktif"
    institution_address: str = "Gedung 52 KST B.J. Habibie Serpong"
    server_uri: str = ""
    api_path: str = "/api/v1/control/"
    api_version: str = "1.0"
    uri_datetime_format: str = "yyyy-MM-ddTHH:mm:ss"

    @classmethod
    def load(cls, settings) -> "DesktopPreferences":
        store = QSettings(_ORGANIZATION, _APPLICATION)
        defaults = cls(
            refresh_interval=float(getattr(settings, "refresh_interval", 2.0)),
            report_dir=str(getattr(settings, "report_dir", "!REPORT!")),
            server_uri=f"http://{getattr(settings, 'central_host', '192.168.1.2')}:8090",
        )

        def text(key: str, default: str) -> str:
            value = store.value(key, default)
            return str(default if value is None else value)

        def number(key: str, default: float) -> float:
            value = store.value(key, default)
            try:
                return float(value)
            except (TypeError, ValueError):
                return float(default)

        return cls(
            refresh_interval=max(0.25, number("display/refresh_interval", defaults.refresh_interval)),
            date_format=text("display/date_format", defaults.date_format),
            datetime_format=text("display/datetime_format", defaults.datetime_format),
            dose_rate_format=text("display/dose_rate_format", defaults.dose_rate_format),
            dose_format=text("display/dose_format", defaults.dose_format),
            threshold_format=text("display/threshold_format", defaults.threshold_format),
            warning_color=text("display/warning_color", defaults.warning_color),
            alarm_color=text("display/alarm_color", defaults.alarm_color),
            csv_delimiter=text("report/csv_delimiter", defaults.csv_delimiter),
            report_dir=text("report/report_dir", defaults.report_dir),
            institution=text("report/institution", defaults.institution),
            institution_address=text("report/institution_address", defaults.institution_address),
            server_uri=text("server/server_uri", defaults.server_uri),
            api_path=text("server/api_path", defaults.api_path),
            api_version=text("server/api_version", defaults.api_version),
            uri_datetime_format=text("server/uri_datetime_format", defaults.uri_datetime_format),
        )

    def save(self) -> None:
        store = QSettings(_ORGANIZATION, _APPLICATION)
        values = {
            "display/refresh_interval": self.refresh_interval,
            "display/date_format": self.date_format,
            "display/datetime_format": self.datetime_format,
            "display/dose_rate_format": self.dose_rate_format,
            "display/dose_format": self.dose_format,
            "display/threshold_format": self.threshold_format,
            "display/warning_color": self.warning_color,
            "display/alarm_color": self.alarm_color,
            "report/csv_delimiter": self.csv_delimiter,
            "report/report_dir": self.report_dir,
            "report/institution": self.institution,
            "report/institution_address": self.institution_address,
            "server/server_uri": self.server_uri,
            "server/api_path": self.api_path,
            "server/api_version": self.api_version,
            "server/uri_datetime_format": self.uri_datetime_format,
        }
        for key, value in values.items():
            store.setValue(key, value)
        store.sync()
