from radmon.security import SecurityStore


def test_archive_state_survives_store_reopen(tmp_path):
    path = tmp_path / "security.db"
    store = SecurityStore(path)
    store.upsert_archive(
        quarter_id="2026-Q3",
        start_at="2026-07-01T00:00:00+07:00",
        end_at="2026-10-01T00:00:00+07:00",
        state="OPEN",
    )
    store.update_archive_state("2026-Q3", "EXPORTING", last_error=None)
    reopened = SecurityStore(path)
    row = reopened.get_archive("2026-Q3")
    assert row["state"] == "EXPORTING"
    assert row["quarter_id"] == "2026-Q3"
