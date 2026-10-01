"""Validate and scope SQL written by an LLM. Uses the SQL parser, not string matching.

Rules:
  * exactly one statement, and it must be a SELECT
  * only whitelisted tables (no schema-qualified names, no system tables)
  * no write statements anywhere in the tree (catches writable CTEs)
  * no unknown functions (blocks things like pg_sleep, pg_read_file)
  * every table is replaced by a subquery limited to the current user's rows
  * a row limit is always applied
"""
import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError


class SQLRejected(ValueError):
    pass


SCOPED_TABLES = {
    "transactions": "SELECT * FROM transactions WHERE user_id = {uid}",
    "accounts": "SELECT * FROM accounts WHERE user_id = {uid}",
    "transaction_lines": (
        "SELECT l.* FROM transaction_lines l "
        "JOIN transactions t ON t.id = l.transaction_id WHERE t.user_id = {uid}"
    ),
}

FORBIDDEN_NODES = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Drop,
    exp.Create,
    exp.Alter,
    exp.Command,
    exp.Merge,
    exp.Into,
    exp.TruncateTable,
)


def make_safe_sql(sql: str, user_id: int, dialect: str, row_limit: int) -> str:
    if not sql or not sql.strip():
        raise SQLRejected("empty query")

    try:
        statements = [s for s in sqlglot.parse(sql, read=dialect) if s is not None]
    except SqlglotError:
        raise SQLRejected("could not parse the query")

    if len(statements) != 1:
        raise SQLRejected("exactly one statement is allowed")
    tree = statements[0]

    if not isinstance(tree, exp.Select):
        raise SQLRejected("only SELECT statements are allowed")
    if tree.find(*FORBIDDEN_NODES):
        raise SQLRejected("write or schema statements are not allowed")
    if tree.find(exp.Anonymous):
        raise SQLRejected("unknown or unsafe function")

    cte_names = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
    tables = list(tree.find_all(exp.Table))
    for table in tables:
        if table.args.get("db") or table.args.get("catalog"):
            raise SQLRejected("schema-qualified tables are not allowed")
        name = table.name.lower()
        if name in cte_names:
            continue
        if name not in SCOPED_TABLES:
            raise SQLRejected(f"table '{table.name}' is not allowed")

    for table in tables:
        name = table.name.lower()
        if name in cte_names:
            continue
        inner = sqlglot.parse_one(SCOPED_TABLES[name].format(uid=int(user_id)), read="postgres")
        alias = table.alias or table.name
        table.replace(exp.Subquery(this=inner, alias=exp.TableAlias(this=exp.to_identifier(alias))))

    limit = tree.args.get("limit")
    try:
        current = int(limit.expression.name) if limit is not None else None
    except (ValueError, AttributeError):
        current = None
    if current is None or current > row_limit:
        tree = tree.limit(row_limit)

    return tree.sql(dialect=dialect)
