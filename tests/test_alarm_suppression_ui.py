from PySide6.QtWidgets import QApplication


def app():
    return QApplication.instance() or QApplication([])


def test_suppression_dialog_defaults_auto_resume_checked():
    app()
    from radmon.admin.suppression_dialog import SuppressionDialog

    dialog = SuppressionDialog(
        serid=5201,
        station_name="IS-1 Gd.52",
        dose_rate=170.0,
        underlying_status="ALARM",
        default_pic="Operator A",
    )
    assert dialog.auto_resume.isChecked() is True
    assert dialog.duration_seconds() == 300
    assert "measurement" in dialog.notice.text().lower()


def test_alarm_page_has_suppress_button_and_policy_columns():
    from radmon.admin.alarm_page import AlarmPage
    assert "Policy" in AlarmPage.HEADERS
    assert "Underlying" in AlarmPage.HEADERS


def test_recent_page_policy_overlay_keeps_dose_visible_contract():
    import inspect
    from radmon.admin.recent_page import RecentPage
    source = inspect.getsource(RecentPage)
    assert "SUPPRESSED" in source
    assert "doserate" in source
