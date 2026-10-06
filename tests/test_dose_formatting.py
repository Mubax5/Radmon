from radmon.formatting import format_dose_value


def test_dose_formatter_rounds_to_exactly_two_fractional_digits():
    assert format_dose_value("0.3") == "0.30"
    assert format_dose_value("0.120") == "0.12"
    assert format_dose_value("0.833333") == "0.83"
    assert format_dose_value("1.2") == "1.20"
    assert format_dose_value("1.005") == "1.01"
    assert format_dose_value("0") == "0.00"
    assert format_dose_value(12) == "12.00"
