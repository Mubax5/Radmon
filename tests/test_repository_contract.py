from __future__ import annotations

from datetime import datetime

from radmon.config import Settings
from radmon.models import Measurement
from radmon.repository import make_sample_key


def test_sample_key_is_stable_and_changes_when_measurement_changes():
    one = Measurement(5201, datetime(2026, 9, 7, 10, 0, 0), 0.123, 2, 0)
    two = Measurement(5201, datetime(2026, 9, 7, 10, 0, 2), 0.123, 2, 0)
    assert make_sample_key(one) == make_sample_key(one)
    assert make_sample_key(one) != make_sample_key(two)
    assert len(make_sample_key(one)) == 64


def test_dummy_profile_is_is1_koridor_5202():
    dummy = Settings().for_dummy()
    assert dummy.serid == 5202
    assert dummy.room == "IS-1 Koridor"
    assert dummy.location == "Gd.52"
    assert dummy.warnlevel == 8
    assert dummy.alarmlevel == 10
