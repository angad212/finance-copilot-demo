"""Natural-language questions -> validated, user-scoped SQL -> grounded answer."""
import json
from datetime import date

from sqlalchemy import text

from config import settings
from db import engine, sqlglot_dialect
from llm import with_backoff
from sql_guard import SQLRejected, make_safe_sql

MAX_TURNS = 4
REFUSAL = "I couldn't answer that safely."

SCHEMA_DOC = """Tables (already limited to the current user's data):
transactions(id, txn_date DATE, description, status)
transaction_lines(id, transaction_id -> transactions.id, account_id -> accounts.id, debit, credit)
accounts(id, name, type)   -- type is one of: asset, liability, equity, income, expense
Each transaction has 2+ lines; debits equal credits.
Spending = SUM(debit) on lines whose account type is 'expense'.
Income = SUM(credit) on lines whose account type is 'income'.
Account names are categories (for example Software, Travel, Meals)."""

SYSTEM = (
    "You answer questions about a small business's finances by querying a PostgreSQL-style database "
    "with the run_sql_query tool.\n" + SCHEMA_DOC + "\n"
    f"Today is {{today}}. Only write SELECT queries. Answer ONLY from tool results; never invent numbers. "
    "If the data cannot answer the question, say so plainly. Keep answers short."
)

TOOLS = [{
    "name": "run_sql_query",
    "description": "Run one read-only SQL SELECT query against the user's ledger and get the rows back.",
    "input_schema": {
        "type": "object",
        "properties": {"sql": {"type": "string", "description": "A single SELECT statement"}},
        "required": ["sql"],
    },
}]


async def run_safe_query(user_id: int, sql: str) -> tuple[list[dict], str]:
    """Validate, scope, and run a query on its own read-only connection."""
    safe = make_safe_sql(sql, user_id, sqlglot_dialect(), settings.sql_row_limit)
    async with engine.connect() as conn:
        if engine.dialect.name == "postgresql":
            await conn.exec_driver_sql("SET TRANSACTION READ ONLY")
            await conn.exec_driver_sql("SET LOCAL statement_timeout = 5000")
        result = await conn.exec_driver_sql(safe)
        rows = [dict(r._mapping) for r in result.fetchall()]
    return rows, safe


async def answer_question(llm, user_id: int, question: str) -> dict:
    messages = [{"role": "user", "content": question}]
    executed: list[str] = []
    rejected = 0

    for _ in range(MAX_TURNS):
        response = await with_backoff(lambda: llm.messages.create(
            model=settings.llm_model, max_tokens=600, temperature=0,
            system=SYSTEM.format(today=date.today().isoformat()),
            tools=TOOLS, messages=messages,
        ))
        if response.stop_reason != "tool_use":
            answer = "".join(b.text for b in response.content if getattr(b, "type", "") == "text").strip()
            if not executed and rejected:
                return {"answer": REFUSAL, "sql": [], "refused": True}
            return {"answer": answer or REFUSAL, "sql": executed, "refused": not answer}

        messages.append({"role": "assistant", "content": response.content})
        results = []
        for block in response.content:
            if getattr(block, "type", "") != "tool_use":
                continue
            sql = (block.input or {}).get("sql", "")
            try:
                rows, _ = await run_safe_query(user_id, sql)
                executed.append(sql)
                content, is_error = json.dumps(rows, default=str)[:6000], False
            except SQLRejected as e:
                rejected += 1
                content, is_error = f"Rejected: {e}. Write a single read-only SELECT on the listed tables.", True
            except Exception:
                rejected += 1
                content, is_error = "The query failed to run. Check the column names and try again.", True
            results.append({"type": "tool_result", "tool_use_id": block.id, "content": content, "is_error": is_error})
        messages.append({"role": "user", "content": results})

    return {"answer": REFUSAL, "sql": executed, "refused": True}
