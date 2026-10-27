import sqlite3
import time

from advisory_agents.storage import Store


def test_public_record_read_does_not_compete_for_writer_reservation(tmp_path):
    store = Store(tmp_path / "records.sqlite3")
    store.put("run", "synthetic", {"status": "RUNNING"})
    writer = sqlite3.connect(store.path)
    try:
        writer.execute("BEGIN IMMEDIATE")
        started = time.monotonic()
        assert store.get("run", "synthetic") == {"status": "RUNNING"}
        assert time.monotonic() - started < 0.5
    finally:
        writer.rollback()
        writer.close()
