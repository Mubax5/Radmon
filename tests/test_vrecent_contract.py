from pathlib import Path

from radmon.stations import station_catalog


def test_production_station_ids_match_live_databases():
    ids = {station.serid for station in station_catalog()}
    assert 3003 in ids
    assert 5501 in ids
    assert 3009 not in ids
    assert 5601 not in ids


def test_live_monitoring_sql_uses_vrecent_not_latest_measurement_scan():
    repository = Path("radmon/repository_revision.py").read_text(encoding="utf-8")
    grafana = Path("radmon/grafana_revision.py").read_text(encoding="utf-8")
    recent_page = Path("radmon/admin/recent_page.py").read_text(encoding="utf-8")

    assert "FROM vrecent" in repository
    assert "FROM vrecent" in grafana
    assert "measurement_history(" not in recent_page


def test_production_schema_columns_are_the_runtime_contract():
    repository = Path("radmon/repository_revision.py").read_text(encoding="utf-8")
    assert '"vrecent"' in repository
    assert '"dtoa"' in repository
    assert '"lvl"' in repository
    assert '"mvalue"' in repository
    assert '"thvalue"' in repository
    assert '"nhit"' in repository
    assert '"ts"' in repository
    assert '"val"' in repository
