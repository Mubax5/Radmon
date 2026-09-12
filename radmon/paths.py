from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys


def _source_root() -> Path:
    return Path(__file__).resolve().parents[1]


@dataclass(frozen=True, slots=True)
class ApplicationPaths:
    install_root: Path
    app_dir: Path
    config_dir: Path
    runtime_dir: Path
    archive_dir: Path
    report_dir: Path
    log_dir: Path
    assets_dir: Path
    grafana_dir: Path

    @property
    def env_file(self) -> Path:
        return self.config_dir / ".env"

    def asset_path(self, *parts: str) -> Path:
        return self.assets_dir.joinpath(*parts)

    @classmethod
    def discover(
        cls,
        executable: Path | None = None,
        *,
        frozen: bool | None = None,
    ) -> "ApplicationPaths":
        is_frozen = bool(getattr(sys, "frozen", False)) if frozen is None else bool(frozen)
        if is_frozen:
            app_dir = Path(executable or sys.executable).resolve().parent
            root = app_dir.parent
            return cls(
                install_root=root,
                app_dir=app_dir,
                config_dir=root / "config",
                runtime_dir=root / "runtime",
                archive_dir=root / "archives",
                report_dir=root / "reports",
                log_dir=root / "runtime" / "logs",
                assets_dir=app_dir / "assets",
                grafana_dir=app_dir / "grafana",
            )

        root = _source_root()
        return cls(
            install_root=root,
            app_dir=root,
            config_dir=root,
            runtime_dir=root / "runtime",
            archive_dir=root / "archives",
            report_dir=root / "reports",
            log_dir=root / "logs",
            assets_dir=root / "assets",
            grafana_dir=root / "grafana",
        )
