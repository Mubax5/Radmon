from radmon.formatting import format_dose_value


def test_dose_formatter_removes_only_insignificant_zeroes():
    assert format_dose_value("1.340") == "1.34"
    assert format_dose_value("11.230") == "11.23"
    assert format_dose_value("0.833333333") == "0.833333333"
    assert format_dose_value("0") == "0"
    assert format_dose_value(12) == "12"
