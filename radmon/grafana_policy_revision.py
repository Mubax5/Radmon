"""Project central alarm-policy state into the final WIB Grafana builders."""
from __future__ import annotations

from typing import Any, Sequence


def apply() -> None:
    from . import grafana_tv as tv

    def status_relation(stations: Sequence | None = None) -> str:
        ids = tv._station_ids(stations)
        wib_now = "CONVERT_TZ(UTC_TIMESTAMP(), '+00:00', '+07:00')"
        return f"""
SELECT
  v.serid,
  v.name,
  v.location,
  v.warnlevel,
  v.alarmlevel,
  COALESCE(v.maxidlemin, 30) AS maxidlemin,
  v.dtom,
  v.doserate,
  COALESCE(
    r.underlying_dose_status,
    CASE
      WHEN v.doserate >= v.alarmlevel THEN 'ALARM'
      WHEN v.doserate >= v.warnlevel THEN 'ALERT'
      ELSE 'NORMAL'
    END
  ) AS underlying_status,
  CASE
    WHEN v.dtom IS NULL OR v.doserate IS NULL THEN 'OFFLINE'
    WHEN TIMESTAMPDIFF(SECOND, v.dtom, {wib_now}) > COALESCE(v.maxidlemin, 30) * 60 THEN 'OFFLINE'
    WHEN COALESCE(r.suppressed, 0) = 1 THEN 'SUPPRESSED'
    WHEN v.doserate >= v.alarmlevel THEN 'ALARM'
    WHEN v.doserate >= v.warnlevel THEN 'ALERT'
    ELSE 'NORMAL'
  END AS status,
  COALESCE(r.trigger_count, 0) AS trigger_count,
  COALESCE(r.retrigger_locked, 0) AS retrigger_locked,
  r.suppression_expires_at,
  r.suppression_pic,
  r.suppression_reason
FROM vrecent v
LEFT JOIN radmon_runtime_status r ON r.serid = v.serid
WHERE v.serid IN ({ids})
""".strip()

    def operation_table(
        panel_id: int,
        title: str,
        x: int,
        y: int,
        w: int,
        h: int,
        *,
        stations: Sequence | None = None,
    ) -> dict[str, Any]:
        relation = status_relation(stations)
        table = tv._panel(panel_id, "table", title, x, y, w, h)
        table["description"] = "operational-condition"
        table["targets"] = [tv._target(f"""
SELECT
  s.serid AS `ID`,
  s.name AS `Ruangan`,
  s.location AS `Lokasi`,
  ROUND(s.doserate, 3) AS `Dose Rate`,
  DATE_FORMAT(s.dtom, '%Y-%m-%d %H:%i:%s') AS `Waktu`,
  s.status AS `Status`,
  s.underlying_status AS `Underlying`,
  s.trigger_count AS `Trigger`,
  CASE WHEN s.retrigger_locked = 1 THEN 'LOCKED' ELSE '' END AS `Retrigger`,
  DATE_FORMAT(s.suppression_expires_at, '%Y-%m-%d %H:%i:%s') AS `Suppression Until`,
  COALESCE(s.suppression_pic, '') AS `PIC`,
  COALESCE(s.suppression_reason, '') AS `Reason`
FROM ({relation}) s
ORDER BY FIELD(s.status, 'OFFLINE', 'SUPPRESSED', 'ALARM', 'ALERT', 'NORMAL'), s.serid
""")]
        table["fieldConfig"] = {
            "defaults": {"custom": {"align": "auto", "cellOptions": {"type": "auto"}}},
            "overrides": [
                {
                    "matcher": {"id": "byName", "options": "Dose Rate"},
                    "properties": [
                        {"id": "unit", "value": "suffix: µSv/h"},
                        {"id": "decimals", "value": 3},
                    ],
                },
                {
                    "matcher": {"id": "byName", "options": "Status"},
                    "properties": [
                        {
                            "id": "mappings",
                            "value": [{
                                "type": "value",
                                "options": {
                                    "NORMAL": {"color": "green", "text": "NORMAL"},
                                    "ALERT": {"color": "orange", "text": "ALERT"},
                                    "ALARM": {"color": "red", "text": "ALARM"},
                                    "OFFLINE": {"color": "purple", "text": "OFFLINE"},
                                    "SUPPRESSED": {"color": "blue", "text": "SUPPRESSED"},
                                },
                            }],
                        },
                        {"id": "custom.cellOptions", "value": {"type": "color-background"}},
                    ],
                },
            ],
        }
        table["options"] = {"cellHeight": "sm", "enablePagination": False, "showHeader": True}
        return table

    tv._status_relation = status_relation
    tv._operation_table = operation_table
