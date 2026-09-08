from datetime import datetime
from zoneinfo import ZoneInfo

from radmon.quarters import previous_quarter, quarter_for, quarters_overlapping

WIB = ZoneInfo("Asia/Jakarta")


def test_q3_2026_boundaries_are_calendar_wib():
    q = quarter_for(datetime(2026, 9, 8, 20, 0, tzinfo=WIB))
    assert q.quarter_id == "2026-Q3"
    assert q.start == datetime(2026, 7, 1, 0, 0, tzinfo=WIB)
    assert q.end == datetime(2026, 10, 1, 0, 0, tzinfo=WIB)
    assert q.month_names == ("July", "August", "September")


def test_q4_previous_rolls_across_year_boundary():
    q = previous_quarter(datetime(2027, 1, 1, 0, 1, tzinfo=WIB))
    assert q.quarter_id == "2026-Q4"
    assert q.start == datetime(2026, 10, 1, 0, 0, tzinfo=WIB)
    assert q.end == datetime(2027, 1, 1, 0, 0, tzinfo=WIB)


def test_overlapping_quarters_uses_half_open_ranges():
    values = quarters_overlapping(
        datetime(2026, 9, 30, 23, 59, tzinfo=WIB),
        datetime(2026, 10, 1, 0, 1, tzinfo=WIB),
    )
    assert [q.quarter_id for q in values] == ["2026-Q3", "2026-Q4"]
