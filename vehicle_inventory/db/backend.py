"""MySQL database connection layer."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, List, Mapping, Optional, Sequence, Union
from urllib.parse import urlparse

from vehicle_inventory.db.sql_compat import adapt_sql

Params = Union[Sequence[Any], Mapping[str, Any], None]


@dataclass
class DbRow:
    _mapping: Mapping[str, Any]

    def __getitem__(self, key: str) -> Any:
        return self._mapping[key]

    def keys(self):
        return self._mapping.keys()

    def __iter__(self):
        return iter(self._mapping)

    def __contains__(self, key: object) -> bool:
        return key in self._mapping


class DbConnection:
    dialect: str = "mysql"

    def execute(self, sql: str, params: Params = ()) -> "DbConnection":
        raise NotImplementedError

    def fetchone(self) -> Optional[DbRow]:
        raise NotImplementedError

    def fetchall(self) -> List[DbRow]:
        raise NotImplementedError

    @property
    def lastrowid(self) -> int:
        raise NotImplementedError

    @property
    def rowcount(self) -> int:
        raise NotImplementedError

    def commit(self) -> None:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError

    def executescript(self, script: str) -> None:
        raise NotImplementedError


class MySQLDbConnection(DbConnection):
    dialect = "mysql"

    def __init__(self, conn):
        self._conn = conn
        self._cursor = None

    def execute(self, sql: str, params: Params = ()) -> "MySQLDbConnection":
        adapted = adapt_sql(sql)
        self._cursor = self._conn.cursor()
        self._cursor.execute(adapted, params or ())
        return self

    def fetchone(self) -> Optional[DbRow]:
        if self._cursor is None:
            return None
        row = self._cursor.fetchone()
        if row is None:
            return None
        columns = [col[0] for col in self._cursor.description or []]
        return DbRow(dict(zip(columns, row)))

    def fetchall(self) -> List[DbRow]:
        if self._cursor is None:
            return []
        rows = self._cursor.fetchall()
        columns = [col[0] for col in self._cursor.description or []]
        return [DbRow(dict(zip(columns, row))) for row in rows]

    @property
    def lastrowid(self) -> int:
        return int(self._cursor.lastrowid if self._cursor is not None else 0)

    @property
    def rowcount(self) -> int:
        return int(self._cursor.rowcount if self._cursor is not None else 0)

    def commit(self) -> None:
        self._conn.commit()

    def close(self) -> None:
        if self._cursor is not None:
            self._cursor.close()
        self._conn.close()

    def executescript(self, script: str) -> None:
        statements = [part.strip() for part in script.split(";") if part.strip()]
        for statement in statements:
            try:
                self.execute(statement)
            except Exception as exc:
                message = str(exc).lower()
                if "duplicate key name" in message or "already exists" in message:
                    continue
                raise
        self.commit()


def open_db_connection(database_url: str, *, readonly: bool = False) -> DbConnection:
    _ = readonly  # MySQL uses a single read/write connection pool semantics in this app.
    if not database_url.startswith("mysql"):
        raise ValueError(f"Unsupported DATABASE_URL (MySQL required): {database_url}")

    import pymysql

    parsed = urlparse(database_url)
    db_name = parsed.path.lstrip("/")
    conn = pymysql.connect(
        host=parsed.hostname or "localhost",
        port=parsed.port or 3306,
        user=parsed.username or "root",
        password=parsed.password or "",
        database=db_name,
        charset="utf8mb4",
        autocommit=False,
        cursorclass=pymysql.cursors.Cursor,
    )
    return MySQLDbConnection(conn)


def fetchall_with_retry(
    conn: DbConnection,
    sql: str,
    params=(),
    *,
    attempts: int = 6,
) -> List[DbRow]:
    delay_sec = 0.05
    for attempt in range(attempts):
        try:
            return conn.execute(sql, params).fetchall()
        except Exception as exc:
            if not _is_deadlock_error(exc) or attempt >= attempts - 1:
                raise
            time.sleep(delay_sec)
            delay_sec = min(delay_sec * 2, 1.0)
    return []


def _is_deadlock_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return "deadlock" in message or "1213" in message


def execute_with_retry(
    conn: DbConnection,
    sql: str,
    params=(),
    *,
    attempts: int = 6,
) -> DbConnection:
    delay_sec = 0.05
    for attempt in range(attempts):
        try:
            return conn.execute(sql, params)
        except Exception as exc:
            if not _is_deadlock_error(exc) or attempt >= attempts - 1:
                raise
            time.sleep(delay_sec)
            delay_sec = min(delay_sec * 2, 1.0)
    return conn


def commit_with_retry(conn: DbConnection, *, attempts: int = 6) -> None:
    delay_sec = 0.05
    for attempt in range(attempts):
        try:
            conn.commit()
            return
        except Exception as exc:
            if not _is_deadlock_error(exc) or attempt >= attempts - 1:
                raise
            time.sleep(delay_sec)
            delay_sec = min(delay_sec * 2, 1.0)


def run_transaction_with_retry(conn: DbConnection, fn, *, attempts: int = 6) -> None:
    """Run ``fn`` inside a transaction, retrying the whole unit on MySQL deadlocks."""
    delay_sec = 0.05
    for attempt in range(attempts):
        try:
            fn()
            commit_with_retry(conn, attempts=attempts)
            return
        except Exception as exc:
            if not _is_deadlock_error(exc) or attempt >= attempts - 1:
                raise
            try:
                conn.rollback()
            except Exception:
                pass
            time.sleep(delay_sec)
            delay_sec = min(delay_sec * 2, 1.0)


def fetchone_with_retry(
    conn: DbConnection,
    sql: str,
    params=(),
    *,
    attempts: int = 6,
) -> Optional[DbRow]:
    rows = fetchall_with_retry(conn, sql, params, attempts=attempts)
    return rows[0] if rows else None
