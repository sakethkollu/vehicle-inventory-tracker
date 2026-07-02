from vehicle_inventory.db.sql_compat import adapt_sql, clamp_acos_arg, haversine_miles_sql, table_exists_sql


def test_adapt_sql_replaces_placeholders():
    assert adapt_sql("SELECT ? FROM t WHERE id = ?") == "SELECT %s FROM t WHERE id = %s"


def test_adapt_sql_replaces_insert_or_replace():
    sql = adapt_sql("INSERT OR REPLACE INTO foo (a) VALUES (?)")
    assert "REPLACE INTO foo" in sql
    assert "INSERT OR REPLACE" not in sql


def test_adapt_sql_on_conflict_to_duplicate_key():
    sql = adapt_sql("INSERT INTO t (a) VALUES (?) ON CONFLICT(a) DO UPDATE SET a = excluded.a")
    assert "ON DUPLICATE KEY UPDATE" in sql
    assert "VALUES(a)" in sql


def test_adapt_sql_escapes_literal_percent():
    sql = adapt_sql("SELECT COUNT(*) FROM t WHERE name LIKE '100%' AND id = ?")
    assert "100%%" in sql
    assert "%s" in sql


def test_table_exists_sql_uses_information_schema():
    assert "INFORMATION_SCHEMA.TABLES" in table_exists_sql()
    assert "%s" in table_exists_sql()


def test_clamp_acos_arg_bounds_expression():
    assert clamp_acos_arg("x") == "LEAST(1.0, GREATEST(-1.0, (x)))"


def test_haversine_miles_sql_contains_acos_and_columns():
    sql = haversine_miles_sql(":lat", ":lng")
    assert "3959.0 * acos" in sql
    assert ":lat" in sql
    assert "dgc.latitude" in sql
