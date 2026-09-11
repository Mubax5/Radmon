from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import time
from typing import Any


class WhatsAppAlarmDispatcher:
    """Dispatch operator-facing policy ALARMs exactly once.

    The legacy raw-mirror fallback remains for old adapters/tests, but central
    runtime wiring passes AlarmPolicyService and therefore never sends directly
    from source/backfill alarm rows.
    """

    def __init__(self, policy, sender, *, now=None) -> None:
        self.policy = policy
        self.sender = sender
        self.now = now or datetime.now

    @staticmethod
    def _message(item: dict[str, Any]) -> str:
        when = item.get("surfaced_at", item.get("event_time"))
        when_text = when.strftime("%Y-%m-%d %H:%M:%S") if hasattr(when, "strftime") else str(when)
        measured = item.get("measured_value")
        threshold = item.get("threshold")
        measured_text = "-" if measured is None else f"{float(measured):.2f}"
        threshold_text = "-" if threshold is None else f"{float(threshold):.2f}"
        trigger_index = item.get("trigger_index")
        trigger = f" #{int(trigger_index)}" if trigger_index is not None else ""
        source = item.get("source_id") or "central"
        return (
            f"[{source}] ALARM RadMon{trigger} {when_text} WIB, "
            f"[serid:{item.get('serid')}]: {measured_text} µSv/h >= "
            f"{threshold_text} µSv/h"
        )

    def _run_policy_once(self) -> int:
        sent = 0
        for item in self.policy.list_events(
            active_only=True, notify_pending_only=True, limit=500
        ):
            if str(item.get("kind")) != "ALARM":
                continue
            if str(item.get("status")) != "ACTIVE":
                continue
            if item.get("notification_sent_at") is not None:
                continue
            try:
                self.sender.send(self._message(item))
            except Exception:
                continue
            self.policy.mark_notification_sent(str(item["event_id"]), self.now())
            sent += 1
        return sent

    def _run_legacy_once(self) -> int:
        sent = 0
        for item in reversed(self.policy.list_alarms(limit=500)):
            if item.get("level") not in {"ALERT", "ALARM"}:
                continue
            if item.get("notification_sent_at") is not None:
                continue
            try:
                self.sender.send(self._message(item))
            except Exception:
                continue
            self.policy.mark_notification_sent(
                str(item["source_id"]), int(item["serid"]), item["event_time"], self.now(),
            )
            sent += 1
        return sent

    def run_once(self) -> int:
        if hasattr(self.policy, "list_events"):
            return self._run_policy_once()
        return self._run_legacy_once()


class SeleniumWhatsAppSender:
    """Optional Windows WhatsApp Web sender based on the supplied legacy bot pattern."""

    def __init__(self, *, group: str, profile_dir: Path | str, driver_path: Path | str | None = None) -> None:
        self.group = group
        self.profile_dir = Path(profile_dir)
        self.driver_path = Path(driver_path) if driver_path else None
        self.driver = None

    @classmethod
    def from_env(cls):
        group = os.getenv("RADMON_WHATSAPP_GROUP", "Alarm_Radmon").strip()
        profile = Path(os.getenv("RADMON_WHATSAPP_PROFILE", "runtime/whatsapp-profile"))
        driver = os.getenv("RADMON_WHATSAPP_DRIVER", "").strip() or None
        return cls(group=group, profile_dir=profile, driver_path=driver)

    def _ensure_driver(self):
        if self.driver is not None:
            return self.driver
        from selenium import webdriver
        from selenium.webdriver.chrome.service import Service

        self.profile_dir.mkdir(parents=True, exist_ok=True)
        options = webdriver.ChromeOptions()
        options.add_argument(f"--user-data-dir={self.profile_dir.resolve()}")
        options.add_argument("--disable-notifications")
        options.add_argument("--no-first-run")
        options.add_argument("--no-default-browser-check")
        service = Service(executable_path=str(self.driver_path)) if self.driver_path else Service()
        self.driver = webdriver.Chrome(service=service, options=options)
        self.driver.get("https://web.whatsapp.com/")
        return self.driver

    def send(self, message: str) -> None:
        from selenium.webdriver.common.by import By
        from selenium.webdriver.common.keys import Keys

        driver = self._ensure_driver()
        deadline = time.time() + 60
        target = None
        while time.time() < deadline and target is None:
            for element in driver.find_elements(By.XPATH, '//span[@title]'):
                if element.get_attribute("title") == self.group:
                    target = element
                    break
            if target is None:
                time.sleep(1)
        if target is None:
            raise RuntimeError(f"WhatsApp group tidak ditemukan: {self.group}")
        target.click()
        time.sleep(0.5)
        composer = None
        for element in driver.find_elements(By.XPATH, '//footer//div[@contenteditable="true" and @role="textbox"]'):
            if element.is_displayed():
                composer = element
                break
        if composer is None:
            raise RuntimeError("WhatsApp message composer tidak ditemukan")
        composer.click()
        composer.send_keys(message)
        composer.send_keys(Keys.ENTER)
