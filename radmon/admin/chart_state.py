from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ChartViewport:
    """Qt-free state holder for preserving an operator's chart viewport."""

    live: bool = True
    start_epoch: float | None = None
    end_epoch: float | None = None

    def capture(self, start_epoch: float, end_epoch: float) -> None:
        if end_epoch <= start_epoch:
            return
        self.start_epoch = float(start_epoch)
        self.end_epoch = float(end_epoch)

    @property
    def width(self) -> float | None:
        if self.start_epoch is None or self.end_epoch is None:
            return None
        return self.end_epoch - self.start_epoch

    def range_for_refresh(self, latest_epoch: float) -> tuple[float, float] | None:
        width = self.width
        if width is None:
            return None
        if not self.live:
            return self.start_epoch, self.end_epoch
        return latest_epoch - width, latest_epoch
