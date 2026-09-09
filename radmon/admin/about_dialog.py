from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout


GITHUB_URL = "https://github.com/Mubax5"
WEBSITE_URL = "https://mubacs.site"


class AboutDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("About Radiation Monitoring")
        self.setMinimumWidth(460)

        title = QLabel("<b>Radiation Monitoring (RadMon)</b><br>Realtime radiation monitoring and reporting system")
        title.setWordWrap(True)

        creator = QLabel("Creator: <b>Hilmi Mubarok</b>")

        links = QLabel(
            f'GitHub: <a href="{GITHUB_URL}">{GITHUB_URL}</a><br>'
            f'Website: <a href="{WEBSITE_URL}">{WEBSITE_URL}</a>'
        )
        links.setOpenExternalLinks(False)
        links.linkActivated.connect(self._open_link)

        description = QLabel(
            "Client and control software for radiation dose-rate monitoring, central LAN ingestion, "
            "alarm response, Grafana monitoring, reports, and regulatory archive access."
        )
        description.setWordWrap(True)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok)
        buttons.accepted.connect(self.accept)

        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addSpacing(8)
        layout.addWidget(creator)
        layout.addWidget(links)
        layout.addSpacing(8)
        layout.addWidget(description)
        layout.addWidget(buttons)

    @staticmethod
    def _open_link(url: str) -> None:
        QDesktopServices.openUrl(QUrl(url))
