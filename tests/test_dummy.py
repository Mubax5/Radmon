from radmon.dummy import DummyDoseGenerator


def test_normal_dummy_stays_below_warning():
    generator = DummyDoseGenerator("normal", seed=7, warnlevel=8, alarmlevel=10)
    values = [generator.next_value() for _ in range(200)]
    assert min(values) >= 0
    assert max(values) < 8


def test_alert_and_alarm_modes_hit_expected_bands():
    alert = DummyDoseGenerator("alert", seed=1, warnlevel=8, alarmlevel=10)
    alarm = DummyDoseGenerator("alarm", seed=1, warnlevel=8, alarmlevel=10)
    assert all(8 <= alert.next_value() < 10 for _ in range(50))
    assert all(alarm.next_value() >= 10 for _ in range(50))


def test_mixed_mode_remains_non_negative_and_can_reproduce_with_seed():
    first = DummyDoseGenerator("mixed", seed=123, warnlevel=8, alarmlevel=10)
    second = DummyDoseGenerator("mixed", seed=123, warnlevel=8, alarmlevel=10)
    values1 = [first.next_value() for _ in range(100)]
    values2 = [second.next_value() for _ in range(100)]
    assert values1 == values2
    assert min(values1) >= 0
