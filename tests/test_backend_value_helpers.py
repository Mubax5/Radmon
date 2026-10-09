from datetime import datetime, timezone

from radmon.datetime_utils import parse_database_datetime
from radmon.db import database_row_value
from radmon.formatting import normalize_dose_unit


def test_database_datetime_parser_accepts_driver_values_and_rejects_missing_text():
    expected = datetime(2026, 9, 28, 14, 3)

    assert parse_database_datetime(expected) is expected
    assert parse_database_datetime("2026-09-28 14:03:00") == expected
    assert parse_database_datetime("2026-09-28T14:03:00+00:00") == expected.replace(tzinfo=timezone.utc)
    assert parse_database_datetime(" ") is None
    assert parse_database_datetime("not a datetime") is None


def test_database_row_value_handles_mapping_and_positional_driver_rows():
    assert database_row_value({"serid": 5201}, "serid", 0) == 5201
    assert database_row_value((5201,), "serid", 0) == 5201
    assert database_row_value(None, "serid", 0) is None


def test_dose_unit_normalization_preserves_custom_units_and_canonicalizes_usv():
    assert normalize_dose_unit("uSv/h") == "µSv/h"
    assert normalize_dose_unit("μSv/h") == "µSv/h"
    assert normalize_dose_unit("counts/s") == "counts/s"
    assert normalize_dose_unit(None) == "µSv/h"
