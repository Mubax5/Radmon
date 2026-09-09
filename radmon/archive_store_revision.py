"""Production schema compatibility for quarterly archive reads/purges."""
from __future__ import annotations

from datetime import datetime


def apply() -> None:
    from . import archive_store as module

    module.TABLE_COLUMNS.update({
        "alarm": ("serid", "dtoa", "lvl", "mvalue", "thvalue", "nhit", "ack", "pic", "note", "i_op", "i_flag"),
        "rawdata": ("serid", "dtom", "val"),
        "applog": ("ts", "id", "msg"),
        "news": ("ts", "code", "content"),
    })
    module.TIME_COLUMNS.update({
        "alarm": "dtoa",
        "rawdata": "dtom",
        "applog": "ts",
        "news": "ts",
    })

    original_monthly_recap_rows = module.CentralArchiveStore.monthly_recap_rows

    def monthly_recap_rows(self, quarter):
        # Reuse the stable measurement aggregation implementation, but present
        # legacy production alarm rows under the semantic keys it expects.
        original_table_rows = self.table_rows

        def compatible_rows(table, selected_quarter, *, chunk_size=5000):
            rows = original_table_rows(table, selected_quarter, chunk_size=chunk_size)
            if table != "alarm":
                yield from rows
                return
            for row in rows:
                item = dict(row)
                item["dtom"] = item.get("dtoa")
                item["type"] = "ALARM" if int(item.get("lvl") or 0) >= 2 else "ALERT"
                yield item

        self.table_rows = compatible_rows
        try:
            return original_monthly_recap_rows(self, quarter)
        finally:
            self.table_rows = original_table_rows

    module.CentralArchiveStore.monthly_recap_rows = monthly_recap_rows
