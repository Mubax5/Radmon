from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_production_collector_surface_is_read_only_before_explicit_ack():
    source = (ROOT / "radmon/lan.py").read_text(encoding="utf-8")
    remote = source.split("class RemoteMariaDBSource", 1)[1].split("class MariaCentralStore", 1)[0]
    reads = remote.split("def ack_legacy", 1)[0]
    for verb in ("INSERT ", "UPDATE ", "DELETE ", "TRUNCATE ", "ALTER ", "DROP "):
        assert verb not in reads.upper(), verb
    ack = remote.split("def ack_legacy", 1)[1]
    assert "UPDATE alarm" in ack
    assert "i_op IS NULL" in ack
