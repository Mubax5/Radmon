from datetime import datetime

from radmon.config import Settings
from radmon.report_queries import DatabaseReportSummaryReader


class Cursor:
    def __init__(self):
        self.sql = None
        self.params = None
        self.rows = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params):
        self.sql = sql
        self.params = params

    def fetchone(self):
        return {
            "first_measurement": datetime(2026, 9, 1, 0, 0),
            "last_measurement": datetime(2026, 9, 2, 0, 0),
            "minimum": 0.1,
            "average": 0.2,
            "maximum": 0.3,
            "sample_count": 43200,
            "approximate_dose": 4.8,
        }

    def fetchall(self):
        return self.rows


class Connection:
    def __init__(self):
        self.cursor_instance = Cursor()
        self.closed = False

    def cursor(self):
        return self.cursor_instance

    def close(self):
        self.closed = True


def test_database_summary_reader_aggregates_full_range_in_sql():
    connection = Connection()
    reader = DatabaseReportSummaryReader(
        Settings(), connection_factory=lambda: connection
    )
    start = datetime(2026, 9, 1, 0, 0)
    end = datetime(2026, 9, 2, 0, 0)
    row = reader.summary(start, end, serid=5202)
    sql = connection.cursor_instance.sql
    assert "MIN(dtom)" in sql
    assert "AVG(doserate)" in sql
    assert "COUNT(doserate)" in sql
    assert "SUM(COALESCE(dose, 0))" in sql
    assert connection.cursor_instance.params == (5202, start, end)
    assert row["sample_count"] == 43200
    assert connection.closed


def test_database_report_detail_reader_has_its_own_bounded_ordered_query():
    connection = Connection()
    reader = DatabaseReportSummaryReader(
        Settings(), connection_factory=lambda: connection
    )
    start = datetime(2026, 9, 1, 0, 0)
    end = datetime(2026, 9, 2, 0, 0)
    assert reader.measurement_rows(start, end, serid=5202, limit=50_001) == []
    sql = connection.cursor_instance.sql
    assert "FROM measurement" in sql
    assert "ORDER BY dtom ASC, serid ASC" in sql
    assert "LIMIT ?" in sql
    assert connection.cursor_instance.params == (5202, start, end, 50_001)
    assert connection.closed
