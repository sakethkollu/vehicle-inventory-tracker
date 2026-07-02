"""MySQL SQL helpers."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from vehicle_inventory.db.backend import DbConnection


def adapt_sql(sql: str) -> str:
    """Adapt legacy placeholder/upsert syntax to MySQL."""
    sql = sql.replace("?", "%s")
    sql = re.sub(r"\bINSERT OR REPLACE\b", "REPLACE", sql, flags=re.IGNORECASE)
    sql = re.sub(r"\bCOLLATE NOCASE\b", "", sql, flags=re.IGNORECASE)
    sql = re.sub(
        r"ON CONFLICT\([^)]+\)\sDO UPDATE SET\s",
        "ON DUPLICATE KEY UPDATE ",
        sql,
        flags=re.IGNORECASE,
    )
    sql = re.sub(r"\bexcluded\.(\w+)", r"VALUES(\1)", sql)
    sql = re.sub(
        r"\bCREATE TEMP TABLE\b",
        "CREATE TEMPORARY TABLE",
        sql,
        flags=re.IGNORECASE,
    )
    return _escape_mysql_percent_literals(sql)


def _escape_mysql_percent_literals(sql: str) -> str:
    """PyMySQL uses printf-style formatting; literal % in SQL must be doubled."""
    parts = re.split(r"(%s)", sql)
    return "".join(part if part == "%s" else part.replace("%", "%%") for part in parts)


def table_exists_sql() -> str:
    return (
        "SELECT TABLE_NAME AS name FROM INFORMATION_SCHEMA.TABLES "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s"
    )


def ensure_index(
    conn: DbConnection,
    *,
    name: str,
    table: str,
    columns: str,
) -> None:
    row = conn.execute(
        "SELECT 1 AS ok FROM INFORMATION_SCHEMA.STATISTICS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND INDEX_NAME = %s",
        (table, name),
    ).fetchone()
    if row:
        return
    conn.execute(f"CREATE INDEX {name} ON {table}({columns})")


def clamp_acos_arg(expr: str) -> str:
    return f"LEAST(1.0, GREATEST(-1.0, ({expr})))"


def haversine_miles_sql(
    lat_param: str,
    lng_param: str,
    *,
    lat_col: str = "dgc.latitude",
    lng_col: str = "dgc.longitude",
) -> str:
    cosine_sum = (
        f"cos(radians({lat_param})) * cos(radians({lat_col}))"
        f" * cos(radians({lng_col}) - radians({lng_param}))"
        f" + sin(radians({lat_param})) * sin(radians({lat_col}))"
    )
    return f"3959.0 * acos({clamp_acos_arg(cosine_sum)})"
