from unittest.mock import MagicMock

import pytest

from vehicle_inventory.db.backend import _is_deadlock_error, execute_with_retry


def test_is_deadlock_error_detects_mysql_code():
    assert _is_deadlock_error(Exception("(1213, 'Deadlock found')")) is True
    assert _is_deadlock_error(Exception("deadlock found when trying to get lock")) is True
    assert _is_deadlock_error(Exception("connection lost")) is False


def test_execute_with_retry_recovers_from_deadlock(monkeypatch):
    conn = MagicMock()
    deadlock = Exception("(1213, 'Deadlock found when trying to get lock')")
    conn.execute.side_effect = [deadlock, conn]

    monkeypatch.setattr("vehicle_inventory.db.backend.time.sleep", lambda _sec: None)
    result = execute_with_retry(conn, "UPDATE t SET a = ?", (1,))
    assert result is conn
    assert conn.execute.call_count == 2


def test_execute_with_retry_raises_after_exhausting_attempts(monkeypatch):
    conn = MagicMock()
    deadlock = Exception("1213 deadlock")
    conn.execute.side_effect = deadlock

    monkeypatch.setattr("vehicle_inventory.db.backend.time.sleep", lambda _sec: None)
    with pytest.raises(Exception, match="1213"):
        execute_with_retry(conn, "UPDATE t SET a = ?", (1,), attempts=2)
