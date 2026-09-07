from __future__ import annotations

import random


class DummyDoseGenerator:
    MODES = {"normal", "alert", "alarm", "mixed"}

    def __init__(
        self,
        mode: str = "mixed",
        *,
        seed: int | None = None,
        warnlevel: float = 8.0,
        alarmlevel: float = 10.0,
    ) -> None:
        normalized = mode.lower().strip()
        if normalized not in self.MODES:
            raise ValueError(f"unsupported dummy mode: {mode}")
        if alarmlevel <= warnlevel:
            raise ValueError("alarmlevel must be greater than warnlevel")
        self.mode = normalized
        self.warnlevel = warnlevel
        self.alarmlevel = alarmlevel
        self.random = random.Random(seed)
        self.current = 0.18
        self._burst_mode = "normal"
        self._burst_remaining = 0

    def _random_walk(self, low: float, high: float, step: float) -> float:
        if self.current < low or self.current > high:
            self.current = self.random.uniform(low, high)
        self.current += self.random.uniform(-step, step)
        self.current = min(high, max(low, self.current))
        return round(self.current, 4)

    def _value_for_mode(self, mode: str) -> float:
        if mode == "normal":
            return self._random_walk(0.05, min(0.35, self.warnlevel - 0.05), 0.025)
        if mode == "alert":
            return self._random_walk(self.warnlevel + 0.10, self.alarmlevel - 0.20, 0.18)
        if mode == "alarm":
            return self._random_walk(self.alarmlevel + 0.10, self.alarmlevel + 2.0, 0.25)
        raise ValueError(mode)

    def next_value(self) -> float:
        if self.mode != "mixed":
            return self._value_for_mode(self.mode)
        if self._burst_remaining <= 0:
            roll = self.random.random()
            if roll < 0.03:
                self._burst_mode = "alarm"
                self._burst_remaining = self.random.randint(2, 5)
            elif roll < 0.10:
                self._burst_mode = "alert"
                self._burst_remaining = self.random.randint(3, 8)
            else:
                self._burst_mode = "normal"
                self._burst_remaining = self.random.randint(5, 20)
        self._burst_remaining -= 1
        return self._value_for_mode(self._burst_mode)
