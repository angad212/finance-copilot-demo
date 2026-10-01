import pytest

from sql_guard import SQLRejected, make_safe_sql


def safe(sql, uid=7):
    return make_safe_sql(sql, uid, "sqlite", 200)


def test_select_is_allowed_and_scoped_to_user():
    out = safe("SELECT SUM(debit) FROM transaction_lines")
    assert "user_id = 7" in out


def test_alias_and_join_survive_scoping():
    out = safe("SELECT t.id FROM transactions t JOIN accounts a ON a.user_id = t.user_id")
    assert out.count("user_id = 7") == 2


def test_cte_names_are_not_treated_as_tables():
    assert "user_id = 7" in safe("WITH t AS (SELECT * FROM transactions) SELECT COUNT(*) FROM t")


@pytest.mark.parametrize("sql", [
    "DROP TABLE transactions",
    "DELETE FROM transactions",
    "UPDATE accounts SET name = 'x'",
    "INSERT INTO accounts (name) VALUES ('x')",
    "SELECT 1; DROP TABLE users",
    "SELECT * FROM users",
    "SELECT * FROM pg_catalog.pg_tables",
    "SELECT pg_sleep(10)",
    "WITH x AS (DELETE FROM transactions RETURNING id) SELECT * FROM x",
    "",
    "not sql at all",
])
def test_dangerous_or_invalid_sql_is_rejected(sql):
    with pytest.raises(SQLRejected):
        safe(sql)


def test_limit_is_added_and_capped():
    assert "LIMIT 200" in safe("SELECT * FROM transactions")
    assert "LIMIT 200" in safe("SELECT * FROM transactions LIMIT 100000")
    assert "LIMIT 5" in safe("SELECT * FROM transactions LIMIT 5")
