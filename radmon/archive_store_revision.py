"""Production schema compatibility for quarterly archive reads/purges."""
from __future__ import annotations


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
        # Present production legacy alarm rows under the semantic keys used by
        # the stable recap implementation. Keeping the old aliases accepted as
        # input also preserves deterministic unit tests and older archives.
        original_table_rows = self.table_rows

        def compatible_rows(table, selected_quarter, *, chunk_size=5000):
            rows = original_table_rows(table, selected_quarter, chunk_size=chunk_size)
            if table != "alarm":
                yield from rows
                return
            for row in rows:
                item = dict(row)
                item["dtom"] = item.get("dtoa") or item.get("dtom")
                if "lvl" in item and item.get("lvl") is not None:
                    item["type"] = "ALARM" if int(item.get("lvl") or 0) >= 2 else "ALERT"
                else:
                    item["type"] = str(item.get("type") or "ALERT").upper()
                yield item

        self.table_rows = compatible_rows
        try:
            return original_monthly_recap_rows(self, quarter)
        finally:
            self.table_rows = original_table_rows

    module.CentralArchiveStore.monthly_recap_rows = monthly_recap_rows
