import csv
import hashlib
import io
import json
import zipfile

from radmon.archive_exports import ArchiveExportJobs
from radmon.archive_store import TABLE_COLUMNS


class Security:
    def __init__(self, path):
        import sqlite3
        self.path = path

    def _connection(self):
        import sqlite3
        return sqlite3.connect(self.path)


class Catalog:
    def __init__(self, records):
        self.records = records

    def list_archives(self, limit=1000):
        return self.records[:limit]


def make_archive(root, quarter, rows):
    path = root / str(quarter[:4]) / f"radmon-{quarter}.zip"
    path.parent.mkdir(parents=True, exist_ok=True)
    sql_name = f"radmon-{quarter}.sql"
    sql = "-- bundle\nSTART TRANSACTION;\nINSERT INTO device (serid) VALUES (1);\n"
    sql += "".join(f"INSERT INTO measurement (serid) VALUES ({row});\n" for row in rows)
    sql += "COMMIT;\n"
    payload = {sql_name: sql.encode()}
    counts = {"device": 1, "measurement": len(rows), "alarm": 0, "rawdata": 0, "applog": 0, "news": 0}
    for table, columns in TABLE_COLUMNS.items():
        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=columns)
        writer.writeheader()
        table_rows = [{columns[0]: 1}] if table == "device" else ([{"serid": 1, "dtom": "2024-01-01", "doserate": row, "dose": 0} for row in rows] if table == "measurement" else [])
        for row in table_rows:
            writer.writerow(row)
        payload[f"{table}.csv"] = output.getvalue().encode()
    payload["monthly-recap.csv"] = b"year,month,serid,name,location,first_measurement,last_measurement,sample_count,minimum,average,maximum,dose_sum,rate_sum,alert_count,alarm_count\n"
    manifest = {"quarter_id": quarter, "row_counts": counts,
                "files": {name: {"sha256": hashlib.sha256(data).hexdigest()} for name, data in payload.items()}}
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        for name, data in payload.items():
            zf.writestr(name, data)
    return {"quarter_id": quarter, "state": "COMPLETE", "archive_path": str(path), "row_counts": counts}


def make_jobs(tmp_path, records):
    jobs = ArchiveExportJobs(Security(tmp_path / "security.db"), Catalog(records), tmp_path / "archives")
    class DeferredExecutor:
        def submit(self, *_args, **_kwargs):
            pass
        def shutdown(self, **_kwargs):
            pass
    jobs._executor.shutdown(wait=True)
    jobs._executor = DeferredExecutor()
    return jobs


def test_inventory_year_filters_and_counts(tmp_path):
    first = make_archive(tmp_path / "archives", "2024-Q1", [1, 2])
    second = make_archive(tmp_path / "archives", "2025-Q2", [3])
    jobs = make_jobs(tmp_path, [first, second])
    assert jobs.inventory()["years"] == [{"year": 2025, "archive_count": 1}, {"year": 2024, "archive_count": 1}]
    assert jobs.select_archives("year", "2024") == [first]
    assert jobs.select_archives("all") == [first, second]


def test_merge_integrity_and_progress_is_monotonic(tmp_path):
    first = make_archive(tmp_path / "archives", "2024-Q1", [1, 2])
    second = make_archive(tmp_path / "archives", "2024-Q2", [3])
    jobs = make_jobs(tmp_path, [first, second])
    progress = []
    job = jobs.create(type("User", (), {"username": "operator"})(), selection="all", value=None)
    jobs._generate(job["job_id"], lambda item: progress.append(item.copy()))
    item, path = jobs.artifact(job["job_id"])
    sql = path.read_text(encoding="utf-8")
    assert sql.count("INSERT INTO device") == 1
    assert sql.count("INSERT INTO measurement") == 3
    assert sql.count("START TRANSACTION") == 1
    assert sql.count("COMMIT;") == 1
    assert [entry["bytes_written"] for entry in progress] == sorted(entry["bytes_written"] for entry in progress)
    assert [entry["partitions_read"] for entry in progress] == sorted(entry["partitions_read"] for entry in progress)
    assert [entry["rows_read"] for entry in progress] == sorted(entry["rows_read"] for entry in progress)
    assert item["rows_read"] == 4


def test_archive_selection_rejects_traversal_and_only_complete_archives(tmp_path):
    complete = make_archive(tmp_path / "archives", "2024-Q1", [1])
    incomplete = dict(make_archive(tmp_path / "archives", "2024-Q2", [2]), state="DAMAGED")
    jobs = make_jobs(tmp_path, [complete, incomplete])
    assert jobs.select_archives("single", "2024-Q1") == [complete]
    import pytest
    with pytest.raises(ValueError):
        jobs.select_archives("year", "../2024")
    with pytest.raises(ValueError):
        jobs.select_archives("single", "2024-Q2")


def test_merge_errors_are_persisted(tmp_path):
    archive = make_archive(tmp_path / "archives", "2024-Q1", [1])
    jobs = make_jobs(tmp_path, [archive])
    job = jobs.create(type("User", (), {"username": "operator"})(), selection="all", value=None)
    archive["archive_path"] = str(tmp_path / "outside.zip")
    jobs.catalog.records = [archive]
    jobs._generate(job["job_id"], lambda _item: None)
    assert jobs.get(job["job_id"])["status"] == "failed"
