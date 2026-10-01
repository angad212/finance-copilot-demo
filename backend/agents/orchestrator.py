from collections import Counter

from sqlalchemy import select

from agents.categorization import categorize_transaction
from agents.fraud import run_fraud_checks
from ledger import LOAD_LINES
from models import Transaction


async def run_pipeline(session, llm, user_id: int, limit: int = 200) -> dict:
    """pending transactions -> categorization -> fraud checks.

    A transaction that cannot be categorized is never lost: it lands in
    `needs_review` with a failed or low-confidence agent run explaining why.
    """
    pending = (await session.scalars(
        select(Transaction)
        .where(Transaction.user_id == user_id, Transaction.status == "pending")
        .order_by(Transaction.txn_date, Transaction.id)
        .limit(limit)
        .options(LOAD_LINES)
    )).all()

    outcomes = Counter()
    for txn in pending:
        outcomes[await categorize_transaction(session, llm, user_id, txn)] += 1
        await session.commit()  # keep progress if a later transaction fails

    fraud = await run_fraud_checks(session, llm, user_id)
    await session.commit()
    return {
        "processed": len(pending),
        "categorized": outcomes["categorized"],
        "cache_hits": outcomes["cache_hit"],
        "needs_review": outcomes["needs_review"],
        **fraud,
    }
